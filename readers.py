"""Who is reading.

This was one person's program, so everything they decided -- the words they
know, their cards, their plans -- lived in one SQLite file and every page
assumed one reader. A second reader needs three things the first never did:
a place of their own for what they decide, a language of their own, and a
door that knows which of them is asking.

The place is a directory, `data/readers/<name>/`, holding the reader's own
state file and vocabulary files. The first reader's are where they always
were, at the top of `data/`: that file is half a gigabyte of judgements, and
moving it would buy nothing but the risk. A reader's `home` says which.

The door is a password and a signed cookie. The cookie carries the reader's
name and when it expires, signed with a key kept beside the registry, and
the signature also covers the reader's password hash -- so changing a
password signs every device out without anything having to remember which
sessions exist.

The registry, the key and every reader's directory are gitignored: this
repository is public, and the only things in here are other people's.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from threading import RLock

from languages import NATIVE, language

ROOT = Path(__file__).resolve().parent
READERS = ROOT / "data" / "readers"

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

    @property
    def state_path(self) -> Path:
        return self.home / "state.sqlite3"


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

    An installation with no registry is the program as it always was: one
    reader, no login. The first `reader add` makes it a shared one.
    """

    def __init__(self, root: Path = READERS) -> None:
        self._root = root
        self._file = root / "readers.json"
        self._key_file = root / "session.key"
        # Re-entrant: spending an invitation makes the account under the same
        # lock, so two people holding one link cannot both use it.
        self._lock = RLock()
        self._failures: dict[str, list[float]] = {}

    # --- who there is -----------------------------------------------------

    def readers(self) -> dict[str, Reader]:
        try:
            raw = json.loads(self._file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        out: dict[str, Reader] = {}
        for name, fields in raw.get("readers", {}).items():
            home = Path(fields.get("home") or self._root / name)
            out[name] = Reader(
                name=name,
                language=fields.get("language", "de"),
                native=fields.get("native", "en"),
                home=home if home.is_absolute() else ROOT / home,
                password=fields.get("password", ""),
            )
        return out

    def get(self, name: str) -> Reader | None:
        return self.readers().get(name)

    def names(self) -> list[str]:
        return sorted(self.readers())

    @property
    def shared(self) -> bool:
        """Whether anyone has to log in: true once any reader has a password."""
        return any(reader.password for reader in self.readers().values())

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
        for reader in readers.values():
            if reader.home == ROOT / "data":
                return reader
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
        with self._lock:
            raw = self._read()
            if name in raw["readers"]:
                raise SystemExit(f"there is already a reader called {name!r}")
            fields = {"language": lang, "native": native}
            if home is not None:
                fields["home"] = _relative(home)
            raw["readers"][name] = fields
            self._write(raw)
        reader = self.get(name)
        reader.home.mkdir(parents=True, exist_ok=True)
        # The closed classes and the starter words, theirs to strike from: the
        # quiz comments out what they say they do not know, and the
        # language's own files are in the repository for every reader of it.
        # See `Settings.for_reader`.
        profile = language(lang)
        copies = [(profile.function_words,
                   reader.home / profile.function_words.name)]
        if profile.starter_words is not None:
            copies.append((profile.starter_words,
                           reader.home / "known_words.txt"))
        for shared, mine in copies:
            if shared.exists() and not mine.exists() and mine != shared:
                mine.write_bytes(shared.read_bytes())
        return reader

    def set_password(self, name: str, password: str) -> None:
        if len(password) < 8:
            raise SystemExit("a password needs at least eight characters")
        if len(password) > 1024:
            raise SystemExit("that password is longer than anyone types")
        with self._lock:
            raw = self._read()
            if name not in raw["readers"]:
                raise SystemExit(f"no reader called {name!r}")
            raw["readers"][name]["password"] = hash_password(password)
            self._write(raw)

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
        with self._lock:
            raw = self._read()
            # Expired ones go whenever a new one is made.
            invites = {key: found for key, found in raw.get("invites", {}).items()
                       if found["expires"] > now}
            invites[_digest(token)] = {"language": lang, "native": native,
                                       "expires": int(now + days * 86400)}
            raw["invites"] = invites
            self._write(raw)
        return token

    def invitation(self, token: str) -> dict | None:
        """What `token` invites someone to be, if it is still good."""
        found = self._read().get("invites", {}).get(_digest(token or ""))
        if not found or found["expires"] < time.time():
            return None
        return found

    def redeem(self, token: str, name: str, password: str) -> Reader:
        """Make the account `token` was for, and spend it."""
        if not NAME.match(name):
            raise SystemExit("a name is lowercase letters, digits, - and _, "
                             "starting with a letter")
        if not 8 <= len(password) <= 1024:
            raise SystemExit("a password needs at least eight characters")
        with self._lock:
            found = self.invitation(token)
            if found is None:
                raise SystemExit("this invitation has expired or has already "
                                 "been used")
            if name in self.readers():
                raise SystemExit(f"the name {name!r} is taken")
            raw = self._read()
            raw["invites"].pop(_digest(token), None)
            self._write(raw)
            reader = self.add(name, found["language"], found["native"])
            self.set_password(name, password)
        return self.get(reader.name)

    def _read(self) -> dict:
        try:
            raw = json.loads(self._file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raw = {}
        raw.setdefault("readers", {})
        return raw

    def _write(self, raw: dict) -> None:
        """Whole or not at all: a half-written registry locks everyone out."""
        self._root.mkdir(parents=True, exist_ok=True)
        spare = self._file.with_suffix(".tmp")
        spare.write_text(json.dumps(raw, indent=2, sort_keys=True) + "\n",
                         encoding="utf-8")
        os.chmod(spare, 0o600)
        os.replace(spare, self._file)

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
        """The signing key, made the first time it is needed."""
        try:
            return bytes.fromhex(self._key_file.read_text(encoding="ascii").strip())
        except FileNotFoundError:
            pass
        with self._lock:
            if not self._key_file.exists():
                self._root.mkdir(parents=True, exist_ok=True)
                fd = os.open(self._key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                             0o600)
                with os.fdopen(fd, "w", encoding="ascii") as out:
                    out.write(secrets.token_hex(32) + "\n")
        return bytes.fromhex(self._key_file.read_text(encoding="ascii").strip())


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
