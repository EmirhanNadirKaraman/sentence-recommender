"""Talking to the local model over Tailscale.

Targets the OpenAI-compatible `/v1/chat/completions` shape, which Ollama,
LM Studio, llama.cpp's server and vLLM all speak — so the endpoint can change
without touching this file.  Configure it in `.env`:

    LLM_BASE_URL=http://<tailscale-host>:11434/v1
    LLM_MODEL=<model name>

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
    ) -> None:
        self._base_url = (base_url or os.environ.get("LLM_BASE_URL", "")).rstrip("/")
        self._model = model or os.environ.get("LLM_MODEL", "")
        self._timeout = timeout

    @property
    def available(self) -> bool:
        return bool(self._base_url and self._model)

    def complete(self, system: str, user: str, temperature: float = 0.7) -> str:
        """One chat completion.  Raises on transport or protocol failure —
        callers decide whether to retry or fall back."""
        if not self.available:
            raise RuntimeError(
                "No local model configured; set LLM_BASE_URL and LLM_MODEL in .env"
            )
        response = requests.post(
            f"{self._base_url}/chat/completions",
            json={
                "model": self._model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": temperature,
                "stream": False,
            },
            timeout=self._timeout,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()
