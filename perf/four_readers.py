"""Four-reader capacity probe, with disposable state and read-only corpus.

Requires local PostgreSQL binaries. No real reader is created or changed.
Results contain timings/counts only; the temporary state dump is deleted.
HTTP adapter bypasses login but executes the real Viewer page methods.
"""
from __future__ import annotations

import argparse
import cProfile
import ctypes
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import pstats
import resource
import struct
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def memory_mb(pid):
    if sys.platform == 'darwin':
        # SDK sys/resource.h: rusage_info_v2 has UUID[16], then 18 uint64s;
        # ri_phys_footprint is the eighth uint64. Includes compressed memory.
        info = ctypes.create_string_buffer(160)
        libproc = ctypes.CDLL('/usr/lib/libproc.dylib')
        if libproc.proc_pid_rusage(pid, 2, ctypes.byref(info)) != 0:
            return None
        return struct.unpack_from('Q', info.raw, 72)[0] / (1024 * 1024)
    sampled = subprocess.check_output(['ps', '-o', 'rss=', '-p', str(pid)], text=True).strip()
    return int(sampled) / 1024 if sampled else None


def emit(value):
    # macOS reports ru_maxrss in bytes; Linux reports KiB.
    scale = 1024 * 1024 if sys.platform == 'darwin' else 1024
    usage = resource.getrusage(resource.RUSAGE_SELF)
    value['peak_rss_mb'] = round(usage.ru_maxrss / scale)
    value['cpu_seconds'] = round(usage.ru_utime + usage.ru_stime, 3)
    if sys.platform == 'darwin' and value.get('event') == 'phase':
        # RSS misses compressed/swapped pages on macOS. Record footprint too.
        value['physical_footprint_mb'] = round(memory_mb(os.getpid()))
    print(json.dumps(value), flush=True)


def worker(args):
    import psycopg2
    from config import DatabaseConfig, Settings
    from context import Application
    from web.server import Viewers
    from corpus.shared import CorpusPool

    settings = Settings()
    original = DatabaseConfig.dsn_kwargs
    production = (settings.own.name, settings.own.host, settings.own.port)

    def guarded(config):
        kw = original(config)
        if (config.name, config.host, config.port) == production:
            kw['options'] += ' -c default_transaction_read_only=on'
        return kw

    DatabaseConfig.dsn_kwargs = guarded
    # Verify the guard on the exact connection configuration used by pages.
    with psycopg2.connect(**settings.own.dsn_kwargs()) as conn:
        with conn.cursor() as cur:
            cur.execute('SHOW default_transaction_read_only')
            assert cur.fetchone()[0] == 'on'
            cur.execute('SELECT build, count(*) FROM corpus_sentence '
                        'WHERE teachable GROUP BY build ORDER BY build')
            emit({'event': 'corpus', 'builds': cur.fetchall()})

    viewers = []
    corpus_pool = CorpusPool()
    for n in range(1, 5):
        home = Path(args.scratch) / f'files{n}'
        shutil.copytree(settings.data_dir, home,
                        ignore=shutil.ignore_patterns('voices', '*.sqlite3*', '*.dump'))
        state = replace(settings.state, name='postgres', user=os.environ['USER'],
                        password='', host=args.scratch, port=args.pg_port,
                        schema=f'probe{n}')
        made = replace(settings, state=state, reader=f'probe{n}', data_dir=home,
                       known_words=home / settings.known_words.name,
                       goal_words=home / settings.goal_words.name,
                       function_words=home / 'function_words.txt'
                       if (home / 'function_words.txt').exists()
                       else settings.function_words)
        app = Application(made)
        app.corpus_pool = corpus_pool
        viewers.append(Viewers(app, keep=1))

    routes = {'/': 'next_up', '/reels': 'reels', '/subtitles': 'subtitles',
              '/review': 'review', '/words': 'word_search', '/lists': 'word_lists'}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *unused):
            pass

        def do_GET(self):
            parsed = urlsplit(self.path)
            q = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            who = int(q.pop('user')) - 1
            try:
                v = viewers[who].pick(q)
                if args.mode == 'profile':
                    profile = cProfile.Profile()
                    profile.enable()
                    body = getattr(v, routes[parsed.path])(q).encode()
                    profile.disable()
                    stats = pstats.Stats(profile)
                    top = sorted(stats.stats.items(), key=lambda pair: pair[1][3], reverse=True)[:25]
                    emit({'event': 'profile', 'route': parsed.path,
                          'top_cumulative': [{'function': f'{Path(key[0]).name}:{key[1]}:{key[2]}',
                                              'calls': val[1], 'self_seconds': round(val[2], 3),
                                              'cumulative_seconds': round(val[3], 3)}
                                             for key, val in top]})
                else:
                    body = getattr(v, routes[parsed.path])(q).encode()
                self.send_response(200)
            except Exception as error:
                import traceback
                traceback.print_exc()
                body = str(error).encode()
                self.send_response(500)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{server.server_port}'

    def request(user, route, source='subtitle'):
        query = {'user': user, 'src': source, 'list': 'everyday_words'}
        begin = time.perf_counter()
        try:
            with urlopen(base + route + '?' + urlencode(query), timeout=180) as r:
                payload = r.read()
                status, size, error = r.status, len(payload), None
        except Exception as exc:
            status, size, error = getattr(exc, 'code', 0), 0, str(exc)
        return {'user': user, 'route': route, 'source': source, 'status': status,
                'seconds': round(time.perf_counter() - begin, 4),
                'bytes': size, 'error': error}

    def phase(name, jobs, concurrent=False):
        emit({'event': 'begin', 'phase': name})
        begin = time.perf_counter()
        if concurrent:
            with ThreadPoolExecutor(max_workers=4) as pool:
                rows = list(pool.map(lambda job: request(*job), jobs))
        else:
            rows = [request(*job) for job in jobs]
        emit({'event': 'phase', 'phase': name,
              'wall_seconds': round(time.perf_counter() - begin, 3), 'requests': rows})
        if any(row['status'] != 200 for row in rows):
            raise RuntimeError(f'{name}: failed page; latency results are invalid')

    try:
        if args.mode == 'profile':
            phase('profile_cold_home', [(1, '/')])
            phase('profile_first_reels', [(1, '/reels')])
            phase('profile_warm_pages', [(1, route) for route in routes])
        elif args.mode == 'cold-parallel':
            phase('four_simultaneous_first_visits', [(n, '/') for n in range(1, 5)], True)
        else:
            for n in range(1, 5):
                phase(f'cold_reader_{n}', [(n, '/')])
                phase(f'first_reels_reader_{n}', [(n, '/reels')])
            phase('warm_four_readers', [(n, route) for _ in range(3)
                  for route in routes for n in range(1, 5)], True)
            # Real writes, exclusively to the disposable state database.
            emit({'event': 'begin', 'phase': 'mark_and_reels'})
            def mark(n):
                v = viewers[n - 1].pick({'list': 'everyday_words'})
                idx = v.scope('subtitle', list_only=False).index
                unit = next(u for u in idx.candidates() if u not in v.known)
                begin = time.perf_counter()
                v.mark_known({'kind': unit.kind, 'key': unit.key,
                              'action': 'known', 'src': 'subtitle'})
                acknowledged = time.perf_counter() - begin
                v._marks.join()
                return {'user': n, 'ack_seconds': round(acknowledged, 4),
                        'settled_seconds': round(time.perf_counter() - begin, 4),
                        'reels': request(n, '/reels')}
            with ThreadPoolExecutor(max_workers=4) as pool:
                rows = list(pool.map(mark, range(1, 5)))
            emit({'event': 'phase', 'phase': 'mark_and_reels', 'results': rows})
            # Switching source exposes a second cache dimension.
            phase('second_source_reader_1', [(1, '/', 'all')])
    finally:
        server.shutdown()


def run(args):
    from config import Settings
    settings = Settings()
    result = Path(args.output).resolve()
    result.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='four-readers-') as folder:
        pgdata = Path(folder) / 'pg'
        subprocess.run(['initdb', '-D', str(pgdata), '-A', 'trust', '--no-locale', '-E', 'UTF8'],
                       check=True, stdout=subprocess.DEVNULL)
        subprocess.run(['pg_ctl', '-D', str(pgdata), '-l', folder + '/postgres.log',
                        '-o', f'-k {folder} -p {args.pg_port} -h ""', 'start'],
                       check=True, stdout=subprocess.DEVNULL)
        try:
            env = dict(os.environ, PGPASSWORD=settings.state.password)
            dump_path = Path(folder) / 'reader.sql'
            with dump_path.open('wb') as backup:
                subprocess.run([
                    'pg_dump', '-h', settings.state.host, '-p', str(settings.state.port),
                    '-U', settings.state.user, '-d', settings.state.name,
                    '--schema', settings.state.schema, '--no-owner', '--no-privileges'],
                    env=env, stdout=backup, check=True)
            # Stream the dump instead of keeping two multi-GB byte strings in
            # the parent throughout the application test. That hidden memory
            # pressure distorts cold timings even when child memory is bounded.
            for n in range(1, 2 if args.mode == 'profile' else 5):
                command = ['psql', '-h', folder, '-p', str(args.pg_port),
                           '-d', 'postgres', '-v', 'ON_ERROR_STOP=1']
                with dump_path.open('rb') as backup, subprocess.Popen(
                        command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL) as restore:
                    for line in backup:
                        line = line.replace((settings.state.schema + '.').encode(), f'probe{n}.'.encode())
                        line = line.replace(('SCHEMA ' + settings.state.schema).encode(), f'SCHEMA probe{n}'.encode())
                        restore.stdin.write(line)
                    restore.stdin.close()
                    if restore.wait() != 0:
                        raise subprocess.CalledProcessError(restore.returncode, command)
            subprocess.run(['psql', '-h', folder, '-p', str(args.pg_port),
                            '-d', 'postgres', '-c', 'ANALYZE'], check=True,
                           stdout=subprocess.DEVNULL)
            command = [sys.executable, str(Path(__file__).resolve()), '--worker',
                       '--scratch', folder, '--pg-port', str(args.pg_port), '--mode', args.mode]
            peak = 0
            with result.open('w') as output:
                child = subprocess.Popen(command, stdout=output)
                try:
                    while child.poll() is None:
                        sampled = memory_mb(child.pid)
                        if sampled is not None:
                            peak = max(peak, sampled)
                        if peak > args.max_memory_mb:
                            child.terminate()
                            output.write(json.dumps({'event': 'memory_limit', 'peak_memory_mb': round(peak),
                                                     'limit_mb': args.max_memory_mb}) + '\n')
                            break
                        time.sleep(0.5)
                    child.wait(timeout=10)
                finally:
                    if child.poll() is None:
                        child.kill()
                        child.wait()
                output.write(json.dumps({'event': 'summary', 'mode': args.mode,
                                         'memory_metric': 'physical_footprint' if sys.platform == 'darwin' else 'rss',
                                         'peak_memory_mb': round(peak), 'exit_code': child.returncode}) + '\n')
            emit({'output': str(result), 'peak_memory_mb': round(peak), 'exit_code': child.returncode})
            if child.returncode != 0:
                raise SystemExit(1)
        finally:
            subprocess.run(['pg_ctl', '-D', str(pgdata), 'stop', '-m', 'fast'],
                           check=True, stdout=subprocess.DEVNULL)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', default='/tmp/four-readers.jsonl')
    p.add_argument('--mode', choices=['staged', 'cold-parallel', 'profile'], default='staged')
    p.add_argument('--max-memory-mb', '--max-rss-mb', dest='max_memory_mb', type=int,
                   default=6000, help='Stop at this process footprint (macOS) or RSS (Linux), in MiB')
    p.add_argument('--pg-port', type=int, default=18891)
    p.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    p.add_argument('--scratch', help=argparse.SUPPRESS)
    options = p.parse_args()
    if options.worker:
        import faulthandler
        import traceback
        faulthandler.dump_traceback_later(45, repeat=True)
        try:
            worker(options)
        except Exception:
            traceback.print_exc()
            sys.stdout.flush()
            os._exit(1)
        faulthandler.cancel_dump_traceback_later()
        # The disposable child has no pending writes after phase joins.
        # Avoid walking gigabytes of swapped Python objects during final GC;
        # the parent owns PostgreSQL shutdown and temporary-directory cleanup.
        sys.stdout.flush()
        os._exit(0)
    else:
        run(options)
