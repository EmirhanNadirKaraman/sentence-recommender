"""Loopback HTTP capacity audit against existing data; no credentials needed.

Run from the repository: .venv/bin/python benchmarks/web_capacity.py --out /tmp/capacity.json
Uses the real router and four separate Application/Viewer caches. Synthetic
sessions read the owner's existing state snapshot, so this measures same-list
users, not different progress/list combinations. No account, grade, ingestion,
LLM, or cover-save requests are sent. GET routes may refresh derived caches.
The test server is bound to an ephemeral loopback port and shuts down on exit.
"""
from __future__ import annotations

import argparse
import cProfile
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import platform
import pstats
import resource
import re
import statistics
import subprocess
import sys
from threading import Thread
import time
from types import SimpleNamespace
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import Settings
from context import Application
from readers import Registry
from web.server import Door, ThreadingHTTPServer, _make_handler

ROUTES = ['/', '/words?q=geben', '/reels', '/subtitles', '/channels',
          '/review', '/hear', '/mine', '/quiz', '/starred', '/lists',
          '/cover', '/journey', '/plan', '/roadmap', '/frontier',
          '/blocked', '/study', '/watch', '/anki', '/settings',
          '/api/cover-search?q=haus', '/api/reels?i=1']


def rss_mb():
    if sys.platform == 'linux':
        pages = int(Path('/proc/self/statm').read_text().split()[1])
        return pages * os.sysconf('SC_PAGE_SIZE') / 2**20
    return int(subprocess.check_output(['ps', '-o', 'rss=', '-p', str(os.getpid())])) / 1024


def peak_mb():
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value / (2**20 if sys.platform == 'darwin' else 1024)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--users', type=int, default=4, choices=range(1, 5))
    parser.add_argument('--rounds', type=int, default=3)
    parser.add_argument('--profile', action='store_true', help='Adds profiler overhead; do not compare latency directly')
    parser.add_argument('--routes', nargs='+', default=ROUTES)
    args = parser.parse_args()
    owner = Registry().owner()
    settings = Settings.for_reader(owner) if owner else Settings()
    before = rss_mb()
    apps = {f'capacity-{i}': Application(settings) for i in range(args.users)}
    readers = {name: SimpleNamespace(name=name, joined='invite') for name in apps}
    registry = SimpleNamespace(shared=True, session=lambda token: readers.get(token),
                               owner=lambda: readers['capacity-0'])
    door = Door(apps['capacity-0'], registry=registry, apps=apps, google=None)
    base = _make_handler(door)
    timings, profiles = [], []

    class Handler(base):
        def log_message(self, *args):
            pass

        def _route(self, path, query, viewers):
            start, cpu = time.perf_counter(), time.thread_time()
            profile = cProfile.Profile() if args.profile else None
            if profile:
                profile.enable()
            try:
                return super()._route(path, query, viewers)
            finally:
                if profile:
                    profile.disable()
                    profiles.append(profile)
                timings.append({'path': path, 'wall_ms': (time.perf_counter() - start) * 1000,
                                'thread_cpu_ms': (time.thread_time() - cpu) * 1000})

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    address = f'http://127.0.0.1:{server.server_port}'
    results = []

    def request(route, user, phase):
        join = '&' if '?' in route else '?'
        url = address + route + join + 'src=subtitle&list=study_list'
        start = time.perf_counter()
        status, size, error = 0, 0, ''
        try:
            with urlopen(Request(url, headers={'Cookie': f'i1_session=capacity-{user}'}), timeout=180) as response:
                status, size = response.status, len(response.read())
        except Exception as caught:
            error = type(caught).__name__
            status = getattr(caught, 'code', 0)
        answer = dict(route=route, user=user, phase=phase, status=status, bytes=size,
                      wall_ms=round((time.perf_counter() - start) * 1000, 2), error=error)
        results.append(answer)
        return answer

    memory = [{'stage': 'imports', 'rss_mb': before}]
    try:
        for route in args.routes:
            answer = request(route, 0, 'first-pass')
            print(json.dumps(answer), flush=True)
            memory.append({'stage': 'first ' + route, 'rss_mb': rss_mb(), 'peak_mb': peak_mb()})
        for route in args.routes:
            for _ in range(args.rounds):
                request(route, 0, 'warm-single')
            print(json.dumps({'warm_single': route}), flush=True)
        memory.append({'stage': 'one user warm', 'rss_mb': rss_mb(), 'peak_mb': peak_mb()})
        # The corpus base is already loaded; this tests per-reader cache costs
        # and simultaneous personal-view construction, not four fresh hosts.
        with ThreadPoolExecutor(max_workers=args.users) as pool:
            started = time.perf_counter()
            cold = list(pool.map(lambda i: request('/reels', i, 'additional-user-first'), range(args.users)))
            print(json.dumps({'additional_users': cold, 'elapsed_s': time.perf_counter() - started}), flush=True)
            for route in args.routes:
                for _ in range(args.rounds):
                    list(pool.map(lambda i: request(route, i, 'concurrent'), range(args.users)))
                print(json.dumps({'concurrent_done': route}), flush=True)
        memory.append({'stage': 'all users warm', 'rss_mb': rss_mb(), 'peak_mb': peak_mb()})
        summary = []
        for route in args.routes:
            row = {'route': route}
            for phase in ('first-pass', 'warm-single', 'concurrent'):
                samples = sorted(r['wall_ms'] for r in results if r['route'] == route and r['phase'] == phase)
                row[phase] = {'n': len(samples), 'median_ms': round(statistics.median(samples), 2),
                              'max_ms': samples[-1]}
            summary.append(row)
        report = {'host': platform.platform(), 'architecture': platform.machine(), 'logical_cpus': os.cpu_count(),
                  'users': args.users, 'profiled': args.profile, 'memory': memory,
                  'summary': summary, 'requests': results, 'server_timings': timings}
        if sys.platform == 'darwin':
            # RSS omits compressed/swapped pages on macOS. Keep the footprint
            # summary too; Linux VPS sizing must not use the tiny idle RSS.
            try:
                vm = subprocess.check_output(['vmmap', '-summary', str(os.getpid())],
                                             text=True, timeout=20, stderr=subprocess.DEVNULL)
                report['mac_footprint'] = re.findall(r'^Physical footprint.*$', vm, re.MULTILINE)
            except (OSError, subprocess.SubprocessError):
                report['mac_footprint'] = ['unavailable']
        with apps['capacity-0'].corpus_store._read() as cur:
            cur.execute('SELECT pg_database_size(current_database()), count(*) FROM corpus_sentence')
            db_bytes, sentences = cur.fetchone()
        report['database'] = {'bytes': db_bytes, 'sentences': sentences}
        if profiles:
            stats = pstats.Stats(profiles[0])
            for profile in profiles[1:]:
                stats.add(profile)
            project = str(Path(__file__).resolve().parents[1]) + '/'
            functions = [dict(file=key[0].removeprefix(project), line=key[1], function=key[2],
                              calls=value[1], self_s=round(value[2], 3), cumulative_s=round(value[3], 3))
                         for key, value in stats.stats.items() if key[0].startswith(project)
                         and '/.venv/' not in key[0] and 'benchmarks/' not in key[0]]
            report['profile_by_self'] = sorted(functions, key=lambda row: -row['self_s'])[:35]
            report['profile_by_cumulative'] = sorted(functions, key=lambda row: -row['cumulative_s'])[:35]
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps({'saved': str(args.out), 'memory': memory[-2:],
                          'errors': [r for r in results if r['status'] != 200]}), flush=True)
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
