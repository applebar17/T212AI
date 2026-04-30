"""Action planning primitives for bounded tool use."""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .intents import AgentIntent, IntentKind, StructuredAgentIntent


class TaskComplexity(StrEnum):
    EASY = "easy"
    COMPLEX = "complex"
    CRITICAL = "critical"
    REASONING = "reasoning"


class PlanExecutionMode(StrEnum):
    PARALLEL = "parallel"
    SEQUENTIAL = "sequential"


class ActionStep(BaseModel):
    tool_name: str
    purpose: str
    depends_on: list[str] = Field(default_factory=list)


class ActionPlan(BaseModel):
    intent: AgentIntent
    steps: list[ActionStep] = Field(default_factory=list)
    requires_approval: bool = False


class ToolStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str
    purpose: str
    input_summary: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    can_run_parallel: bool = False
    risk_class: str = "read_only"


class AgentPlan(BaseModel):
    intent: AgentIntent
    summary: str
    required_context: list[str] = Field(default_factory=list)
    tool_steps: list[ToolStep] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    missing_inputs: list[str] = Field(default_factory=list)
    requires_approval: bool = False
    task_complexity: TaskComplexity = TaskComplexity.EASY


class StructuredAgentPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: StructuredAgentIntent
    summary: str
    required_context: list[str] = Field(default_factory=list)
    tool_steps: list[ToolStep] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    missing_inputs: list[str] = Field(default_factory=list)
    requires_approval: bool = False
    task_complexity: TaskComplexity = TaskComplexity.EASY

    def to_agent_plan(self) -> AgentPlan:
        return AgentPlan(
            intent=self.intent.to_agent_intent(),
            summary=self.summary,
            required_context=list(self.required_context),
            tool_steps=list(self.tool_steps),
            assumptions=list(self.assumptions),
            risks=list(self.risks),
            missing_inputs=list(self.missing_inputs),
            requires_approval=self.requires_approval,
            task_complexity=self.task_complexity,
        )


class PlanAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: str
    tool_name: str | None = None
    purpose: str
    input_summary: str | None = None
    expected_output: str
    depends_on: list[str] = Field(default_factory=list)
    output_key: str | None = None
    risk_class: str = "read_only"
    retry_policy: str | None = None
    stop_policy: str | None = None


class PlanActionGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_id: str
    title: str
    execution_mode: PlanExecutionMode = PlanExecutionMode.SEQUENTIAL
    actions: list[PlanAction] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_parallel_group(self) -> Self:
        action_ids = {action.action_id for action in self.actions}
        if len(action_ids) != len(self.actions):
            raise ValueError("duplicate_action_id_in_group")
        if self.execution_mode == PlanExecutionMode.PARALLEL:
            for action in self.actions:
                if action_ids.intersection(action.depends_on):
                    raise ValueError("parallel_group_actions_must_be_independent")
                if _is_state_changing_broker_action(action):
                    raise ValueError("state_changing_broker_actions_must_be_sequential")
        return self


class GroupedAgentPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: StructuredAgentIntent = Field(
        default_factory=lambda: StructuredAgentIntent(kind=IntentKind.UNKNOWN)
    )
    summary: str
    required_context: list[str] = Field(default_factory=list)
    action_groups: list[PlanActionGroup] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    missing_inputs: list[str] = Field(default_factory=list)
    requires_approval: bool = False
    expected_final_output: str
    task_complexity: TaskComplexity = TaskComplexity.EASY

    @model_validator(mode="after")
    def validate_action_graph(self) -> Self:
        group_ids: set[str] = set()
        seen_actions: set[str] = set()
        for group in self.action_groups:
            if group.group_id in group_ids:
                raise ValueError("duplicate_action_group_id")
            group_ids.add(group.group_id)
            for action in group.actions:
                if action.action_id in seen_actions:
                    raise ValueError("duplicate_action_id")
                for dependency in action.depends_on:
                    if dependency not in seen_actions:
                        raise ValueError("unknown_or_forward_action_dependency")
                seen_actions.add(action.action_id)
        return self

    def to_agent_plan(self) -> AgentPlan:
        tool_steps: list[ToolStep] = []
        for group in self.action_groups:
            for action in group.actions:
                tool_steps.append(
                    ToolStep(
                        tool_name=action.tool_name or "manual_step",
                        purpose=action.purpose,
                        input_summary=action.input_summary,
                        depends_on=list(action.depends_on),
                        can_run_parallel=group.execution_mode
                        == PlanExecutionMode.PARALLEL,
                        risk_class=action.risk_class,
                    )
                )
        return AgentPlan(
            intent=self.intent.to_agent_intent(),
            summary=self.summary,
            required_context=list(self.required_context),
            tool_steps=tool_steps,
            assumptions=list(self.assumptions),
            risks=list(self.risks),
            missing_inputs=list(self.missing_inputs),
            requires_approval=self.requires_approval,
            task_complexity=self.task_complexity,
        )


def _is_state_changing_broker_action(action: PlanAction) -> bool:
    risk_class = str(action.risk_class or "").strip().lower().replace("-", "_")
    if risk_class in {
        "state_changing",
        "side_effect",
        "broker_execution",
        "execution",
        "write",
    }:
        return True
    tool_name = str(action.tool_name or "").strip().lower()
    return tool_name in {
        "broker_prepare_order",
        "broker_prepare_order_action",
        "broker_prepare_cancel_action",
        "broker_place_order",
        "broker_cancel_order",
    }
