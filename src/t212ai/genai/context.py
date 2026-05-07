"""Context-window resolution and chat message compaction helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
import re
from typing import Any, Callable, Mapping

from .tokenizer import TokenCounter


DEFAULT_CONTEXT_FALLBACK_TOKENS = 128_000
DEFAULT_CONTEXT_GUARD_RATIO = 0.95
DEFAULT_OUTPUT_RESERVE_TOKENS = 1_024
DEFAULT_CONTEXT_RECENT_MESSAGES = 12
DEFAULT_CONTEXT_SUMMARY_MAX_TOKENS = 1_024
MIN_CONFIGURABLE_CONTEXT_TOKENS = 64_000
PRIOR_CONTEXT_SUMMARY_HEADER = "Prior conversation/tool context summary:"

_DATE_SNAPSHOT_RE = re.compile(r"^(?P<base>.+)-\d{4}-\d{2}-\d{2}$")
_CONTEXT_LIMIT_PATTERNS = (
    re.compile(r"maximum context length is\s+([\d,]+)\s+tokens", re.IGNORECASE),
    re.compile(
        r"max(?:imum)? context(?: length)?(?: is|:)?\s+([\d,]+)",
        re.IGNORECASE,
    ),
    re.compile(r"context window(?: size)?(?: is|:)?\s+([\d,]+)", re.IGNORECASE),
)


COMMON_MODEL_CONTEXT_TOKENS: dict[str, int] = {
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-4.1": 1_047_576,
    "gpt-4.1-mini": 1_047_576,
    "gpt-4.1-nano": 1_047_576,
    "o3": 200_000,
    "o3-mini": 200_000,
    "o4-mini": 200_000,
    "gpt-5": 400_000,
    "gpt-5-mini": 400_000,
    "gpt-5-nano": 400_000,
    "gpt-5.1": 400_000,
    "gpt-5.2": 400_000,
    "gpt-5.4": 1_050_000,
    "gpt-5.5": 1_050_000,
    "gpt-5.5-pro": 1_050_000,
}


def normalize_model_name(model: str | None) -> str:
    return str(model or "").strip().lower()


def parse_context_token_value(
    value: Any,
    *,
    minimum: int = MIN_CONFIGURABLE_CONTEXT_TOKENS,
) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(str(value).strip().replace(",", ""))
    except (TypeError, ValueError):
        return None
    if parsed <= minimum:
        return None
    return parsed


def parse_context_tokens_by_model_json(raw: str | None) -> dict[str, int]:
    if not raw or not str(raw).strip():
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}

    parsed: dict[str, int] = {}
    for key, value in payload.items():
        model = normalize_model_name(str(key))
        tokens = parse_context_token_value(value)
        if model and tokens is not None:
            parsed[model] = tokens
    return parsed


def parse_context_limit_from_error(exc: Exception | str) -> int | None:
    message = str(exc)
    for pattern in _CONTEXT_LIMIT_PATTERNS:
        match = pattern.search(message)
        if not match:
            continue
        try:
            return int(match.group(1).replace(",", ""))
        except (TypeError, ValueError):
            continue
    return None


def is_context_length_error(exc: Exception | str) -> bool:
    message = str(exc).lower()
    markers = (
        "context_length_exceeded",
        "maximum context length",
        "max context length",
        "context window",
        "too many tokens",
    )
    return any(marker in message for marker in markers)


@dataclass(slots=True)
class ModelContextRegistry:
    model_context_tokens: Mapping[str, int] = field(
        default_factory=lambda: dict(COMMON_MODEL_CONTEXT_TOKENS)
    )

    def lookup(self, model: str | None) -> int | None:
        normalized = normalize_model_name(model)
        if not normalized:
            return None
        exact = self.model_context_tokens.get(normalized)
        if exact is not None:
            return int(exact)
        snapshot_match = _DATE_SNAPSHOT_RE.match(normalized)
        if not snapshot_match:
            return None
        return self.model_context_tokens.get(snapshot_match.group("base"))


@dataclass(slots=True)
class ContextBudgetResolver:
    tier_context_tokens: Mapping[str, int] = field(default_factory=dict)
    model_context_tokens: Mapping[str, int] = field(default_factory=dict)
    fallback_tokens: int = DEFAULT_CONTEXT_FALLBACK_TOKENS
    registry: ModelContextRegistry = field(default_factory=ModelContextRegistry)
    runtime_context_tokens: dict[str, int] = field(default_factory=dict)

    def resolve(self, model: str | None, *, tier: str | None = None) -> int:
        normalized_model = normalize_model_name(model)
        if normalized_model in self.runtime_context_tokens:
            return self.runtime_context_tokens[normalized_model]

        normalized_tier = str(tier or "").strip().lower()
        if normalized_tier and normalized_tier in self.tier_context_tokens:
            return int(self.tier_context_tokens[normalized_tier])

        if normalized_model in self.model_context_tokens:
            return int(self.model_context_tokens[normalized_model])

        registered = self.registry.lookup(normalized_model)
        if registered is not None:
            return registered
        return max(1, int(self.fallback_tokens or DEFAULT_CONTEXT_FALLBACK_TOKENS))

    def record_runtime_limit(self, model: str | None, tokens: int | None) -> None:
        normalized = normalize_model_name(model)
        if not normalized or tokens is None:
            return
        try:
            parsed = int(tokens)
        except (TypeError, ValueError):
            return
        if parsed <= 0:
            return
        existing = self.runtime_context_tokens.get(normalized)
        if existing is None or parsed < existing:
            self.runtime_context_tokens[normalized] = parsed


@dataclass(slots=True)
class ContextCompactionResult:
    changed: bool
    input_tokens: int
    budget_tokens: int
    context_limit_tokens: int
    summary_used: bool = False
    fallback_truncated: bool = False


SummaryCallback = Callable[[list[dict[str, Any]], str, int], str]


class GenAIContextManager:
    def __init__(
        self,
        *,
        resolver: ContextBudgetResolver | None = None,
        token_counter: TokenCounter | None = None,
        guard_ratio: float = DEFAULT_CONTEXT_GUARD_RATIO,
        output_reserve_tokens: int = DEFAULT_OUTPUT_RESERVE_TOKENS,
        recent_messages: int = DEFAULT_CONTEXT_RECENT_MESSAGES,
        summary_max_tokens: int = DEFAULT_CONTEXT_SUMMARY_MAX_TOKENS,
        logger: logging.Logger | None = None,
    ) -> None:
        self.resolver = resolver or ContextBudgetResolver()
        self.token_counter = token_counter or TokenCounter()
        self.guard_ratio = _safe_ratio(guard_ratio)
        self.output_reserve_tokens = max(0, int(output_reserve_tokens))
        self.recent_messages = max(1, int(recent_messages))
        self.summary_max_tokens = max(1, int(summary_max_tokens))
        self.logger = logger or logging.getLogger(__name__)

    def ensure_budget(
        self,
        params: dict[str, Any],
        *,
        tier: str | None = None,
        summarizer: SummaryCallback | None = None,
        force: bool = False,
    ) -> ContextCompactionResult:
        model = str(params.get("model") or "")
        messages = params.get("messages")
        if not model or not isinstance(messages, list) or not messages:
            return ContextCompactionResult(
                changed=False,
                input_tokens=0,
                budget_tokens=0,
                context_limit_tokens=self.resolver.resolve(model, tier=tier),
            )

        context_limit = self.resolver.resolve(model, tier=tier)
        output_reserve = self._resolve_output_reserve(params)
        guarded_limit = max(1, int(context_limit * self.guard_ratio))
        fixed_prompt_tokens = self._count_fixed_prompt_tokens(params, model)
        message_budget = max(1, guarded_limit - output_reserve - fixed_prompt_tokens)
        input_tokens = self.count_messages(messages, model) + fixed_prompt_tokens
        total_budget = max(1, guarded_limit - output_reserve)

        if not force and input_tokens <= total_budget:
            return ContextCompactionResult(
                changed=False,
                input_tokens=input_tokens,
                budget_tokens=total_budget,
                context_limit_tokens=context_limit,
            )

        compacted, summary_used, fallback_truncated = self.compact_messages(
            messages,
            model=model,
            budget_tokens=message_budget,
            summarizer=summarizer,
        )
        params["messages"] = compacted
        return ContextCompactionResult(
            changed=compacted != messages,
            input_tokens=input_tokens,
            budget_tokens=total_budget,
            context_limit_tokens=context_limit,
            summary_used=summary_used,
            fallback_truncated=fallback_truncated,
        )

    def compact_messages(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
        budget_tokens: int,
        summarizer: SummaryCallback | None = None,
    ) -> tuple[list[dict[str, Any]], bool, bool]:
        if not messages:
            return messages, False, False

        system_message, first_content_index = self._split_system_message(messages)
        recent_start = self._recent_start(messages, first_content_index)
        older_messages = messages[first_content_index:recent_start]
        recent_messages = messages[recent_start:]

        if older_messages and summarizer is not None:
            try:
                summary = summarizer(older_messages, model, self.summary_max_tokens)
            except Exception as exc:  # pragma: no cover - fallback path
                self.logger.warning(
                    "Context summarization failed; falling back to truncation: %s",
                    exc,
                )
                summary = ""
            if str(summary or "").strip():
                candidate = self._assemble_with_summary(
                    system_message,
                    str(summary).strip(),
                    recent_messages,
                )
                if self.count_messages(candidate, model) <= budget_tokens:
                    return candidate, True, False
                truncated_candidate = self.truncate_messages(
                    candidate,
                    model=model,
                    budget_tokens=budget_tokens,
                )
                if self.count_messages(truncated_candidate, model) <= budget_tokens:
                    return truncated_candidate, True, True

        return (
            self.truncate_messages(
                messages,
                model=model,
                budget_tokens=budget_tokens,
            ),
            False,
            True,
        )

    def truncate_messages(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
        budget_tokens: int,
    ) -> list[dict[str, Any]]:
        if not messages:
            return messages

        system_message, first_content_index = self._split_system_message(messages)
        start = self._recent_start(messages, first_content_index)
        while start < len(messages):
            candidate = self._assemble(system_message, messages[start:])
            if self.count_messages(candidate, model) <= budget_tokens:
                return candidate
            start += 1
            while start < len(messages) and _message_role(messages[start]) == "tool":
                start += 1
        if system_message is not None:
            return [system_message]
        return [messages[-1]]

    def count_messages(self, messages: list[dict[str, Any]], model: str) -> int:
        return self.token_counter.count_messages(messages, model=model)

    def render_messages_for_summary(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
        max_tokens: int,
    ) -> str:
        selected: list[str] = []
        total = 0
        for message in reversed(messages):
            rendered = self._render_message_for_summary(message)
            tokens = self.token_counter.count_text(rendered, model=model)
            if selected and total + tokens > max_tokens:
                break
            selected.insert(0, rendered)
            total += tokens
        return "\n\n".join(selected)

    def _resolve_output_reserve(self, params: Mapping[str, Any]) -> int:
        for key in ("max_completion_tokens", "max_tokens"):
            value = params.get(key)
            if value is None:
                continue
            try:
                return max(0, int(value))
            except (TypeError, ValueError):
                continue
        return self.output_reserve_tokens

    def _count_fixed_prompt_tokens(self, params: Mapping[str, Any], model: str) -> int:
        total = 0
        for key in ("tools", "tool_choice", "response_format"):
            if key not in params:
                continue
            total += self.token_counter.count_content(params.get(key), model=model)
        return total

    def _split_system_message(
        self,
        messages: list[dict[str, Any]],
    ) -> tuple[dict[str, Any] | None, int]:
        first = messages[0] if messages else None
        if isinstance(first, dict) and first.get("role") == "system":
            return first, 1
        return None, 0

    def _recent_start(
        self,
        messages: list[dict[str, Any]],
        first_content_index: int,
    ) -> int:
        start = max(first_content_index, len(messages) - self.recent_messages)
        while start > first_content_index and _message_role(messages[start]) == "tool":
            start -= 1
        return start

    def _assemble(
        self,
        system_message: dict[str, Any] | None,
        content_messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if system_message is None:
            return list(content_messages)
        return [system_message, *content_messages]

    def _assemble_with_summary(
        self,
        system_message: dict[str, Any] | None,
        summary: str,
        recent_messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        summary_message = {
            "role": "user",
            "content": f"{PRIOR_CONTEXT_SUMMARY_HEADER}\n{summary}",
        }
        return self._assemble(system_message, [summary_message, *recent_messages])

    def _render_message_for_summary(self, message: dict[str, Any]) -> str:
        role = _message_role(message) or "unknown"
        content = message.get("content") if isinstance(message, dict) else None
        if content in {None, ""}:
            content = {
                key: value
                for key, value in message.items()
                if key != "role" and value is not None and value != ""
            }
        if not isinstance(content, str):
            try:
                content = json.dumps(content, separators=(",", ":"))
            except Exception:
                content = str(content)
        return f"{role}: {content}"


def _message_role(message: dict[str, Any] | Any) -> str:
    if isinstance(message, dict):
        return str(message.get("role") or "")
    return str(getattr(message, "role", "") or "")


def _safe_ratio(value: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return DEFAULT_CONTEXT_GUARD_RATIO
    if parsed <= 0:
        return DEFAULT_CONTEXT_GUARD_RATIO
    return min(parsed, 1.0)
