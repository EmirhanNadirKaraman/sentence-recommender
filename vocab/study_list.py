"""Building the one list that says both what to learn and in what order.

Two files hold half the answer each:

  `words_4000.txt`     the order — curated, most useful first — but it names
                       words in their bare dictionary shape
  `final_result.txt`   the shape the matcher and `phrase_table` actually
                       speak, `etw./jdn. (Akk) haben` rather than `haben`,
                       but in an order of its own

They join on `final_result`'s first column, which is exactly what
`words_4000` lists — 4,095 of 4,096 lines match outright. The merge walks
`words_4000` in order, swapping each entry for its blueprint, then appends
whatever `final_result` knows that the ordering file never mentioned, so
nothing learnable is lost just because it was not ranked.

The result is written to disk rather than computed each time: it is the
answer to "what am I studying, and in what order", and that deserves to be
a file you can read and edit.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

HEADER = """\
# The study list: what to learn, in the order to learn it.
#
# Two tab-separated columns — the word as it is usually written, then the
# form the matcher speaks. The second column is the one that counts; the
# first is there so this stays readable.
#
# Order is priority. Everything above the divider comes from
# {order_file}, which is ranked; everything below is known to
# {form_file} but was never ranked, so it sits at the end.
#
# Generated {today}. Rebuild with:  python main.py build-study-list
"""

DIVIDER = "\n# --- below here: known forms that the ranked list never named ---\n"


class StudyListBuilder:
    """Merges a ranking and a form dictionary into one ordered list."""

    def __init__(self, order_file: Path, form_file: Path) -> None:
        self._order_file = order_file
        self._form_file = form_file

    def build(self) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
        """The ranked (word, form) pairs, and the unranked leftovers."""
        forms = self._forms()
        ranked: list[tuple[str, str]] = []
        used: set[str] = set()
        for word in self._order():
            form = forms.get(word)
            if form is None:
                # Not in the form dictionary; keep it as written, since a
                # ranked word with no known blueprint is still worth learning.
                form = word
            if form in used:
                continue
            used.add(form)
            ranked.append((word, form))

        rest = [(word, form) for word, form in forms.items() if form not in used]
        return ranked, rest

    def write(self, path: Path) -> tuple[int, int]:
        ranked, rest = self.build()
        lines = [HEADER.format(today=date.today().isoformat(),
                               order_file=self._order_file.name,
                               form_file=self._form_file.name)]
        lines.extend(f"{word}\t{form}" for word, form in ranked)
        lines.append(DIVIDER)
        lines.extend(f"{word}\t{form}" for word, form in rest)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return len(ranked), len(rest)

    # --- the two halves ---------------------------------------------------

    def _order(self) -> list[str]:
        """The ranking file, one entry per line, comments and blanks dropped."""
        out: list[str] = []
        seen: set[str] = set()
        for raw in self._order_file.read_text(encoding="utf-8").splitlines():
            line = raw.split("#", 1)[0].strip()
            if line and line not in seen:
                seen.add(line)
                out.append(line)
        return out

    def _forms(self) -> dict[str, str]:
        """word -> the form the matcher speaks, first mention winning.

        First mention because a word recurs under several blueprints and the
        earliest is the one the dictionary leads with.
        """
        forms: dict[str, str] = {}
        for raw in self._form_file.read_text(encoding="utf-8").splitlines():
            columns = raw.split("\t")
            if len(columns) < 2:
                continue
            word, form = columns[0].strip(), columns[1].strip()
            if word and form:
                forms.setdefault(word, form)
        return forms
