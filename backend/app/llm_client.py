"""Provider client factory for Ollama, OpenRouter, and Groq."""

from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from typing import Any

import httpx
from groq import AsyncGroq
from ollama import AsyncClient

from app.model_router import provider_name


class OpenRouterClient:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        self.api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        self.base_url = os.getenv(
            "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
        ).rstrip("/")
        self.transport = transport

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise RuntimeError(
                "LLM_PROVIDER=openrouter requires OPENROUTER_API_KEY in .env"
            )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        referer = os.getenv("OPENROUTER_HTTP_REFERER")
        title = os.getenv("OPENROUTER_APP_TITLE", "Patchwork")
        if referer:
            headers["HTTP-Referer"] = referer
        if title:
            headers["X-OpenRouter-Title"] = title
        return headers

    @staticmethod
    def _model_chain(primary_model: str) -> list[str]:
        configured = os.getenv("OPENROUTER_FALLBACK_MODELS")
        if configured is None:
            configured = os.getenv(
                "OPENROUTER_FALLBACK_MODEL",
                "qwen/qwen3.8-27b:free",
            )
        fallbacks = [model.strip() for model in configured.split(",") if model.strip()]
        return list(dict.fromkeys([primary_model, *fallbacks]))

    @staticmethod
    def _is_transient_error(status_code: int | None, detail: str | None) -> bool:
        if status_code in {408, 409, 429} or (status_code is not None and status_code >= 500):
            return True
        return bool(detail and any(token in detail.lower() for token in (
            "temporarily overloaded",
            "rate limit",
            "try again",
        )))

    @staticmethod
    def _error_detail(data: Any) -> str | None:
        error = data.get("error") if isinstance(data, dict) else None
        if not error:
            return None
        if isinstance(error, dict):
            message = error.get("message") or error.get("type")
            code = error.get("code")
            if message and code:
                return f"{message} (code {code})"
            if message:
                return str(message)
        return str(error)

    @staticmethod
    def _payload(
        model: str,
        prompt: str,
        options: dict[str, Any] | None,
        system: str | None,
        reasoning_enabled: bool = False,
        messages: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        request_messages = messages
        if request_messages is None:
            request_messages = []
            if system:
                request_messages.append({"role": "system", "content": system})
            request_messages.append({"role": "user", "content": prompt})

        options = options or {}
        payload: dict[str, Any] = {"model": model, "messages": request_messages}
        if reasoning_enabled:
            payload["reasoning"] = {"enabled": True}
        if "temperature" in options:
            payload["temperature"] = options["temperature"]
        if "num_predict" in options:
            payload["max_tokens"] = options["num_predict"]
        elif "max_tokens" in options:
            payload["max_tokens"] = options["max_tokens"]
        for option_name in ("response_format", "tools", "tool_choice", "parallel_tool_calls"):
            if option_name in options:
                payload[option_name] = options[option_name]
        return payload

    async def generate(
        self,
        *,
        model: str,
        prompt: str,
        think: bool = False,
        options: dict[str, Any] | None = None,
        system: str | None = None,
    ) -> SimpleNamespace:
        failures = []
        for candidate_model in self._model_chain(model):
            try:
                return await self._generate_once(
                    model=candidate_model,
                    prompt=prompt,
                    think=think,
                    options=options,
                    system=system,
                )
            except RuntimeError as error:
                if "no usable final text" in str(error):
                    try:
                        return await self._generate_once(
                            model=candidate_model,
                            prompt=prompt,
                            think=False,
                            options=options,
                            system=system,
                            reasoning_override=False,
                        )
                    except RuntimeError as retry_error:
                        error = retry_error
                failures.append(f"{candidate_model}: {error}")
        raise RuntimeError("OpenRouter model chain failed: " + " | ".join(failures))

    async def _generate_once(
        self,
        *,
        model: str,
        prompt: str,
        think: bool = False,
        options: dict[str, Any] | None = None,
        system: str | None = None,
        reasoning_override: bool | None = None,
    ) -> SimpleNamespace:
        reasoning_enabled = reasoning_override
        if reasoning_enabled is None:
            reasoning_enabled = think or os.getenv(
                "OPENROUTER_REASONING_ENABLED", "true"
            ).strip().lower() in {"1", "true", "yes", "on"}
        payload = self._payload(
            model,
            prompt,
            options,
            system,
            reasoning_enabled=reasoning_enabled,
        )
        return await self._request_completion(payload, model)

    async def continue_reasoning(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        options: dict[str, Any] | None = None,
    ) -> SimpleNamespace:
        """Continue a reasoning turn while preserving reasoning_details verbatim."""
        failures = []
        for candidate_model in self._model_chain(model):
            try:
                payload = self._payload(
                    candidate_model,
                    prompt="",
                    options=options,
                    system=None,
                    reasoning_enabled=True,
                    messages=messages,
                )
                return await self._request_completion(payload, candidate_model)
            except RuntimeError as error:
                failures.append(f"{candidate_model}: {error}")
        raise RuntimeError("OpenRouter reasoning model chain failed: " + " | ".join(failures))

    async def _request_completion(
        self,
        payload: dict[str, Any],
        requested_model: str,
    ) -> SimpleNamespace:
        max_attempts = max(1, int(os.getenv("OPENROUTER_MAX_ATTEMPTS", "3")))
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(120.0, connect=15.0),
            transport=self.transport,
        ) as client:
            for attempt in range(1, max_attempts + 1):
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=self._headers(),
                    json=payload,
                )

                try:
                    data = response.json()
                except ValueError:
                    data = {}
                error_detail = self._error_detail(data)

                if response.is_error or error_detail:
                    if attempt < max_attempts and self._is_transient_error(
                        response.status_code, error_detail
                    ):
                        retry_after = response.headers.get("Retry-After")
                        try:
                            delay = float(retry_after) if retry_after else 0.5 * (2 ** (attempt - 1))
                        except ValueError:
                            delay = 0.5 * (2 ** (attempt - 1))
                        await asyncio.sleep(min(delay, 15.0))
                        continue
                    if response.is_error:
                        detail = f": {error_detail}" if error_detail else ""
                        raise RuntimeError(
                            f"OpenRouter request failed with HTTP {response.status_code}{detail}"
                        )
                    raise RuntimeError(f"OpenRouter returned an API error: {error_detail}")

                if not isinstance(data, dict):
                    raise RuntimeError("OpenRouter returned invalid JSON")
                break
            else:
                raise RuntimeError("OpenRouter request failed after all retry attempts")

        if not isinstance(data, dict):
            raise RuntimeError("OpenRouter returned invalid JSON")

        choices = data.get("choices") if isinstance(data, dict) else None
        if not isinstance(choices, list) or not choices:
            response_id = data.get("id") if isinstance(data, dict) else None
            suffix = f" (response id {response_id})" if response_id else ""
            raise RuntimeError(
                f"OpenRouter returned no completion choices{suffix}; response shape was invalid"
            )

        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, list):
            content = "".join(
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and isinstance(part.get("text"), str)
            )
        if isinstance(content, dict):
            content = content.get("text") or content.get("content")
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("OpenRouter returned no usable final text")
        return SimpleNamespace(
            response=content,
            model=data.get("model", requested_model),
            reasoning_details=message.get("reasoning_details"),
        )

    async def list(self) -> SimpleNamespace:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(20.0, connect=10.0),
            transport=self.transport,
        ) as client:
            key_response = await client.get(
                f"{self.base_url}/key",
                headers=self._headers(),
            )
            if key_response.is_error:
                raise RuntimeError(
                    f"OpenRouter authentication check failed with HTTP {key_response.status_code}"
                )

            response = await client.get(
                f"{self.base_url}/models",
                headers=self._headers(),
            )
        if response.is_error:
            raise RuntimeError(f"OpenRouter model check failed with HTTP {response.status_code}")
        models = response.json().get("data", [])
        return SimpleNamespace(
            models=[SimpleNamespace(model=item.get("id", "")) for item in models]
        )


class GroqClient:
    def __init__(self, client: AsyncGroq | None = None):
        api_key = os.getenv("GROQ_API_KEY", "").strip()
        if not api_key and client is None:
            raise RuntimeError("LLM_PROVIDER=groq requires GROQ_API_KEY in .env")
        self.client = client or AsyncGroq(api_key=api_key)

    async def generate(
        self,
        *,
        model: str,
        prompt: str,
        think: bool = False,
        options: dict[str, Any] | None = None,
        system: str | None = None,
    ) -> SimpleNamespace:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        options = options or {}
        request: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": options.get("temperature", 1),
            "top_p": options.get("top_p", 1),
        }
        if "num_predict" in options:
            request["max_completion_tokens"] = options["num_predict"]
        elif "max_tokens" in options:
            request["max_completion_tokens"] = options["max_tokens"]

        reasoning_effort = os.getenv("GROQ_REASONING_EFFORT", "medium").strip()
        reasoning_effort = str(options.get("reasoning_effort", reasoning_effort)).strip()
        if reasoning_effort:
            request["reasoning_effort"] = reasoning_effort
        for option_name in ("response_format", "tools", "tool_choice", "parallel_tool_calls"):
            if option_name in options:
                request[option_name] = options[option_name]

        completion = None
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                completion = await self.client.chat.completions.create(**request)
                break
            except Exception as error:
                last_error = error
                status_code = getattr(error, "status_code", None)
                detail = str(error).lower()
                if status_code != 413 and "tokens per minute" not in detail:
                    raise RuntimeError(f"Groq request failed: {error}") from error
                current_limit = int(request.get("max_completion_tokens", 2048))
                request["max_completion_tokens"] = max(512, current_limit // 2)
                request["reasoning_effort"] = "low"
        if completion is None:
            raise RuntimeError(f"Groq request failed: {last_error}") from last_error

        choices = getattr(completion, "choices", None)
        if not choices:
            raise RuntimeError("Groq returned no completion choices")
        message = getattr(choices[0], "message", None)
        content = getattr(message, "content", None)
        if not isinstance(content, str) or not content.strip():
            if request.get("reasoning_effort") != "low":
                request["reasoning_effort"] = "low"
                try:
                    completion = await self.client.chat.completions.create(**request)
                    message = getattr(completion.choices[0], "message", None)
                    content = getattr(message, "content", None)
                except Exception as error:
                    raise RuntimeError(f"Groq request failed: {error}") from error
            if not isinstance(content, str) or not content.strip():
                raise RuntimeError("Groq returned no usable final text")
        return SimpleNamespace(
            response=content,
            model=getattr(completion, "model", model),
            reasoning_details=getattr(message, "reasoning_details", None),
        )

    async def list(self) -> SimpleNamespace:
        try:
            response = await self.client.models.list()
        except Exception as error:
            raise RuntimeError(f"Groq model check failed: {error}") from error
        return SimpleNamespace(
            models=[SimpleNamespace(model=item.id) for item in response.data]
        )


def get_llm_client() -> AsyncClient | OpenRouterClient | GroqClient:
    provider = provider_name()
    if provider == "ollama":
        return AsyncClient(host=os.getenv("OLLAMA_HOST", "http://localhost:11434"))
    if provider == "openrouter":
        return OpenRouterClient()
    if provider == "groq":
        return GroqClient()
    raise RuntimeError(f"Unsupported LLM_PROVIDER: {provider}")