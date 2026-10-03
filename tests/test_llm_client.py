import json
import os
import unittest
from unittest.mock import patch

import httpx

from app.llm_client import GroqClient, OpenRouterClient
from app.model_router import model_for, provider_name


class OpenRouterClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_maps_options_and_returns_assistant_text(self):
        requests = []

        async def respond(request):
            requests.append(request)
            return httpx.Response(
                200,
                json={
                    "model": "nvidia/nemotron-3-ultra-550b-a55b:free",
                    "choices": [{"message": {"content": "generated text"}}],
                },
            )

        transport = httpx.MockTransport(respond)
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}):
            client = OpenRouterClient(transport=transport)
            result = await client.generate(
                model="nvidia/nemotron-3-ultra-550b-a55b:free",
                prompt="write a test",
                system="be concise",
                options={"temperature": 0.2, "num_predict": 256},
            )

        body = json.loads(requests[0].content)
        self.assertEqual(result.response, "generated text")
        self.assertEqual(body["messages"][0], {"role": "system", "content": "be concise"})
        self.assertEqual(body["messages"][1], {"role": "user", "content": "write a test"})
        self.assertEqual(body["max_tokens"], 256)
        self.assertEqual(body["temperature"], 0.2)
        self.assertEqual(body["reasoning"], {"enabled": True})
        self.assertEqual(requests[0].headers["Authorization"], "Bearer test-key")

    async def test_generate_maps_structured_output_options(self):
        requests = []

        async def respond(request):
            requests.append(json.loads(request.content))
            return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}):
            client = OpenRouterClient(transport=httpx.MockTransport(respond))
            await client.generate(
                model="model",
                prompt="return json",
                options={"response_format": {"type": "json_object"}},
            )

        self.assertEqual(requests[0]["response_format"], {"type": "json_object"})

    async def test_generate_requires_api_key(self):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}):
            client = OpenRouterClient(
                transport=httpx.MockTransport(
                    lambda request: httpx.Response(200, json={})
                )
            )
            with self.assertRaisesRegex(RuntimeError, "OPENROUTER_API_KEY"):
                await client.generate(model="model", prompt="hello")

    async def test_generate_surfaces_api_error_in_success_response(self):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}):
            client = OpenRouterClient(
                transport=httpx.MockTransport(
                    lambda request: httpx.Response(
                        200,
                        json={"error": {"message": "temporarily overloaded", "code": 502}},
                    )
                )
            )
            with self.assertRaisesRegex(RuntimeError, "temporarily overloaded.*code 502"):
                await client.generate(model="model", prompt="hello")

    async def test_generate_reports_missing_choices_with_response_id(self):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}):
            client = OpenRouterClient(
                transport=httpx.MockTransport(
                    lambda request: httpx.Response(200, json={"id": "req_123"})
                )
            )
            with self.assertRaisesRegex(RuntimeError, "no completion choices.*req_123"):
                await client.generate(model="model", prompt="hello")

    async def test_generate_retries_transient_upstream_overload(self):
        requests = []

        async def respond(request):
            requests.append(request)
            if len(requests) == 1:
                return httpx.Response(
                    200,
                    json={"error": {"message": "Service temporarily overloaded", "code": 503}},
                )
            return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}):
            client = OpenRouterClient(transport=httpx.MockTransport(respond))
            result = await client.generate(model="model", prompt="hello")

        self.assertEqual(result.response, "ok")
        self.assertEqual(len(requests), 2)

    async def test_generate_uses_qwen_fallback_after_primary_failure(self):
        requests = []

        async def respond(request):
            requests.append(json.loads(request.content))
            if len(requests) == 1:
                return httpx.Response(
                    400,
                    json={"error": {"message": "primary model unavailable"}},
                )
            return httpx.Response(200, json={"choices": [{"message": {"content": "qwen result"}}]})

        with patch.dict(
            os.environ,
            {
                "OPENROUTER_API_KEY": "test-key",
                "OPENROUTER_MAX_ATTEMPTS": "1",
            },
        ):
            client = OpenRouterClient(transport=httpx.MockTransport(respond))
            result = await client.generate(model="nvidia/primary", prompt="hello")

        self.assertEqual(result.response, "qwen result")
        self.assertEqual(requests[0]["model"], "nvidia/primary")
        self.assertEqual(requests[1]["model"], "qwen/qwen3.8-27b:free")

    async def test_generate_uses_configured_second_fallback_model(self):
        requests = []

        async def respond(request):
            requests.append(json.loads(request.content))
            if len(requests) == 1:
                return httpx.Response(400, json={"error": {"message": "unavailable"}})
            return httpx.Response(200, json={"choices": [{"message": {"content": "fallback result"}}]})

        with patch.dict(
            os.environ,
            {"OPENROUTER_API_KEY": "test-key", "OPENROUTER_MAX_ATTEMPTS": "1"},
        ):
            client = OpenRouterClient(transport=httpx.MockTransport(respond))
            result = await client.generate(model="nvidia/primary", prompt="hello")

        self.assertEqual(result.response, "fallback result")
        self.assertEqual(
            [request["model"] for request in requests],
            ["nvidia/primary", "qwen/qwen3.8-27b:free"],
        )

    async def test_list_rejects_invalid_api_key_before_listing_models(self):
        requests = []

        async def respond(request):
            requests.append(request)
            return httpx.Response(401, json={"error": {"message": "User not found"}})

        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "invalid-key"}):
            client = OpenRouterClient(transport=httpx.MockTransport(respond))
            with self.assertRaisesRegex(RuntimeError, "authentication check failed with HTTP 401"):
                await client.list()

        self.assertEqual([request.url.path for request in requests], ["/api/v1/key"])

    def test_provider_selects_requested_model(self):
        with patch.dict(
            os.environ,
            {
                "LLM_PROVIDER": "openrouter",
                "OPENROUTER_MODEL": "nvidia/nemotron-3-ultra-550b-a55b:free",
            },
        ):
            self.assertEqual(provider_name(), "openrouter")
            self.assertEqual(
                model_for("coding"),
                "nvidia/nemotron-3-ultra-550b-a55b:free",
            )


class GroqClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_maps_repo_options_to_groq_request(self):
        class Completions:
            async def create(self, **request):
                self.request = request
                return type(
                    "Completion",
                    (),
                    {
                        "model": request["model"],
                        "choices": [
                            type(
                                "Choice",
                                (),
                                {
                                    "message": type(
                                        "Message",
                                        (),
                                        {"content": "generated text"},
                                    )()
                                },
                            )()
                        ],
                    },
                )()

        completions = Completions()
        fake_client = type(
            "Client",
            (),
            {"chat": type("Chat", (), {"completions": completions})()},
        )()
        client = GroqClient(client=fake_client)

        result = await client.generate(
            model="openai/gpt-oss-120b",
            prompt="write a test",
            system="be concise",
            options={"temperature": 0.2, "num_predict": 256},
        )

        self.assertEqual(result.response, "generated text")
        self.assertEqual(completions.request["max_completion_tokens"], 256)
        self.assertEqual(completions.request["reasoning_effort"], "medium")
        self.assertEqual(
            completions.request["messages"],
            [
                {"role": "system", "content": "be concise"},
                {"role": "user", "content": "write a test"},
            ],
        )

    def test_provider_selects_groq_model(self):
        with patch.dict(
            os.environ,
            {"LLM_PROVIDER": "groq", "GROQ_MODEL": "openai/gpt-oss-120b"},
        ):
            self.assertEqual(provider_name(), "groq")
            self.assertEqual(model_for("coding"), "openai/gpt-oss-120b")

    async def test_generate_reduces_completion_after_tpm_rejection(self):
        class TpmError(Exception):
            status_code = 413

            def __str__(self):
                return "tokens per minute limit exceeded"

        class Completions:
            def __init__(self):
                self.requests = []

            async def create(self, **request):
                self.requests.append(request)
                if len(self.requests) == 1:
                    raise TpmError()
                return type(
                    "Completion",
                    (),
                    {
                        "model": request["model"],
                        "choices": [
                            type(
                                "Choice",
                                (),
                                {"message": type("Message", (), {"content": "ok"})()},
                            )()
                        ],
                    },
                )()

        completions = Completions()
        fake_client = type(
            "Client",
            (),
            {"chat": type("Chat", (), {"completions": completions})()},
        )()
        client = GroqClient(client=fake_client)

        result = await client.generate(
            model="openai/gpt-oss-120b",
            prompt="hello",
            options={"num_predict": 2048},
        )

        self.assertEqual(result.response, "ok")
        self.assertEqual(completions.requests[1]["max_completion_tokens"], 1024)
        self.assertEqual(completions.requests[1]["reasoning_effort"], "low")


if __name__ == "__main__":
    unittest.main()