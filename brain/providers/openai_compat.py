"""
OpenAI-compatible provider (Ollama, LM Studio, vLLM, OpenAI, OpenRouter...).

Talks to {base_url}/v1/chat/completions over plain HTTP requests — no extra
dependency beyond `requests`, which Keys.ai already ships.

This is what makes the brain model-agnostic: point it at any OpenAI-compatible
endpoint via config/api_keys.json (llm_provider / llm_model / llm_url) and it
just works.
"""

from __future__ import annotations

from brain.providers.base import LLMProvider, ProviderError, parse_json


class OpenAICompatProvider(LLMProvider):
    name = "openai_compat"

    def __init__(self, base_url: str = "http://localhost:11434",
                 model: str = "tinyllama", api_key: str = "",
                 timeout: float = 600.0, num_ctx: int | None = None,
                 extra_options: dict | None = None):
        self.base_url = base_url.rstrip("/")
        # Context window for local runtimes. Ollama's default (4096) leaves no
        # room for a long instruction block plus the model's own answer, so a
        # page-writing run loses its brief and starts improvising. Callers that
        # send big prompts raise this.
        self.num_ctx = num_ctx
        self.extra_options = dict(extra_options or {})
        # Accept "http://host:11434", "http://host:1234/v1", and a fully
        # qualified ".../v1/chat/completions". Posting to a bare "/v1" (as this
        # used to for a /v1 base) is not a completions route: LM Studio and
        # vLLM answered 404 and the chat went silent.
        if self.base_url.endswith("/chat/completions"):
            self.endpoint = self.base_url
        elif self.base_url.endswith("/v1"):
            self.endpoint = self.base_url + "/chat/completions"
        else:
            self.endpoint = self.base_url + "/v1/chat/completions"
        self.model    = model
        self.api_key  = api_key
        self.timeout  = timeout
        # Native /api/chat availability on a local runtime: None = untested.
        # Ollama exposes it (and the only way to switch reasoning off);
        # LM Studio / vLLM answer 404, so we fall back to the OpenAI endpoint.
        self._native: bool | None = None

    def _is_local(self) -> bool:
        return any(h in self.base_url for h in ("localhost", "127.0.0.1", "0.0.0.0", "::1"))

    def _messages_for_call(self, messages: list[dict], no_think: bool) -> list[dict]:
        """Silence Qwen3 reasoning for local calls.

        Qwen3 models emit a long hidden reasoning block on every request. For
        structured output (slides, rows) that costs 2-5x the wall time and can
        consume the whole token budget, returning an empty answer. The model
        honours the documented '/no_think' soft switch; other models never see
        it, and hosted endpoints are left untouched.
        """
        if not (no_think and self._is_local() and "qwen3" in self.model.lower()):
            return messages
        out = [dict(m) for m in messages]
        for m in reversed(out):
            if m.get("role") == "user":
                if "/no_think" not in (m.get("content") or ""):
                    m["content"] = (m.get("content") or "") + "\n\n/no_think"
                break
        return out

    def _native_url(self) -> str:
        base = self.base_url[:-3] if self.base_url.endswith("/v1") else self.base_url
        return base.rstrip("/") + "/api/chat"

    def _post_native(self, messages: list[dict], temperature: float,
                     max_tokens: int | None) -> str:
        """Ollama /api/chat with reasoning disabled.

        Qwen3 class models spend thousands of hidden reasoning tokens before
        answering; on this hardware that is 11 tok/s, i.e. minutes of dead time
        for one deck. Ollama's OpenAI endpoint has no switch for it, the native
        endpoint does ("think": false). Raise FileNotFoundError when the
        runtime has no native endpoint so the caller can fall back.
        """
        import requests
        options: dict = {"temperature": temperature}
        if max_tokens:
            options["num_predict"] = max_tokens
        if self.num_ctx:
            options["num_ctx"] = int(self.num_ctx)
        options.update(self.extra_options)
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "think": False,
            "options": options,
        }
        try:
            resp = requests.post(self._native_url(), json=payload,
                                 timeout=(10, self.timeout))
        except Exception as e:
            raise ProviderError(
                f"Ollama request to {self._native_url()} failed: {e}"
            ) from e
        if resp.status_code in (404, 405):
            raise FileNotFoundError(self._native_url())
        resp.raise_for_status()
        data = resp.json()
        return (data.get("message") or {}).get("content", "").strip()

    def _post(self, messages: list[dict], temperature: float,
              max_tokens: int | None, no_think: bool = True) -> str:
        if self._is_local() and self._native is not False:
            try:
                text = self._post_native(messages, temperature, max_tokens)
                self._native = True
                return text
            except FileNotFoundError:
                self._native = False   # not Ollama; use the OpenAI endpoint
            except ProviderError:
                raise
            except Exception as e:
                raise ProviderError(
                    f"Ollama request to {self._native_url()} failed: {e}"
                ) from e
        return self._post_openai(messages, temperature, max_tokens, no_think)

    def _post_openai(self, messages: list[dict], temperature: float,
                     max_tokens: int | None, no_think: bool = True) -> str:
        import requests
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {
            "model": self.model,
            "messages": self._messages_for_call(messages, no_think),
            "temperature": temperature,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens
        try:
            resp = requests.post(
                self.endpoint, json=payload, headers=headers,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            return (data.get("choices") or [{}])[0].get("message", {}).get(
                "content", ""
            ).strip()
        except Exception as e:
            raise ProviderError(
                f"OpenAI-compatible request to {self.endpoint} failed: {e}"
            ) from e

    def _messages(self, prompt: str, system: str | None) -> list[dict]:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return messages

    def stream(self, prompt: str, system: str | None = None,
               on_token=None, temperature: float = 0.2,
               max_tokens: int | None = None) -> str:
        """Stream a completion, calling on_token(delta) as it arrives.

        Falls back to a single blocking call when the runtime has no streaming
        endpoint. Callers use this to show real progress while a long file is
        being written instead of a frozen percentage.
        """
        if not (self._is_local() and self._native is not False):
            text = self.generate(prompt, system=system, temperature=temperature,
                                 max_tokens=max_tokens)
            if on_token:
                on_token(text)
            return text
        try:
            text = self._stream_native(self._messages(prompt, system),
                                       temperature, max_tokens, on_token)
            self._native = True
            return text
        except FileNotFoundError:
            self._native = False
            text = self.generate(prompt, system=system, temperature=temperature,
                                 max_tokens=max_tokens)
            if on_token:
                on_token(text)
            return text

    def _stream_native(self, messages: list[dict], temperature: float,
                       max_tokens: int | None, on_token=None) -> str:
        import json as _json
        import requests
        options: dict = {"temperature": temperature}
        if max_tokens:
            options["num_predict"] = max_tokens
        if self.num_ctx:
            options["num_ctx"] = int(self.num_ctx)
        options.update(self.extra_options)
        payload = {"model": self.model, "messages": messages, "stream": True,
                   "think": False, "options": options}
        try:
            resp = requests.post(self._native_url(), json=payload,
                                 timeout=(10, self.timeout), stream=True)
        except Exception as e:
            raise ProviderError(f"Ollama stream to {self._native_url()} failed: {e}") from e
        if resp.status_code in (404, 405):
            raise FileNotFoundError(self._native_url())
        resp.raise_for_status()
        parts: list[str] = []
        for line in resp.iter_lines(decode_unicode=True):
            if not line:
                continue
            try:
                chunk = _json.loads(line)
            except Exception:
                continue
            piece = (chunk.get("message") or {}).get("content") or ""
            if piece:
                parts.append(piece)
                if on_token:
                    try:
                        on_token(piece)
                    except Exception:
                        pass
            if chunk.get("done"):
                break
        return "".join(parts).strip()

    def generate(self, prompt: str, system: str | None = None,
                 temperature: float = 0.2,
                 max_tokens: int | None = None) -> str:
        text = self._post(self._messages(prompt, system), temperature, max_tokens)
        if not text and self._is_local():
            # Local runtimes occasionally return an empty message on a warm
            # model (context swap, cancelled sibling request). One retry, then
            # surface the failure instead of handing back an empty string.
            text = self._post(self._messages(prompt, system), temperature, max_tokens)
        if not text:
            raise ProviderError(
                f"{self.model} returned an empty completion from {self.endpoint}"
            )
        return text

    def structured_output(self, prompt: str, system: str | None = None,
                          temperature: float = 0.0) -> dict | None:
        json_prompt = (
            prompt
            + "\n\nIMPORTANT: Reply with ONLY a valid JSON object. "
            "No prose, no markdown fences."
        )
        text = self._post(self._messages(json_prompt, system),
                          temperature, None)
        return parse_json(text)
