"""Talking to the local model, wherever it is.

Targets the OpenAI-compatible `/v1/chat/completions` shape, which Ollama,
LM Studio, llama.cpp's server and vLLM all speak — so the endpoint can change
without touching this file.  Configure it in `.env`:

    LLM_BASE_URL=http://<tailscale-host>:11434/v1
    LLM_MODEL=<model name>

A machine on the LAN or on Tailscale usually needs nothing more. Reached
through a public tunnel — a Cloudflare one, say — it wants a secret as well,
because the URL is on the open internet:

    LLM_BASE_URL=https://<name>.trycloudflare.com/v1
    LLM_API_KEY=<the password>
    LLM_AUTH=bearer            # or: basic, header

`bearer` is the default and is what an OpenAI-compatible server means by an
API key. `basic` is for a tunnel put behind HTTP basic auth, and takes
`LLM_USER` too. `header` sends the secret under a name of your choosing in
`LLM_AUTH_HEADER`, which is how Cloudflare Access service tokens work.
`check-model` says which of them your endpoint actually wants.

The key is read from the environment and never written anywhere — not into a
log line, not into an error. `describe` exists so a failure can be reported
without it.

With no `LLM_BASE_URL` set, `LLMClient.available` is False and every caller
falls back to its non-LLM path.  Nothing in the project requires a model to
be reachable.
"""
from __future__ import annotations

import os

import requests


class LLMClient:
    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float = 120.0,
        api_key: str | None = None,
        auth: str | None = None,
    ) -> None:
        self._base_url = (base_url or os.environ.get("LLM_BASE_URL", "")).rstrip("/")
        self._model = model or os.environ.get("LLM_MODEL", "")
        self._timeout = timeout
        self._api_key = api_key or os.environ.get("LLM_API_KEY", "")
        self._auth = (auth or os.environ.get("LLM_AUTH", "bearer")).lower()

    @property
    def available(self) -> bool:
        return bool(self._base_url and self._model)

    @property
    def model(self) -> str:
        return self._model

    @property
    def endpoint(self) -> str:
        return self._base_url

    def describe(self) -> str:
        """Where it points and how it authenticates — never the secret."""
        how = f"{self._auth} auth" if self._api_key else "no auth"
        return f"{self._base_url or '(unset)'} · {self._model or '(no model)'} · {how}"

    def _headers(self) -> dict[str, str]:
        """The auth header this endpoint was configured to want.

        Three shapes because a tunnel can be fronted three ways, and getting
        it wrong looks identical from here: a 401 with an HTML body. The
        alternative was to try each in turn, which sends the secret to an
        endpoint that has already refused it once.
        """
        if not self._api_key:
            return {}
        if self._auth == "basic":
            import base64                                # noqa: PLC0415
            user = os.environ.get("LLM_USER", "")
            pair = f"{user}:{self._api_key}".encode()
            return {"Authorization": "Basic " + base64.b64encode(pair).decode()}
        if self._auth == "header":
            name = os.environ.get("LLM_AUTH_HEADER", "CF-Access-Client-Secret")
            return {name: self._api_key}
        return {"Authorization": f"Bearer {self._api_key}"}

    def models(self) -> list[str]:
        """What the endpoint says it serves.

        The cheapest thing that exercises the URL and the secret together,
        which is why `check-model` asks this before it asks for a completion.
        """
        response = requests.get(f"{self._base_url}/models",
                                headers=self._headers(), timeout=self._timeout)
        response.raise_for_status()
        body = response.json()
        return sorted(str(m.get("id", "")) for m in body.get("data", []))

    def slots(self) -> int | None:
        """How many requests the server answers at once, if it will say.

        llama.cpp reports it as `total_slots` on `/props`, which sits beside
        `/v1` rather than under it. Anything else -- vLLM, Ollama, a server
        that hides the endpoint -- answers with something that is not that,
        and gets None: the caller then falls back to a fixed count rather
        than to a guess dressed up as a measurement.

        Worth asking because the answer sets the ceiling. A request past the
        slot count queues, and a pool sized to the queue rather than the
        server was measured slower, not merely no faster.
        """
        root = self._base_url[:-3] if self._base_url.endswith("/v1") \
            else self._base_url
        try:
            response = requests.get(f"{root}/props", headers=self._headers(),
                                    timeout=self._timeout)
            response.raise_for_status()
            slots = int(response.json()["total_slots"])
        except (requests.RequestException, ValueError, KeyError, TypeError):
            return None
        return slots if slots > 0 else None

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Vectors for a batch of sentences, in the order they were given.

        A batch rather than one call per sentence, and by a wide margin: the
        same endpoint answers 16.9 sentences a second at 32 per request and
        49.5 at 128, because almost all of the cost is the round trip.

        The order is checked rather than trusted. The API returns an `index`
        on every row and nothing forbids a server from answering out of
        order; a silently shuffled batch would attach every vector to the
        wrong sentence, and nothing downstream could notice.
        """
        if not self.available:
            raise RuntimeError(
                "No local model configured; set LLM_BASE_URL and LLM_MODEL in .env"
            )
        response = requests.post(
            f"{self._base_url}/embeddings",
            headers=self._headers(),
            json={"model": self._model, "input": texts},
            timeout=self._timeout,
        )
        response.raise_for_status()
        rows = response.json()["data"]
        if len(rows) != len(texts):
            raise RuntimeError(
                f"asked for {len(texts)} embeddings and got {len(rows)}")
        rows = sorted(rows, key=lambda row: row.get("index", 0))
        return [row["embedding"] for row in rows]

    def complete(self, system: str, user: str, temperature: float = 0.7,
                 response_format: dict | None = None) -> str:
        """One chat completion.  Raises on transport or protocol failure —
        callers decide whether to retry or fall back."""
        if not self.available:
            raise RuntimeError(
                "No local model configured; set LLM_BASE_URL and LLM_MODEL in .env"
            )
        body = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "stream": False,
        }
        if response_format is not None:
            # Guided decoding: the server constrains what the model may emit,
            # so a malformed answer becomes impossible rather than merely
            # discouraged. A backend with no grammar engine refuses the
            # request outright, which is the safe way to fail -- it cannot
            # quietly answer prose that ignores the contract.
            body["response_format"] = response_format
        response = requests.post(
            f"{self._base_url}/chat/completions",
            headers=self._headers(),
            json=body,
            timeout=self._timeout,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()
