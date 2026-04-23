"""Shared GenAI type models."""

from typing import Any, TypedDict

from pydantic import BaseModel, Field


class ToolFunction(TypedDict):
    name: str
    description: str | None
    parameters: dict[str, Any]
    strict: bool | None


class ToolSpec(TypedDict):
    type: str
    function: ToolFunction


class StructuredOutput(BaseModel):
    """Base class for structured GenAI outputs."""

    pass


class ToolError(BaseModel):
    message: str = Field(..., description="Human readable error summary.")
    code: str | None = Field(
        None, description="Machine readable error code if available."
    )
    type: str | None = Field(
        None, description="Exception type or error category."
    )
    hint: str | None = Field(
        None, description="Suggested correction for the tool call."
    )
    retryable: bool | None = Field(
        None, description="Whether retrying the call may succeed."
    )
    details: dict[str, Any] | None = Field(
        None, description="Optional additional error context."
    )


class ToolResult(BaseModel):
    status: str = Field(
        ...,
        description="Execution status (e.g. ok, error, skipped).",
    )
    output: str | None = Field(
        None, description="Short text response for the model."
    )
    data: Any | None = Field(
        None, description="Structured tool payload or results."
    )
    error: ToolError | None = Field(
        None, description="Error details when status is error."
    )
    meta: dict[str, Any] | None = Field(
        None, description="Additional metadata for tracing or debugging."
    )
