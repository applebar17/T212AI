"""Normalized SEC EDGAR filing-activity models."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class EdgarCompanyReference(BaseModel):
    ticker: str
    cik: str
    name: str | None = None


class EdgarFilingRecord(BaseModel):
    form: str
    normalized_form: str
    filed_at: date | None = None
    accession_number: str | None = None
    primary_document: str | None = None
    filing_url: str | None = None
    category: str


class EdgarFilingActivityResult(BaseModel):
    symbol: str
    cik: str
    company_name: str | None = None
    activity_label: str
    since_days: int
    tracked_forms: list[str] = Field(default_factory=list)
    filing_counts: dict[str, int] = Field(default_factory=dict)
    recent_filings: list[EdgarFilingRecord] = Field(default_factory=list)
    fresh_activity_signal: str = "quiet"
    notes: list[str] = Field(default_factory=list)

    def render_text(self) -> str:
        lines = [
            f"SEC EDGAR {self.activity_label} for {self.symbol} over the last {self.since_days} day(s).",
            f"Company: {self.company_name or 'unknown'} (CIK {self.cik}).",
            (
                "Tracked forms: "
                + (", ".join(self.tracked_forms) if self.tracked_forms else "none")
                + "."
            ),
            (
                "Fresh filing activity signal: "
                f"{self.fresh_activity_signal}."
            ),
        ]
        if self.filing_counts:
            counts = ", ".join(
                f"{form}={count}" for form, count in self.filing_counts.items() if count > 0
            )
            lines.append(f"Counts: {counts or 'no matching filings'}.\n")
        else:
            lines.append("Counts: no matching filings.\n")
        if self.recent_filings:
            lines.append("Recent filings:")
            for filing in self.recent_filings:
                lines.append(
                    "- "
                    f"{filing.form} filed {filing.filed_at.isoformat() if filing.filed_at else 'unknown'}"
                    f"{f' ({filing.filing_url})' if filing.filing_url else ''}."
                )
        if self.notes:
            lines.append("Notes:")
            lines.extend(f"- {note}" for note in self.notes)
        return "\n".join(lines)
