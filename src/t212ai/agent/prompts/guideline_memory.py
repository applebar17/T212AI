"""Prompt builders for guideline memory extraction."""

from __future__ import annotations

from textwrap import dedent

GUIDELINE_MUTATION_SYSTEM_PROMPT = dedent(
    """\
    You convert explicit user guideline-memory requests into a structured GuidelineMutationRequest.

    Rules:
    - Only choose create, update, archive, delete, list, or render.
    - Use delete only when the user explicitly asked for permanent deletion.
    - Use archive for forget/remove requests unless permanent delete was explicit.
    - For create/update, include category, title, body, applies_to, and priority when the user intent makes them clear.
    - Use source='user' for requests coming from the user.
    - If the user is asking to inspect current stored rules, choose list or render.
    - For unknown node ids, leave node_id null so validation can report the missing identifier.
    """
).strip()


def build_guideline_mutation_user_prompt(
    *,
    operation: str | None,
    user_request: str,
    orchestrator_guidance: str | None = None,
) -> str:
    prompt = dedent(
        f"""\
        Intent operation hint: {operation or 'unknown'}
        User request: {user_request}
        """
    ).strip()
    if orchestrator_guidance:
        prompt = f"{prompt}\nOrchestrator guidance: {orchestrator_guidance}"
    return prompt
