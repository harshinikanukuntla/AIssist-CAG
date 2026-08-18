"""
Thin, provider-agnostic wrapper around an OpenAI-compatible chat
completions endpoint.

Defaults to NVIDIA NIM's hosted API catalog, but nothing here is
NIM-specific — swapping to a self-hosted NIM container (to unlock real
KV-cache prefix reuse via NIM_ENABLE_KV_CACHE_REUSE on the server side)
or to another OpenAI-compatible provider entirely is a config change
(llm_base_url / llm_api_key / llm_model), not a code change.
"""

from openai import APITimeoutError, AsyncOpenAI, OpenAIError

from app.config import Settings


class LLMUnavailableError(RuntimeError):
    """Raised when the upstream LLM call fails or times out, so callers
    can return a graceful message instead of a raw 500."""


class LLMClient:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._client = AsyncOpenAI(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            timeout=settings.llm_timeout_seconds,
        )

    async def complete(self, messages: list[dict[str, str]]) -> str:
        try:
            response = await self._client.chat.completions.create(
                model=self._settings.llm_model,
                messages=messages,
                max_tokens=self._settings.llm_max_output_tokens,
                temperature=self._settings.llm_temperature,
            )
        except APITimeoutError as exc:
            raise LLMUnavailableError("The assistant took too long to respond.") from exc
        except OpenAIError as exc:
            raise LLMUnavailableError("The assistant is temporarily unavailable.") from exc

        choice = response.choices[0]
        return (choice.message.content or "").strip()
