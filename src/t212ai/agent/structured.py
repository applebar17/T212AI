"""Reusable structured synthesis for specialist agent outputs."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from t212ai.genai.tracing import set_trace_metadata, set_trace_name, traceable

from .planner import TaskComplexity
from .schemas import AgentResponse


class StructuredAgentOutputSynthesizer:
    """Convert an agent response and compact context into a typed output schema."""

    def __init__(self, genai_client: Any) -> None:
        self.genai = genai_client

    @traceable(name="agent.structured_output_synthesis", run_type="chain")
    def synthesize(
        self,
        schema: type[BaseModel],
        *,
        source_agent_name: str,
        source_response: AgentResponse,
        user_request: str,
        instructions: str,
        context: dict[str, Any] | None = None,
        task_complexity: TaskComplexity = TaskComplexity.COMPLEX,
    ) -> BaseModel:
        set_trace_name(f"{source_agent_name}.structured_synthesis")
        set_trace_metadata(
            agent_name=source_agent_name,
            agent_step="structured_synthesis",
            step_kind="parser",
            schema=schema.__name__,
            task_complexity=task_complexity.value,
        )
        result = self.genai.generate_structured(
            schema,
            _system_prompt(schema=schema, source_agent_name=source_agent_name),
            [
                {
                    "role": "user",
                    "content": _user_prompt(
                        user_request=user_request,
                        instructions=instructions,
                        source_response=source_response,
                        context=context or {},
                    ),
                }
            ],
            model=_model_for(self.genai, task_complexity),
            temperature=0.0,
        )
        return schema.model_validate(result)


def _system_prompt(*, schema: type[BaseModel], source_agent_name: str) -> str:
    return (
        "You convert a specialist agent result into the requested structured schema. "
        "Use only the provided agent output and compact context. Preserve uncertainty, "
        "source limitations, and safety constraints. Do not add broker/order actions. "
        f"Source agent: {source_agent_name}. Output schema: {schema.__name__}."
    )


def _user_prompt(
    *,
    user_request: str,
    instructions: str,
    source_response: AgentResponse,
    context: dict[str, Any],
) -> str:
    payload = {
        "userRequest": user_request,
        "instructions": instructions,
        "sourceAgent": source_response.selected_agent,
        "sourceFinalAnswer": source_response.final_answer,
        "sourceMetadata": source_response.metadata,
        "sourceArtifacts": _compact(source_response.artifacts),
        "context": _compact(context),
    }
    return json.dumps(payload, default=str, ensure_ascii=False)


def _compact(value: Any, *, max_chars: int = 12_000) -> Any:
    rendered = json.dumps(value, default=str, ensure_ascii=False)
    if len(rendered) <= max_chars:
        try:
            return json.loads(rendered)
        except json.JSONDecodeError:
            return rendered
    return {"truncated": True, "preview": rendered[:max_chars]}


def _model_for(genai: Any, task_complexity: TaskComplexity) -> str | None:
    if not hasattr(genai, "chat_model_for"):
        return None
    if task_complexity == TaskComplexity.REASONING:
        return genai.chat_model_for("reasoning")
    if task_complexity in {TaskComplexity.COMPLEX, TaskComplexity.CRITICAL}:
        return genai.chat_model_for("smart")
    return genai.chat_model_for("default")
