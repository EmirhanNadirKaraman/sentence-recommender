"""Building the one list that says both what to learn and in what order.

Three files hold the answer between them:

  `words_4000.txt`     the order — curated, most useful first — but it names
                       words in their bare dictionary shape
  `final_result.txt`   the shape the matcher and `phrase_table` actually
                       speak, `etw./jdn. (Akk) haben` rather than `haben`,
                       but in an order of its own
  `expressions.txt`    the fixed expressions — `auf jeden Fall`, `eine Rolle
                       spielen`, `es gibt` — units found by their words,
                       which neither of the other two can name

The first two join on `final_result`'s first column, which is exactly what
`words_4000` lists — 4,095 of 4,096 lines match outright. The merge walks
`words_4000` in order, swapping each entry for its blueprint, then the
expressions in the order their file gives them, then appends whatever
`final_result` knows that the ordering file never mentioned, so nothing
learnable is lost just because it was not ranked.

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
# Order is priority. Everything above the first divider comes from
# {order_file}, which is ranked; then the fixed expressions of
# {expressions_file}; everything below the last divider is known to
# {form_file} but was never ranked, so it sits at the end.
#
# Generated {today}. Rebuild with:  python main.py build-study-list
"""

EXPRESSIONS = "\n# --- fixed expressions, from {expressions_file} ---\n"
DIVIDER = "\n# --- below here: known forms that the ranked list never named ---\n"
# Units the list carries by hand, because no source can. None today: `es
# gibt` was one until `expressions.txt` existed to name it. Kept so that
# `hand_edits` has a place to be told about the next one.
HAND_UNITS: frozenset[str] = frozenset()


class StudyListBuilder:
    """Merges a ranking and a form dictionary into one ordered list."""

    def __init__(self, order_file: Path, form_file: Path,
                 expressions_file: Path | None = None) -> None:
        self._order_file = order_file
        self._form_file = form_file
        self._expressions_file = expressions_file

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

    def hand_edits(self, path: Path) -> list[str]:
        """The lines a person wrote into the generated file.

        A `#` line that is not the generated header or the divider, and
        any `word<TAB>form` line the generator would not produce — a
        retirement written out (`# der, die, das`), a unit added by hand
        (`es gibt`, 2026-09-20). The word list is derived and can be
        rebuilt; the judgements about it cannot, and `build-study-list`
        used to write over both without saying so.
        """
        if not path.exists():
            return []
        rendered = HEADER.format(today="", order_file=self._order_file.name,
                                 form_file=self._form_file.name,
                                 expressions_file=self._expressions_name)
        header = {line.strip() for line in rendered.splitlines()}
        dividers = {DIVIDER.strip(),
                    EXPRESSIONS.format(expressions_file=self._expressions_name).strip()}
        found = []
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped in dividers:
                continue
            if stripped.startswith("#"):
                # The header, whose one dated line is matched by its prefix.
                if stripped in header or stripped.startswith("# Generated "):
                    continue
                found.append(line)
            elif "\t" in line and line.split("\t")[0].strip().lower() in HAND_UNITS:
                found.append(line)
        return found

    def write(self, path: Path, force: bool = False) -> tuple[int, int]:
        edits = self.hand_edits(path)
        if edits and not force:
            raise SystemExit(
                f"refusing: {path} holds {len(edits)} lines written by hand, and "
                f"a rebuild would write over them —\n  "
                + "\n  ".join(e[:70] for e in edits[:6])
                + ("\n  …" if len(edits) > 6 else "")
                + "\n\n  Pass --force to discard them, or fold them into the "
                "sources first.")
        ranked, rest = self.build()
        lines = [HEADER.format(today=date.today().isoformat(),
                               order_file=self._order_file.name,
                               form_file=self._form_file.name,
                               expressions_file=self._expressions_name)]
        lines.extend(f"{word}\t{form}" for word, form in ranked)
        expressions = self.expressions()
        if expressions:
            lines.append(EXPRESSIONS.format(expressions_file=self._expressions_name))
            lines.extend(f"{name}\t{name}" for name in expressions)
        lines.append(DIVIDER)
        lines.extend(f"{word}\t{form}" for word, form in rest)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return len(ranked), len(rest)

    @property
    def _expressions_name(self) -> str:
        return self._expressions_file.name if self._expressions_file else "expressions.txt"

    def expressions(self) -> tuple[str, ...]:
        """The fixed expressions, as their file orders them: each is both
        the word and the form, the canonical being the unit's key."""
        from vocab.expressions import canonicals                 # noqa: PLC0415
        if self._expressions_file is None:
            return ()
        return canonicals(self._expressions_file)

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
            # Comments stripped first, as `_order` above already does. A
            # retired entry is commented out rather than deleted, and it
            # keeps its tab — so splitting on the tab alone read the `#` as
            # part of the word and put `# der, die, das` in here as one.
            columns = raw.split("#", 1)[0].split("\t")
            if len(columns) < 2:
                continue
            word, form = columns[0].strip(), columns[1].strip()
            if word and form:
                forms.setdefault(word, form)
        return forms
