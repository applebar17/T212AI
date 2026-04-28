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

        Return only the structured AgentPlan schema. Do not include hidden reasoning.
        Use explicit assumptions, required_context, tool_steps, risks, and
        missing_inputs to make the plan auditable.

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
) -> str:
    return dedent(
        f"""\
        Create a structured action plan.
        Intent: {intent_payload}
        User request: {user_request}
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

        Return only the structured AgentCritique schema. Check whether the answer is complete,
        safe, grounded in available context, and clear. Do not expose hidden reasoning; use
        concise findings.

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
