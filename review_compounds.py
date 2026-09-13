#!/usr/bin/env python3
"""Check `data/compounds.txt` a word at a time, one keystroke each.

    python review_compounds.py

`o` keeps a split, `p` deletes it, `s` leaves it for later, `u` undoes the
last answer, `q` stops. `o` and `p` sit under two fingers of the same hand,
which is what makes a few hundred of these bearable.

The file is rewritten after every keystroke, so stopping is the same as
pausing and nothing is lost to a closed terminal or a Ctrl-C. Undo works the
same way: it rewrites too, so an undone mistake is gone from the file
immediately rather than at the end.

Written atomically -- to a temporary file, then renamed -- because a rewrite
after every key means an interrupted write is a question of when, not if, and
half a file of compounds is worse than none.

The marker in the file is the point of trust: only what sits above it counts,
so `y` moves a line above it and `n` removes the line entirely.
"""
from __future__ import annotations

import os
import sys
import termios
import tty
from pathlib import Path

FILE = Path(__file__).with_name("data") / "compounds.txt"
MARK = "# ===================== CHECKED TO HERE ====================="


def read():
    """Header, the lines already checked, the marker block, what is left."""
    text = FILE.read_text(encoding="utf-8")
    before, _, after = text.partition(MARK)
    marker_block, _, rest = after.partition("\n\n")
    head = [l for l in before.splitlines(keepends=True)]
    checked = [l for l in head if l.strip() and not l.lstrip().startswith("#")]
    header = [l for l in head if l not in checked]
    left = [l for l in rest.splitlines(keepends=True)
            if l.strip() and not l.lstrip().startswith("#")]
    return header, checked, MARK + marker_block + "\n\n", left


def write(header, checked, marker, left):
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text("".join(header) + "".join(checked) + "\n"
                   + marker + "".join(left), encoding="utf-8")
    os.replace(tmp, FILE)          # atomic: the file is never half-written


def key() -> str:
    """One keypress, without waiting for Enter."""
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        return sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)


def show(line: str, done: int, left: int) -> None:
    word, _, rest = line.partition("\t")
    parts, _, tail = rest.partition("\t")
    count = tail.strip().lstrip("# ").split()[0] if tail.strip() else "?"
    print(f"\r\033[K  {done:>4} kept · {left:>5} left"
          f"   \033[1m{word}\033[0m = {' + '.join(parts.split())}"
          f"   said {count}x", end="  ", flush=True)


def main() -> None:
    if not sys.stdin.isatty():
        raise SystemExit("this needs a real terminal — run it in one directly")
    header, checked, marker, left = read()
    print(f"  {len(checked)} already checked, {len(left):,} to go")
    print("  o keep · p delete · s skip · u undo · q stop\n")
    kept = deleted = skipped = 0
    # Every answer, so any of them can be taken back. A list rather than one
    # slot: the mistake you notice is often not the one you just made.
    history: list[tuple[str, str]] = []
    while left:
        show(left[0], len(checked), len(left))
        press = key().lower()
        if press in ("q", "\x03"):          # q or Ctrl-C
            break
        if press == "o":
            line = left.pop(0); checked.append(line)
            history.append(("o", line)); kept += 1
        elif press == "p":
            line = left.pop(0)
            history.append(("p", line)); deleted += 1
        elif press == "s":
            line = left.pop(0); left.append(line)
            history.append(("s", line)); skipped += 1
        elif press in ("u", "\x7f"):        # u or backspace
            if not history:
                continue
            what, line = history.pop()
            if what == "o":
                checked.pop(); left.insert(0, line); kept -= 1
            elif what == "p":
                left.insert(0, line); deleted -= 1
            else:
                left.pop(); left.insert(0, line); skipped -= 1
        else:
            continue                        # unknown key: ask again
        write(header, checked, marker, left)
    print(f"\n\n  {kept} kept · {deleted} deleted · {skipped} skipped"
          + (f" · {len(history)} answers this run" if history else ""))
    print(f"  {len(checked)} now above the marker, {len(left):,} below")


if __name__ == "__main__":
    main()
