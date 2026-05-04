"""Prompt builders for plan and critique generation."""

from __future__ import annotations

from textwrap import dedent
from typing import Any


def build_plan_system_prompt(
    *,
    agent_name: str,
    purpose: str,
    guidelines: str,
    toolbox_summary: str,
    persistent_guidance: str | None,
) -> str:
    prompt = dedent(
        f"""\
        You are {agent_name}.
        Purpose: {purpose}

        Return the structured AgentPlan schema with concise, auditable planning
        notes. Use explicit assumptions, required_context, tool_steps, risks, and
        missing_inputs.
        Treat this as the plan step of a configurable agent loop:
        reason -> plan -> execute -> judge -> return. The reason and plan steps
        run without attached tools. The execute step will receive the agent's narrow
        toolbox later and should follow this plan action by action. Mark a tool
        step as can_run_parallel only when it has no dependency on another step's
        output. State-changing work must be represented as preparation plus
        button approval; typed chat text is ordinary conversation, not approval.

        Available capability/toolbox summary:
        {toolbox_summary}

        Agent-specific guidelines:
        {guidelines}
        """
    ).strip()
    if persistent_guidance:
        prompt = f"{prompt}\n\nPersistent guidance memory:\n{persistent_guidance}"
    return prompt


def build_plan_user_prompt(
    *,
    user_request: str,
    intent_payload: dict[str, Any],
    orchestrator_guidance: str | None = None,
) -> str:
    prompt = dedent(
        f"""\
        Create a structured action plan.
        Intent: {intent_payload}
        User request: {user_request}
        """
    ).strip()
    if orchestrator_guidance:
        prompt = f"{prompt}\nOrchestrator guidance: {orchestrator_guidance}"
    return prompt


def build_reasoning_context_system_prompt(
    *,
    agent_name: str,
    purpose: str,
    guidelines: str,
    toolbox_summary: str,
    tool_descriptions: str | None = None,
    flow_guidelines: list[str] | None = None,
    examples: list[str] | None = None,
    persistent_guidance: str | None,
) -> str:
    prompt = dedent(
        f"""\
        You are {agent_name}.
        Purpose: {purpose}

        Return the structured AgentReasoningContext schema with concise,
        auditable task context that a later planner can consume.

        This is the reason step of a configurable agent loop:
        reason -> plan -> execute -> judge -> return.
        No tools are attached in this step. Use the user request, chat history,
        invocation reason, intent hint, persistent guidance, and toolbox
        descriptions as planning context.

        Available capability/toolbox summary:
        {toolbox_summary}

        Available high-level tool descriptions:
        {tool_descriptions or "No high-level tool descriptions provided."}

        Agent-specific guidelines:
        {guidelines}
        """
    ).strip()
    if flow_guidelines:
        prompt = f"{prompt}\n\nReasoning-step guidelines:\n{_render_list(flow_guidelines)}"
    if examples:
        prompt = f"{prompt}\n\nReasoning examples:\n{_render_examples(examples)}"
    if persistent_guidance:
        prompt = f"{prompt}\n\nPersistent guidance memory:\n{persistent_guidance}"
    return prompt


def build_reasoning_context_user_prompt(
    *,
    user_request: str,
    invocation_reason: str,
    intent_payload: dict[str, Any],
) -> str:
    return dedent(
        f"""\
        Build structured reasoning context.
        Invocation reason: {invocation_reason}
        Intent hint: {intent_payload}
        User request: {user_request}
        """
    ).strip()


def build_grouped_plan_system_prompt(
    *,
    agent_name: str,
    purpose: str,
    guidelines: str,
    toolbox_summary: str,
    tool_descriptions: str | None = None,
    flow_guidelines: list[str] | None = None,
    examples: list[str] | None = None,
    persistent_guidance: str | None,
) -> str:
    prompt = dedent(
        f"""\
        You are {agent_name}.
        Purpose: {purpose}

        Return the structured GroupedAgentPlan schema. Turn the reasoning context
        into an executable grouped plan with concise, auditable notes.

        Execution semantics:
        - action groups run sequentially in listed order
        - actions inside a sequential group run in listed order
        - actions inside a parallel group must be independent and may run together
        - dependent actions must declare depends_on action IDs
        - every action needs a stable action_id and expected_output
        - use output_key when later actions should consume an action result
        - state-changing broker work must be sequential and must prepare a side
          effect for deterministic approval; typed chat text is ordinary
          conversation, not approval

        No tools are attached in this step. Use toolbox descriptions to choose
        likely action/tool names.

        Available capability/toolbox summary:
        {toolbox_summary}

        Available high-level tool descriptions:
        {tool_descriptions or "No high-level tool descriptions provided."}

        Agent-specific guidelines:
        {guidelines}
        """
    ).strip()
    if flow_guidelines:
        prompt = f"{prompt}\n\nPlanning-step guidelines:\n{_render_list(flow_guidelines)}"
    if examples:
        prompt = f"{prompt}\n\nPlanning examples:\n{_render_examples(examples)}"
    if persistent_guidance:
        prompt = f"{prompt}\n\nPersistent guidance memory:\n{persistent_guidance}"
    return prompt


def build_grouped_plan_user_prompt(
    *,
    user_request: str,
    invocation_reason: str,
    intent_payload: dict[str, Any],
    reasoning_context_payload: dict[str, Any],
) -> str:
    return dedent(
        f"""\
        Build a grouped execution plan.
        Invocation reason: {invocation_reason}
        Intent hint: {intent_payload}
        User request: {user_request}
        Reasoning context: {reasoning_context_payload}
        """
    ).strip()


def build_plan_action_system_prompt(
    *,
    agent_name: str,
    purpose: str,
    guidelines: str,
    toolbox_summary: str,
    persistent_guidance: str | None,
) -> str:
    prompt = dedent(
        f"""\
        You are {agent_name}.
        Purpose: {purpose}

        Execute exactly one planned action. Use tools only when they are needed
        for this action and are available in the attached toolbox. Return a
        compact assistant message that captures the essential result, source
        caveats, and any failure. Summarize tool output instead of pasting raw
        tool JSON.

        If a tool returns status=error, read its output, code, hint, and
        structured details before deciding whether to retry, stop, or ask for
        clarification. For broker order preparation failures, explicitly state
        whether an order was prepared, whether approval was created, and what
        corrected broker-native input is needed.

        This action result will become high-level context for later actions, so
        keep it self-contained and coherent.

        Available capability/toolbox summary:
        {toolbox_summary}

        Agent-specific guidelines:
        {guidelines}
        """
    ).strip()
    if persistent_guidance:
        prompt = f"{prompt}\n\nPersistent guidance memory:\n{persistent_guidance}"
    return prompt


def _render_list(items: list[str]) -> str:
    return "\n".join(f"- {str(item).strip()}" for item in items if str(item).strip())


def _render_examples(items: list[str]) -> str:
    return "\n\n".join(str(item).strip() for item in items if str(item).strip())


def build_plan_action_user_prompt(
    *,
    user_request: str,
    reasoning_context_payload: dict[str, Any],
    group_payload: dict[str, Any],
    action_payload: dict[str, Any],
    dependency_summaries: list[str],
) -> str:
    return dedent(
        f"""\
        Execute the next planned action.
        Original user request: {user_request}
        Reasoning context: {reasoning_context_payload}
        Current group: {group_payload}
        Current action: {action_payload}
        Dependency summaries: {dependency_summaries}

        Return only the essential action result as a concise assistant message.
        """
    ).strip()


def build_final_synthesis_system_prompt(
    *,
    agent_name: str,
    purpose: str,
    guidelines: str,
    persistent_guidance: str | None,
) -> str:
    prompt = dedent(
        f"""\
        You are {agent_name}.
        Purpose: {purpose}

        Produce the final response for the orchestrator and user from completed
        planning-execution summaries. This step is synthesis-only. Keep the
        answer concise, grounded, and explicit about missing or failed context.

        Agent-specific guidelines:
        {guidelines}
        """
    ).strip()
    if persistent_guidance:
        prompt = f"{prompt}\n\nPersistent guidance memory:\n{persistent_guidance}"
    return prompt


def build_final_synthesis_user_prompt(
    *,
    user_request: str,
    reasoning_context_payload: dict[str, Any],
    grouped_plan_payload: dict[str, Any],
    action_summaries: list[str],
) -> str:
    return dedent(
        f"""\
        Build the final answer.
        Original user request: {user_request}
        Reasoning context: {reasoning_context_payload}
        Grouped plan: {grouped_plan_payload}
        Completed action summaries: {action_summaries}
        """
    ).strip()


def build_critique_system_prompt(
    *,
    agent_name: str,
    purpose: str,
    guidelines: str,
    persistent_guidance: str | None,
) -> str:
    prompt = dedent(
        f"""\
        You are judging work from {agent_name}.
        Agent purpose: {purpose}

        Return the structured AgentCritique schema. Check whether the answer is
        complete, safe, grounded in available context, and clear. Use concise,
        auditable findings.

        Judge guidelines:
        {guidelines}
        """
    ).strip()
    if persistent_guidance:
        prompt = f"{prompt}\n\nPersistent guidance memory:\n{persistent_guidance}"
    return prompt


def build_critique_user_prompt(
    *,
    user_request: str,
    agent_output: str,
    plan_payload: dict[str, Any] | None,
) -> str:
    payload = {
        "user_request": user_request,
        "agent_output": agent_output,
        "plan": plan_payload,
    }
    return dedent(
        f"""\
        Review this agent output package.
        Payload: {payload}
        """
    ).strip()
