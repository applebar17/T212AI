"""Dedicated agent for persistent guideline memory management."""

from __future__ import annotations

from t212ai.genai.models import ToolResult
from t212ai.genai.tracing import (
    _trace_agent_handle_inputs,
    _trace_agent_response_outputs,
    set_trace_metadata,
    set_trace_name,
    traceable,
)
from t212ai.guidelines import (
    GUIDELINE_MEMORY_TOOLBOX,
    GuidelineMemoryService,
    GuidelineMutationAction,
    GuidelineMutationRequest,
    GuidelineToolRuntime,
    build_guideline_tool_mapping,
)

from .base import AgentProfile, BaseAgent
from .intents import AgentIntent, IntentKind
from .planner import AgentPlan, TaskComplexity
from .schemas import AgentRequest, AgentResponse


class GuidelineMemoryAgent(BaseAgent):
    def __init__(self, reasoner, guideline_service: GuidelineMemoryService) -> None:
        super().__init__(
            reasoner,
            AgentProfile(
                name="guideline_memory_agent",
                purpose="Manage persistent guideline and preference memory.",
                guidelines=(
                    "Only modify stored guidelines when the user explicitly asked to "
                    "remember, update, archive, delete, or list them. Prefer archive "
                    "over delete unless the user explicitly asked for permanent deletion."
                ),
                toolbox_summary=(
                    "Guideline CRUD tools: list, render preview, create, update, archive, "
                    "and explicit delete."
                ),
                task_complexity=TaskComplexity.EASY,
                guideline_scopes=("global", "orchestrator"),
                guideline_include_categories=("investment_preference",),
                toolbox=GUIDELINE_MEMORY_TOOLBOX,
            ),
            guideline_service=guideline_service,
        )
        self._runtime = GuidelineToolRuntime(service=guideline_service)
        self._tool_mapping = build_guideline_tool_mapping(self._runtime)

    @traceable(
        name="Guideline Memory Agent Handle",
        run_type="chain",
        process_inputs=_trace_agent_handle_inputs,
        process_outputs=_trace_agent_response_outputs,
    )
    def handle(
        self,
        request: AgentRequest,
        *,
        intent: AgentIntent | None = None,
        task_complexity: TaskComplexity | None = None,
    ) -> AgentResponse:
        resolved_intent = intent or AgentIntent(kind=IntentKind.MANAGE_GUIDELINES)
        complexity = task_complexity or TaskComplexity.EASY
        set_trace_name(f"{self.__class__.__name__}.handle")
        set_trace_metadata(
            agent_name=self.name,
            agent_kind="specialist",
            intent_kind=resolved_intent.kind.value,
            task_complexity=complexity.value,
        )
        plan = self.plan(
            request,
            intent=resolved_intent,
            task_complexity=complexity,
        )
        mutation_request = self._build_mutation_request(request, intent=resolved_intent)
        result = self._execute_mutation_request(mutation_request)
        return AgentResponse(
            final_answer=_final_answer_for_result(mutation_request, result),
            selected_agent=self.name,
            plan=plan,
            metadata={
                "agent": self.name,
                "task_complexity": complexity.value,
                "action": mutation_request.action.value,
                "status": result.status,
            },
        )

    def _build_mutation_request(
        self,
        request: AgentRequest,
        *,
        intent: AgentIntent,
    ) -> GuidelineMutationRequest:
        operation = intent.entities.get("operation")
        system_prompt = (
            "You convert explicit user guideline-memory requests into a structured "
            "GuidelineMutationRequest.\n\n"
            "Rules:\n"
            "- Only choose create, update, archive, delete, list, or render.\n"
            "- Use delete only when the user explicitly asked for permanent deletion.\n"
            "- Use archive for forget/remove requests unless permanent delete was explicit.\n"
            "- For create/update, include category, title, body, applies_to, and priority "
            "when the user intent makes them clear.\n"
            "- Use source='user' for requests coming from the user.\n"
            "- If the user is asking to inspect current stored rules, choose list or render.\n"
            "- Do not invent missing node ids; if the user refers to a specific stored rule "
            "but the id is unknown, leave node_id null so the tools can fail loudly."
        )
        messages = []
        if request.history:
            messages.extend(request.history.to_llm_messages())
        messages.append(
            {
                "role": "user",
                "content": (
                    f"Intent operation hint: {operation or 'unknown'}\n"
                    f"User request: {request.user_message}"
                ),
            }
        )
        result = self.reasoner.genai.generate_structured(
            GuidelineMutationRequest,
            system_prompt,
            messages,
            model=self.reasoner.genai.chat_model_for("default"),
            temperature=0.0,
        )
        return GuidelineMutationRequest.model_validate(result)

    def _execute_mutation_request(
        self,
        request: GuidelineMutationRequest,
    ) -> ToolResult:
        if request.action == GuidelineMutationAction.CREATE:
            return self._tool_mapping["guideline_create_node"](
                category=request.category.value if request.category else None,
                title=request.title,
                body=request.body,
                priority=request.priority or 0,
                tags=request.tags or [],
                applies_to=request.applies_to or [],
                source=request.source,
            )
        if request.action == GuidelineMutationAction.UPDATE:
            return self._tool_mapping["guideline_update_node"](
                node_id=request.node_id,
                category=request.category.value if request.category else None,
                title=request.title,
                body=request.body,
                priority=request.priority,
                tags=request.tags,
                applies_to=request.applies_to,
                source=request.source,
            )
        if request.action == GuidelineMutationAction.ARCHIVE:
            return self._tool_mapping["guideline_archive_node"](
                node_id=request.node_id,
                source=request.source or "agent",
            )
        if request.action == GuidelineMutationAction.DELETE:
            return self._tool_mapping["guideline_delete_node"](
                node_id=request.node_id,
                confirmed=bool(request.confirmed),
            )
        if request.action == GuidelineMutationAction.RENDER:
            return self._tool_mapping["guideline_render_preview"](
                scopes=request.scopes or None,
                include_categories=_category_values(request.categories),
                active_only=bool(request.active_only),
            )
        return self._tool_mapping["guideline_list_nodes"](
            categories=_category_values(request.categories),
            scopes=request.scopes or None,
            active_only=bool(request.active_only),
        )


def _category_values(categories) -> list[str] | None:
    values = [category.value for category in categories or []]
    return values or None


def _fallback_message(result: ToolResult) -> str:
    if result.error is not None:
        return result.error.message
    return "Guideline memory request completed."


def _final_answer_for_result(
    mutation_request: GuidelineMutationRequest,
    result: ToolResult,
) -> str:
    if (
        mutation_request.action == GuidelineMutationAction.RENDER
        and isinstance(result.data, dict)
        and isinstance(result.data.get("markdown"), str)
        and result.data["markdown"]
    ):
        return result.data["markdown"]
    return result.output or _fallback_message(result)
