"""Optional agent output critic."""

from __future__ import annotations

from t212ai.genai.tracing import (
    _trace_agent_critique_outputs,
    _trace_agent_review_inputs,
    set_trace_metadata,
    set_trace_name,
    traceable,
)

from .planner import TaskComplexity
from .reasoning import AgentReasoner
from .schemas import AgentCritique, AgentRequest, AgentResponse


class AgentJudge:
    def __init__(self, reasoner: AgentReasoner) -> None:
        self.reasoner = reasoner
        self.name = "agent_judge"

    @traceable(
        name="Agent Judge Review",
        run_type="chain",
        process_inputs=_trace_agent_review_inputs,
        process_outputs=_trace_agent_critique_outputs,
    )
    def review(
        self,
        *,
        request: AgentRequest,
        response: AgentResponse,
        guidelines: str | None = None,
    ) -> AgentCritique:
        set_trace_name(f"{self.__class__.__name__}.review")
        set_trace_metadata(
            agent_name=self.name,
            reviewed_agent=response.selected_agent,
            task_complexity=TaskComplexity.CRITICAL.value,
        )
        return self.reasoner.critique(
            agent_name=response.selected_agent,
            purpose="Review specialist-agent output for completeness and safety.",
            guidelines=guidelines or self._default_guidelines(),
            user_request=request.user_message,
            agent_output=response.final_answer,
            plan=response.plan,
            chat_history=request.history,
            task_complexity=TaskComplexity.CRITICAL,
        )

    def _default_guidelines(self) -> str:
        return (
            "Flag missing context, unsafe assumptions, insufficient broker-state "
            "grounding, unclear approval requirements, and weak source provenance."
        )
