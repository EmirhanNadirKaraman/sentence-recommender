"""Signing in with Google: OpenID Connect's code flow, by hand.

Three steps, and the standard library does each.

1. `start` sends the browser to Google with a fresh `state`, a `nonce` and a
   PKCE challenge, and remembers them here, server-side, under the state.
   The state also goes into a cookie, so the answer can only be finished in
   the browser that asked: a sign-in begun by someone else and slipped into
   your browser arrives without it.
2. Google sends the browser back to `/auth/google/callback` with a code.
3. `finish` trades the code -- with the PKCE verifier and the client secret
   -- for an ID token, straight from Google's token endpoint over verified
   TLS. That channel is why the token's signature need not be checked
   (OpenID Connect Core 3.1.3.7); its issuer, audience, expiry and nonce
   still are.

A reader is known by the token's `sub`, Google's own unchanging id for the
account, and never by the email address, which can change hands.

Configured by three lines in `.env`: `GOOGLE_CLIENT_ID` and
`GOOGLE_CLIENT_SECRET` from the Google Cloud console, and `PUBLIC_URL`, the
address readers type. Google sends the browser back to `PUBLIC_URL` and
nowhere else, so a sign-in has to begin there too -- the cookie that has to
meet the answer is that host's. Without all three there is no Google button.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass
from threading import Lock
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

AUTHORIZE = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN = "https://oauth2.googleapis.com/token"
ISSUERS = frozenset({"https://accounts.google.com", "accounts.google.com"})
CALLBACK = "/auth/google/callback"

# The cookie that carries the state through Google and back. Scoped to the
# two paths that use it, and short-lived like the state itself.
COOKIE = "i1_google"
COOKIE_PATH = "/auth/google"

# How long a sign-in may take between leaving for Google and coming back,
# and how many may be under way at once -- the oldest go first past that,
# so a flood of starts cannot grow this without bound.
PENDING_SECONDS = 600
PENDING_MAX = 256

# Clock difference forgiven on the token's expiry.
SKEW = 60


class Refused(Exception):
    """Why a sign-in with Google did not finish, in words for the page."""


@dataclass(frozen=True)
class Pending:
    """A sign-in under way: what it is for, and what to check it against."""

    purpose: str            # "signin", "signup" or "link"
    verifier: str
    nonce: str
    started: float
    next: str = "/"
    # signup: the name they picked; link: the reader linking.
    name: str = ""
    language: str = ""
    native: str = ""
    invite: str = ""


@dataclass(frozen=True)
class Identity:
    """Who Google says came back."""

    subject: str
    # The address, when Google vouches for it; "" when it does not.
    email: str


def configured() -> bool:
    """Whether `.env` has everything a Google sign-in needs."""
    from config import load_dotenv                       # noqa: PLC0415
    load_dotenv()
    return all(os.environ.get(k, "").strip() for k in
               ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "PUBLIC_URL"))


class GoogleSignIn:
    """The client side of Google's sign-in, for one installation."""

    def __init__(self, client_id: str, client_secret: str, base_url: str,
                 post=None) -> None:
        self.client_id = client_id
        self._secret = client_secret
        self.base_url = base_url.rstrip("/")
        self.redirect_uri = self.base_url + CALLBACK
        # How the code is traded for a token: a POST to Google, or a stand-in.
        self._post = post or _post_form
        self._pending: dict[str, Pending] = {}
        self._lock = Lock()

    @classmethod
    def from_env(cls) -> "GoogleSignIn | None":
        if not configured():
            return None
        return cls(os.environ["GOOGLE_CLIENT_ID"].strip(),
                   os.environ["GOOGLE_CLIENT_SECRET"].strip(),
                   os.environ["PUBLIC_URL"].strip())

    @property
    def host(self) -> str:
        """The host a sign-in has to begin and end on."""
        return urlparse(self.base_url).netloc

    @property
    def secure(self) -> bool:
        return self.base_url.startswith("https://")

    def start(self, purpose: str, **fields) -> tuple[str, str]:
        """Where to send the browser, and the state for its cookie."""
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode("ascii")).digest()
        ).rstrip(b"=").decode("ascii")
        nonce = secrets.token_urlsafe(16)
        now = time.time()
        with self._lock:
            for key in [k for k, p in self._pending.items()
                        if now - p.started > PENDING_SECONDS]:
                del self._pending[key]
            while len(self._pending) >= PENDING_MAX:
                del self._pending[next(iter(self._pending))]
            self._pending[state] = Pending(purpose, verifier, nonce, now,
                                           **fields)
        query = urlencode({
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": "openid email",
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            # Asked every time which account, so someone signed in to two
            # does not land in the wrong one without a word.
            "prompt": "select_account",
        })
        return f"{AUTHORIZE}?{query}", state

    def finish(self, state: str, cookie: str, code: str) -> tuple[Pending, Identity]:
        """The sign-in `state` began, and who Google says came back.

        Spent whether it succeeds or not: a state is good once.
        """
        if not (state and cookie and hmac.compare_digest(state, cookie)):
            raise Refused("This sign-in was begun in another browser, or "
                          "its page was opened twice. Start again.")
        with self._lock:
            pending = self._pending.pop(state, None)
        if pending is None or time.time() - pending.started > PENDING_SECONDS:
            raise Refused("This sign-in took too long, or the server was "
                          "restarted in the middle of it. Start again.")
        if not code:
            raise Refused("Google sent no answer to check. Start again.")
        try:
            answer = self._post(TOKEN, {
                "code": code,
                "client_id": self.client_id,
                "client_secret": self._secret,
                "redirect_uri": self.redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": pending.verifier,
            })
        except (OSError, ValueError) as error:
            raise Refused("Google did not confirm the sign-in. Try again in "
                          "a moment.") from error
        claims = _claims(answer.get("id_token", ""))
        audience = claims.get("aud")
        audiences = audience if isinstance(audience, list) else [audience]
        if claims.get("iss") not in ISSUERS or self.client_id not in audiences:
            raise Refused("That answer was not Google's, for this site.")
        if isinstance(audience, list) and claims.get("azp") != self.client_id:
            raise Refused("That answer was not Google's, for this site.")
        try:
            expires = float(claims.get("exp", 0))
        except (TypeError, ValueError):
            expires = 0.0
        if expires + SKEW < time.time():
            raise Refused("That answer from Google had already expired. "
                          "Start again.")
        if not hmac.compare_digest(str(claims.get("nonce", "")), pending.nonce):
            raise Refused("That answer was for another sign-in. Start again.")
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject:
            raise Refused("Google did not say whose account it was.")
        verified = claims.get("email_verified") in (True, "true")
        email = str(claims.get("email", "")) if verified else ""
        return pending, Identity(subject, email)


def _claims(token: str) -> dict:
    """The claims of a JWT, unchecked -- see the module docstring for why
    that is enough for one that came straight from Google."""
    try:
        payload = token.split(".")[1]
        padded = payload + "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except (IndexError, ValueError, UnicodeError):
        raise Refused("Google's answer could not be read. Start again.") from None
    if not isinstance(claims, dict):
        raise Refused("Google's answer could not be read. Start again.")
    return claims


def _post_form(url: str, fields: dict) -> dict:
    """A form POSTed over verified TLS, and the JSON that comes back -- an
    error's JSON too, which is where Google says what went wrong."""
    request = Request(url, data=urlencode(fields).encode("ascii"), method="POST",
                      headers={"Content-Type": "application/x-www-form-urlencoded",
                               "Accept": "application/json"})
    try:
        with urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        try:
            said = json.loads(error.read().decode("utf-8"))
        except ValueError:
            said = {}
        # Logged without the request, which carries the secret.
        print(f"Google refused the code: {error.code} "
              f"{said.get('error', '')} {said.get('error_description', '')}",
              flush=True)
        raise ValueError(said.get("error", "refused")) from None
    except URLError as error:
        raise OSError(str(error.reason)) from None
