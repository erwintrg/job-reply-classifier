"""Classifier on the Anthropic Messages API (Claude Haiku by default).

The response is constrained with structured outputs (a JSON schema with an enum for `kind`) and
then validated again by `parse_output`, so a schema change or a refusal never reaches a sink.
"""
from __future__ import annotations

from typing import Any

from ..models import Classification, Envelope
from .base import OUTPUT_SCHEMA, SYSTEM_PROMPT, ClassificationError, ConfigError, build_user_prompt, parse_output

DEFAULT_MODEL = "claude-haiku-4-5"


class AnthropicClassifier:
    name = "anthropic"

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        api_key: str | None = None,
        client: Any = None,
        max_tokens: int = 512,
        timeout: float = 60.0,
    ) -> None:
        self.model = model
        self.max_tokens = max_tokens
        if client is None:
            try:
                import anthropic
            except ImportError as exc:
                raise ConfigError('the anthropic classifier needs the SDK: pip install -e ".[anthropic]"') from exc
            # api_key=None lets the SDK read ANTHROPIC_API_KEY from the environment.
            client = anthropic.Anthropic(api_key=api_key or None, timeout=timeout, max_retries=2)
        self._client = client

    def classify(self, envelope: Envelope, body: str) -> Classification:
        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": build_user_prompt(envelope, body)}],
                output_config={"format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
            )
        except Exception as exc:
            raise _translate(exc) from exc
        if response.stop_reason in ("refusal", "max_tokens"):
            raise ClassificationError(f"model stopped early ({response.stop_reason})")
        text = "".join(block.text for block in response.content if getattr(block, "type", "") == "text")
        return parse_output(text)


def _translate(exc: Exception) -> Exception:
    """Setup problems stop the cycle; everything else is retried on the next cycle.

    Without this split a revoked key would burn through the retry budget of every
    candidate mail and log them all as unclassified.
    """
    try:
        import anthropic
    except ImportError:  # a fake client in tests, nothing to translate
        return ClassificationError(f"{type(exc).__name__}: {exc}")
    if isinstance(exc, (anthropic.AuthenticationError, anthropic.PermissionDeniedError, anthropic.NotFoundError)):
        return ConfigError(f"Anthropic API rejected the setup ({type(exc).__name__}); check ANTHROPIC_API_KEY and ANTHROPIC_MODEL")
    if isinstance(exc, anthropic.RateLimitError):
        return ClassificationError("rate limited by the Anthropic API")
    if isinstance(exc, anthropic.APIStatusError):
        return ClassificationError(f"Anthropic API error {exc.status_code}")
    if isinstance(exc, anthropic.APIConnectionError):
        return ClassificationError("could not reach the Anthropic API")
    return ClassificationError(f"{type(exc).__name__}: {exc}")
