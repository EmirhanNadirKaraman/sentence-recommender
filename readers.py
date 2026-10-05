"""Who is reading.

This was one person's program, so everything they decided -- the words they
know, their cards, their plans -- lived in one file and every page assumed
one reader. A second reader needs three things the first never did: a place
of their own for what they decide, a language of their own, and a door that
knows which of them is asking.

The place is two: a schema in Postgres for everything the program stores
for them (see `state`), and a directory for the two word files they edit as
text, `known_words.txt` and `function_words.txt`. The first reader's are
where an installation's always were -- the schema `reader` and the top of
`data/` -- and everyone else's are `reader_<name>` and
`data/readers/<name>/`. A reader's `home` says which.

The door is a password and a signed cookie. The cookie carries the reader's
name and when it expires, signed with a key kept in the database, and the
signature also covers the reader's password hash -- so changing a password
signs every device out without anything having to remember which sessions
exist.

Who the readers are lives in the database too, in a schema of its own,
`accounts`: names, languages, password hashes, open invitations, the
signing key. None of it is in this public repository, and none of it goes
out in a dump of the corpus (see README, "Moving the corpus").
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import RLock

from languages import NATIVE, language
from state import ensure, open_state

ROOT = Path(__file__).resolve().parent
READERS = ROOT / "data" / "readers"
ACCOUNTS = "accounts"

SCHEMA = """
CREATE TABLE IF NOT EXISTS reader (
    name     TEXT COLLATE "C" PRIMARY KEY,
    language TEXT COLLATE "C" NOT NULL,
    native   TEXT COLLATE "C" NOT NULL,
    -- Their directory, relative to the project when it is inside it. NULL
    -- is the usual `data/readers/<name>/`.
    home     TEXT COLLATE "C",
    password TEXT COLLATE "C" NOT NULL DEFAULT '',
    added    TEXT COLLATE "C" NOT NULL
);
-- Only a digest of each token: the link is the secret, and a copy of the
-- database is not a set of working links.
CREATE TABLE IF NOT EXISTS invite (
    digest   TEXT COLLATE "C" PRIMARY KEY,
    language TEXT COLLATE "C" NOT NULL,
    native   TEXT COLLATE "C" NOT NULL,
    expires  BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS secret (
    name  TEXT COLLATE "C" PRIMARY KEY,
    value TEXT COLLATE "C" NOT NULL
);
"""

# Lowercase letters, digits, `-` and `_`: the name is a directory and a
# cookie field, and neither should have to be escaped.
NAME = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")

# scrypt at the strength the standard library's own docs use as the
# example: 16 MiB and a few tens of milliseconds a guess on this machine.
# Logins are rare; guesses should not be.
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 14, 8, 1

# Half a year. A phone that installed the app should not be asked for a
# password every week; one that is lost is dealt with by changing it.
SESSION_SECONDS = 180 * 24 * 3600

# Wrong passwords before a name stops accepting tries, and for how long.
# Two people with real passwords never hit this; a script guessing does.
TRIES = 5
LOCKOUT_SECONDS = 15 * 60

# How long an invitation link stays good. Long enough to reach someone who
# is away for a weekend; short enough that one lying in an old chat is dead.
INVITE_DAYS = 7


@dataclass(frozen=True)
class Reader:
    """One person, the language they are learning and the one they speak."""

    name: str
    # Where their state and vocabulary files live.
    home: Path
    language: str = "de"
    native: str = "en"
    password: str = ""


def hash_password(password: str, salt: bytes | None = None) -> str:
    """`scrypt$n$r$p$salt$hash`, everything needed to check it later."""
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N,
                            r=SCRYPT_R, p=SCRYPT_P)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${digest.hex()}"


def check_password(password: str, stored: str) -> bool:
    """Whether `password` is the one `stored` was made from."""
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    found = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt),
                           n=int(n), r=int(r), p=int(p))
    return hmac.compare_digest(found.hex(), digest)


class Registry:
    """The readers this installation knows, and the key their cookies are
    signed with.

    An installation with no reader in it is the program as it always was:
    one reader, no login. The first reader with a password makes it a shared
    one.

    `config` is the `accounts` schema's connection; `homes` is where a
    reader's directory goes when they are not given one.
    """

    def __init__(self, config=None, homes: Path = READERS) -> None:
        if config is None:
            from config import DatabaseConfig                # noqa: PLC0415
            config = DatabaseConfig.owned(ACCOUNTS)
        self._db = config
        self._homes = homes
        self._ready = False
        # Re-entrant: spending an invitation makes the account under the same
        # lock, so two requests holding one link cannot both use it.
        self._lock = RLock()
        self._failures: dict[str, list[float]] = {}
        self._signing_key: bytes | None = None

    def _conn(self):
        if not self._ready:
            ensure(self._db, SCHEMA)
            self._ready = True
        return open_state(self._db)

    # --- who there is -----------------------------------------------------

    def readers(self) -> dict[str, Reader]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT name, language, native, home, password FROM reader"
                " ORDER BY name").fetchall()
        out: dict[str, Reader] = {}
        for name, lang, native, home, password in rows:
            where = Path(home) if home else self._homes / name
            out[name] = Reader(name=name,
                               home=where if where.is_absolute() else ROOT / where,
                               language=lang, native=native, password=password)
        return out

    def get(self, name: str) -> Reader | None:
        return self.readers().get(name)

    def names(self) -> list[str]:
        return sorted(self.readers())

    @property
    def shared(self) -> bool:
        """Whether anyone has to log in: true once any reader has a password."""
        with self._conn() as conn:
            return conn.execute(
                "SELECT EXISTS (SELECT 1 FROM reader WHERE password <> '')"
            ).fetchone()[0]

    def owner(self) -> Reader | None:
        """The reader whose files are the ones at the top of `data/`: who
        this installation belonged to before it had other readers, and who
        may invite them."""
        return next((r for r in self.readers().values()
                     if r.home == ROOT / "data"), None)

    def default(self) -> Reader | None:
        """Who a command run without `--reader` is.

        The reader living at the top of `data/` -- the one this installation
        belonged to before there were others -- or the only reader there is.
        """
        readers = self.readers()
        owner = next((r for r in readers.values() if r.home == ROOT / "data"),
                     None)
        if owner is not None:
            return owner
        return next(iter(readers.values())) if len(readers) == 1 else None

    # --- changing it ------------------------------------------------------

    def add(self, name: str, lang: str, native: str,
            home: Path | None = None) -> Reader:
        if not NAME.match(name):
            raise SystemExit(f"{name!r} is not a usable name: lowercase letters, "
                             "digits, - and _, starting with a letter")
        language(lang)                       # refuses an unknown one
        if native not in NATIVE:
            raise SystemExit(f"no native language {native!r} -- this project "
                             f"translates into {', '.join(sorted(NATIVE))}")
        with self._lock, self._conn() as conn:
            done = conn.execute(
                "INSERT INTO reader (name, language, native, home, added)"
                " VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                (name, lang, native, None if home is None else _relative(home),
                 datetime.now().isoformat(timespec="seconds")))
            if not done.rowcount:
                raise SystemExit(f"there is already a reader called {name!r}")
        reader = self.get(name)
        reader.home.mkdir(parents=True, exist_ok=True)
        self._copy_word_files(reader)
        return reader

    def set_password(self, name: str, password: str) -> None:
        if len(password) < 8:
            raise SystemExit("a password needs at least eight characters")
        if len(password) > 1024:
            raise SystemExit("that password is longer than anyone types")
        with self._lock, self._conn() as conn:
            done = conn.execute("UPDATE reader SET password = %s WHERE name = %s",
                                (hash_password(password), name))
            if not done.rowcount:
                raise SystemExit(f"no reader called {name!r}")

    # --- invitations ------------------------------------------------------
    #
    # How a new reader comes to exist without anyone typing at the server:
    # the owner makes a link -- in Settings, or `reader invite` -- and whoever
    # opens it picks a name and a password. The link carries a token kept
    # only as a digest, good once, for `INVITE_DAYS`; the language and the
    # language of the translations are the invitation's, not the visitor's
    # to choose. The owner themselves is made at the server, with `reader
    # add NAME --home data` and `reader password NAME`: whoever can type
    # there owns it anyway, and a web page that made the first account would
    # hand the installation to whoever reached it first.

    def invite(self, lang: str, native: str, days: int = INVITE_DAYS) -> str:
        """A token for `/signup?invite=...`, good once and for `days`."""
        language(lang)
        if native not in NATIVE:
            raise SystemExit(f"no native language {native!r} -- this project "
                             f"translates into {', '.join(sorted(NATIVE))}")
        token = secrets.token_urlsafe(18)
        now = time.time()
        with self._conn() as conn:
            # Expired ones go whenever a new one is made.
            conn.execute("DELETE FROM invite WHERE expires <= %s", (int(now),))
            conn.execute(
                "INSERT INTO invite (digest, language, native, expires)"
                " VALUES (%s, %s, %s, %s)",
                (_digest(token), lang, native, int(now + days * 86400)))
        return token

    def invitation(self, token: str) -> dict | None:
        """What `token` invites someone to be, if it is still good."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT language, native, expires FROM invite WHERE digest = %s",
                (_digest(token or ""),)).fetchone()
        if row is None or row[2] < time.time():
            return None
        return {"language": row[0], "native": row[1], "expires": row[2]}

    def redeem(self, token: str, name: str, password: str) -> Reader:
        """Make the account `token` was for, and spend it.

        Spent in the same transaction that checks it, and locked while it is
        read, so the same link opened twice at once makes one account.
        """
        if not NAME.match(name):
            raise SystemExit("a name is lowercase letters, digits, - and _, "
                             "starting with a letter")
        if not 8 <= len(password) <= 1024:
            raise SystemExit("a password needs at least eight characters")
        with self._lock, self._conn() as conn:
            row = conn.execute(
                "SELECT language, native, expires FROM invite WHERE digest = %s"
                " FOR UPDATE", (_digest(token or ""),)).fetchone()
            if row is None or row[2] < time.time():
                raise SystemExit("this invitation has expired or has already "
                                 "been used")
            if conn.execute("SELECT 1 FROM reader WHERE name = %s",
                            (name,)).fetchone():
                raise SystemExit(f"the name {name!r} is taken")
            conn.execute("DELETE FROM invite WHERE digest = %s",
                         (_digest(token),))
            conn.execute(
                "INSERT INTO reader (name, language, native, home, password,"
                " added) VALUES (%s, %s, %s, NULL, %s, %s)",
                (name, row[0], row[1], hash_password(password),
                 datetime.now().isoformat(timespec="seconds")))
        reader = self.get(name)
        reader.home.mkdir(parents=True, exist_ok=True)
        self._copy_word_files(reader)
        return reader

    @staticmethod
    def _copy_word_files(reader: Reader) -> None:
        """The closed classes and the starter words, theirs to strike from:
        the quiz comments out what they say they do not know, and the
        language's own files are in the repository for every reader of it.
        See `Settings.for_reader`."""
        profile = language(reader.language)
        copies = [(profile.function_words,
                   reader.home / profile.function_words.name)]
        if profile.starter_words is not None:
            copies.append((profile.starter_words,
                           reader.home / "known_words.txt"))
        for shared, mine in copies:
            if shared.exists() and not mine.exists() and mine != shared:
                mine.write_bytes(shared.read_bytes())

    # --- the door ---------------------------------------------------------

    def login(self, name: str, password: str) -> str | None:
        """A session cookie value for `name`, or None.

        A name that has failed too often stops accepting tries for a while,
        right or wrong, so a guesser learns nothing from the answer.
        """
        now = time.time()
        with self._lock:
            recent = [t for t in self._failures.get(name, ())
                      if now - t < LOCKOUT_SECONDS]
            self._failures[name] = recent
            if len(recent) >= TRIES:
                return None
        reader = self.get(name)
        # The hash is checked even for a name nobody has, against a dummy,
        # so the time taken does not say which names exist.
        stored = reader.password if reader and reader.password else _dummy()
        if check_password(password, stored) and reader and reader.password:
            with self._lock:
                self._failures.pop(name, None)
            return self.sign(reader, int(now) + SESSION_SECONDS)
        with self._lock:
            self._failures.setdefault(name, []).append(now)
        return None

    def locked(self, name: str) -> bool:
        now = time.time()
        with self._lock:
            return sum(1 for t in self._failures.get(name, ())
                       if now - t < LOCKOUT_SECONDS) >= TRIES

    def sign(self, reader: Reader, expires: int) -> str:
        return f"{reader.name}.{expires}.{self._signature(reader, expires)}"

    def session(self, cookie: str) -> Reader | None:
        """The reader a cookie value belongs to, if it is still good."""
        try:
            name, expires, signature = cookie.split(".")
            until = int(expires)
        except ValueError:
            return None
        if until < time.time():
            return None
        reader = self.get(name)
        if reader is None or not reader.password:
            return None
        if not hmac.compare_digest(signature, self._signature(reader, until)):
            return None
        return reader

    def _signature(self, reader: Reader, expires: int) -> str:
        # The password hash is signed over too, so a new password ends every
        # session the old one opened.
        message = f"{reader.name}.{expires}.{reader.password}".encode("utf-8")
        return hmac.new(self._key(), message, hashlib.sha256).hexdigest()

    def _key(self) -> bytes:
        """The signing key, made the first time it is needed and kept in the
        database, so every process serving this installation signs alike."""
        if self._signing_key is None:
            with self._conn() as conn:
                conn.execute(
                    "INSERT INTO secret (name, value) VALUES ('session', %s)"
                    " ON CONFLICT DO NOTHING", (secrets.token_hex(32),))
                (value,) = conn.execute(
                    "SELECT value FROM secret WHERE name = 'session'").fetchone()
            self._signing_key = bytes.fromhex(value)
        return self._signing_key


_DUMMY: list[str] = []


def _dummy() -> str:
    """Checked against when a name has no reader, so a wrong name costs as
    long as a wrong password. Its own password is unguessable and unused;
    made on first use, because every command imports this module and only
    the login page needs it."""
    if not _DUMMY:
        _DUMMY.append(hash_password(secrets.token_hex(16)))
    return _DUMMY[0]


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _relative(path: Path) -> str:
    path = path.resolve()
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)
