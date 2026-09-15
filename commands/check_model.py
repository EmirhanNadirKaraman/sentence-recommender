"""`check-model` — is the local model reachable, and how fast is it?

Run this when wiring up a new endpoint. A tunnel that refuses you and a
tunnel that is not there look much the same from inside a long job, so this
asks the two cheap questions first — does the URL answer, does the secret
work — and only then asks the model to say something.

The timing is the point of the last part. How long a run over the whole deck
takes is a property of that machine and that model, and no amount of
arithmetic here substitutes for one measured round trip.
"""
from __future__ import annotations

import time

import requests

from generation.client import LLMClient

SYSTEM = "You translate German for a learner. Answer with the translation only."


def _message(response) -> str:
    """Whatever the endpoint said, however it chose to say it."""
    try:
        body = response.json()
    except ValueError:
        return response.text[:300].strip()
    error = body.get("error", body)
    if isinstance(error, dict):
        return str(error.get("message") or error)[:300]
    return str(error)[:300]
PROBE = "Was kann man aus der Geschichte anderer Länder lernen?"


class CheckModelCommand:
    def run(self, app, steps: int = 3861, per_step_tokens: int = 200) -> None:
        client = LLMClient()
        print(f"configured: {client.describe()}")
        # Only the URL is required to get this far. Listing what an endpoint
        # serves is how you find out what to put in LLM_MODEL, so demanding
        # LLM_MODEL first made the one command that answers the question
        # refuse to run until it had been answered.
        if not client.endpoint:
            raise SystemExit(
                "LLM_BASE_URL is not set in .env — see the Setup section of "
                "the README")

        try:
            served = client.models()
        except requests.HTTPError as error:
            code = error.response.status_code
            if code in (401, 403):
                raise SystemExit(
                    f"the endpoint answered {code}: the secret was refused.\n"
                    "  Try another shape in .env — LLM_AUTH=bearer (default),\n"
                    "  LLM_AUTH=basic with LLM_USER, or LLM_AUTH=header with\n"
                    "  LLM_AUTH_HEADER naming the header your tunnel wants.")
            if code == 404:
                raise SystemExit(
                    "the endpoint answered 404 for /models. LLM_BASE_URL "
                    "usually has to end in /v1")
            raise SystemExit(f"the endpoint answered {code}")
        except requests.RequestException as error:
            raise SystemExit(f"could not reach it: {type(error).__name__}")

        print(f"reachable · {len(served)} model(s) served")
        # Named rather than counted: the usual mistake after a fresh pull is
        # a tag that does not match, and the list is the answer to it.
        for name in served:
            here = "   <- LLM_MODEL" if name == client.model else ""
            print(f"    {name}{here}")
        if not served:
            print("  the endpoint answered, but serves nothing — start a "
                  "model on that machine first")
        if not client.model:
            raise SystemExit(
                "\nLLM_MODEL is not set. Copy one of the names above into "
                ".env:\n    LLM_MODEL=" + (served[0] if served else "<name>"))
        if served and client.model not in served:
            print(f"  warning: LLM_MODEL is {client.model!r}, which is not in "
                  "that list — a completion will probably fail")

        started = time.perf_counter()
        try:
            answer = client.complete(SYSTEM, PROBE, temperature=0.2)
        except requests.HTTPError as error:
            # The server's own words. A wrapper that reports `HTTPError` and
            # drops the body hides the one sentence that says what to do --
            # this endpoint answers a cold model with "No model loaded. ...
            # Or enable Model auto-switch", which is the entire fix.
            raise SystemExit(
                f"completion failed: {error.response.status_code}\n  "
                + _message(error.response))
        except requests.RequestException as error:
            raise SystemExit(f"completion failed: {type(error).__name__}")
        spent = time.perf_counter() - started

        print(f"\n  {PROBE}")
        print(f"  -> {answer}")
        # Four characters to the token is the usual rule of thumb for
        # English, and this is a rate rather than a promise.
        tokens = max(len(answer) / 4, 1)
        print(f"\n  {spent:.2f}s for about {tokens:.0f} tokens "
              f"({tokens / spent:.1f}/s)")
        each = per_step_tokens / max(tokens / spent, 1e-9)
        hours = steps * each / 3600
        print(f"  {steps:,} steps at ~{per_step_tokens} tokens each: "
              f"{hours:.1f} h single-stream, "
              f"{hours / 4:.1f} h at four in flight")
        print("  (one round trip, so treat it as an order of magnitude)")
