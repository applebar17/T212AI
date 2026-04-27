"""Telegram command definitions."""

from __future__ import annotations

from datetime import datetime

from t212ai.proposals.models import Proposal, ProposalDetail

HELP_COMMANDS: tuple[str, ...] = (
    "/help",
    "/summary",
    "/positions",
    "/orders",
    "/history",
    "/watchlist",
    "/analyze <ticker>",
    "/proposals",
    "/proposal <proposal_id>",
    "/cancel_order <order_id>",
    "/digest now",
)


def render_help_text() -> str:
    commands = "\n".join(f"- {command}" for command in HELP_COMMANDS)
    return (
        "T212AI Telegram bridge is available.\n\n"
        "Natural-language messages will be routed to the agent once the runtime "
        "is wired. Baseline command shortcuts:\n"
        f"{commands}"
    )


def render_recent_proposals_text(proposals: list[Proposal]) -> str:
    if not proposals:
        return "No recent proposals were found for this Telegram chat."
    lines = ["Recent proposals:"]
    for proposal in proposals:
        lines.append(
            "- "
            f"{proposal.proposal_id}: "
            f"{proposal.action_summary} | "
            f"status={proposal.status.value} | "
            f"created_at={_format_datetime(proposal.created_at)}"
        )
    return "\n".join(lines)


def render_proposal_detail_text(detail: ProposalDetail) -> str:
    proposal = detail.proposal
    lines = [
        f"Proposal {proposal.proposal_id}",
        f"Status: {proposal.status.value}",
        f"Action: {proposal.action_summary}",
        f"Created at: {_format_datetime(proposal.created_at)}",
        f"Thesis: {proposal.thesis}",
    ]
    if proposal.risks:
        lines.append("Risks:")
        lines.extend(f"- {risk}" for risk in proposal.risks)
    lines.append(f"Confidence: {round(proposal.confidence, 2)}")
    if proposal.pending_action_id:
        lines.append(f"Linked pending action: {proposal.pending_action_id}")
    if proposal.last_error:
        lines.append(f"Last error: {proposal.last_error}")
    if detail.latest_approval_event is not None:
        lines.append(
            "Latest approval event: "
            f"{detail.latest_approval_event.decision.value} via "
            f"{detail.latest_approval_event.source.value} at "
            f"{_format_datetime(detail.latest_approval_event.created_at)}"
        )
    if detail.latest_execution_attempt is not None:
        attempt = detail.latest_execution_attempt
        suffix = ""
        if attempt.broker_order_id is not None:
            suffix = f", broker_order_id={attempt.broker_order_id}"
        lines.append(
            "Latest execution attempt: "
            f"{attempt.status.value} at {_format_datetime(attempt.created_at)}{suffix}"
        )
        if attempt.error_message:
            lines.append(f"Execution error: {attempt.error_message}")
    return "\n".join(lines)


def _format_datetime(value: datetime) -> str:
    return value.isoformat()
