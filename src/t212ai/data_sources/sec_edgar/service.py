"""Higher-level SEC EDGAR insider/disclosure manager."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from .client import SecEdgarClient
from .models import EdgarCompanyReference, EdgarFilingActivityResult, EdgarFilingRecord


OWNERSHIP_FORMS = ("3", "4", "5")
STAKE_FORMS = ("13D", "13G")
DISCLOSURE_FORMS = ("8-K", "10-Q", "10-K", "3", "4", "5", "13D", "13G")


class EdgarInsiderManager:
    def __init__(self, client: SecEdgarClient) -> None:
        self.client = client
        self._ticker_cache: dict[str, EdgarCompanyReference] | None = None

    def resolve_company(self, symbol: str) -> EdgarCompanyReference:
        ticker = str(symbol or "").strip().upper()
        if not ticker:
            raise ValueError("symbol is required.")
        if self._ticker_cache is None:
            self._ticker_cache = self._build_ticker_cache()
        resolved = self._ticker_cache.get(ticker)
        if resolved is None:
            raise ValueError(f"SEC EDGAR could not resolve ticker '{ticker}' to a CIK.")
        return resolved

    def recent_ownership_activity(
        self,
        symbol: str,
        *,
        since_days: int = 30,
        limit: int = 10,
    ) -> EdgarFilingActivityResult:
        company = self.resolve_company(symbol)
        filings = self._recent_filings(company, since_days=since_days, form_filters=OWNERSHIP_FORMS)
        limited = filings[: max(1, int(limit or 10))]
        return self._build_activity_result(
            company,
            activity_label="ownership activity",
            since_days=since_days,
            tracked_forms=list(OWNERSHIP_FORMS),
            filings=limited,
            full_filings=filings,
            notes=[
                "Forms 3, 4, and 5 report insider ownership changes and related holdings disclosures.",
                "This is official SEC filing context, not a direct trade signal.",
            ],
        )

    def recent_major_stake_activity(
        self,
        symbol: str,
        *,
        since_days: int = 90,
        limit: int = 10,
    ) -> EdgarFilingActivityResult:
        company = self.resolve_company(symbol)
        filings = self._recent_filings(company, since_days=since_days, form_filters=STAKE_FORMS)
        limited = filings[: max(1, int(limit or 10))]
        return self._build_activity_result(
            company,
            activity_label="major stake activity",
            since_days=since_days,
            tracked_forms=list(STAKE_FORMS),
            filings=limited,
            full_filings=filings,
            notes=[
                "13D and 13G filings indicate significant ownership stake disclosures.",
                "13D is generally associated with more active intent than 13G.",
            ],
        )

    def company_disclosure_snapshot(
        self,
        symbol: str,
        *,
        since_days: int = 30,
        limit: int = 12,
    ) -> EdgarFilingActivityResult:
        company = self.resolve_company(symbol)
        filings = self._recent_filings(
            company,
            since_days=since_days,
            form_filters=DISCLOSURE_FORMS,
        )
        limited = filings[: max(1, int(limit or 12))]
        return self._build_activity_result(
            company,
            activity_label="disclosure snapshot",
            since_days=since_days,
            tracked_forms=list(DISCLOSURE_FORMS),
            filings=limited,
            full_filings=filings,
            notes=[
                "8-K filings report important current events.",
                "10-Q and 10-K filings provide quarterly and annual reporting context.",
                "Ownership and stake filings can add official disclosure context to market anomalies.",
            ],
        )

    def _build_ticker_cache(self) -> dict[str, EdgarCompanyReference]:
        payload = self.client.get_company_tickers()
        cache: dict[str, EdgarCompanyReference] = {}
        for item in payload.values():
            if not isinstance(item, dict):
                continue
            ticker = str(item.get("ticker") or "").strip().upper()
            cik_raw = item.get("cik_str")
            if not ticker or cik_raw in {None, ""}:
                continue
            cik = str(cik_raw).strip().zfill(10)
            cache[ticker] = EdgarCompanyReference(
                ticker=ticker,
                cik=cik,
                name=str(item.get("title") or "").strip() or None,
            )
        return cache

    def _recent_filings(
        self,
        company: EdgarCompanyReference,
        *,
        since_days: int,
        form_filters: tuple[str, ...],
    ) -> list[EdgarFilingRecord]:
        cutoff = date.today() - timedelta(days=max(1, int(since_days or 1)))
        submissions = self.client.get_submissions(company.cik)
        filings = self._collect_filings(
            submissions,
            company=company,
            cutoff=cutoff,
            form_filters=set(form_filters),
        )
        filings.sort(
            key=lambda item: item.filed_at or date.min,
            reverse=True,
        )
        return filings

    def _collect_filings(
        self,
        submissions: dict[str, Any],
        *,
        company: EdgarCompanyReference,
        cutoff: date,
        form_filters: set[str],
    ) -> list[EdgarFilingRecord]:
        out = self._rows_to_filings(
            _columnar_rows((submissions.get("filings") or {}).get("recent") or {}),
            company=company,
            cutoff=cutoff,
            form_filters=form_filters,
        )
        for extra in (submissions.get("filings") or {}).get("files") or []:
            if not isinstance(extra, dict):
                continue
            if not _file_may_overlap_cutoff(extra, cutoff):
                continue
            name = str(extra.get("name") or "").strip()
            if not name:
                continue
            payload = self.client.get_submissions_file(name)
            out.extend(
                self._rows_to_filings(
                    _columnar_rows(payload),
                    company=company,
                    cutoff=cutoff,
                    form_filters=form_filters,
                )
            )
        deduped: dict[tuple[str | None, str | None], EdgarFilingRecord] = {}
        for filing in out:
            key = (filing.accession_number, filing.form)
            if key not in deduped:
                deduped[key] = filing
        return list(deduped.values())

    def _rows_to_filings(
        self,
        rows: list[dict[str, Any]],
        *,
        company: EdgarCompanyReference,
        cutoff: date,
        form_filters: set[str],
    ) -> list[EdgarFilingRecord]:
        filings: list[EdgarFilingRecord] = []
        for row in rows:
            form = str(row.get("form") or "").strip()
            if not form:
                continue
            normalized = _normalize_form(form)
            if normalized not in form_filters:
                continue
            filed_at = _parse_date(row.get("filingDate"))
            if filed_at is None or filed_at < cutoff:
                continue
            accession_number = str(row.get("accessionNumber") or "").strip() or None
            primary_document = str(row.get("primaryDocument") or "").strip() or None
            filings.append(
                EdgarFilingRecord(
                    form=form,
                    normalized_form=normalized,
                    filed_at=filed_at,
                    accession_number=accession_number,
                    primary_document=primary_document,
                    filing_url=_build_filing_url(company.cik, accession_number, primary_document),
                    category=_category_for_form(normalized),
                )
            )
        return filings

    def _build_activity_result(
        self,
        company: EdgarCompanyReference,
        *,
        activity_label: str,
        since_days: int,
        tracked_forms: list[str],
        filings: list[EdgarFilingRecord],
        full_filings: list[EdgarFilingRecord],
        notes: list[str],
    ) -> EdgarFilingActivityResult:
        counts = {form: 0 for form in tracked_forms}
        for filing in full_filings:
            counts[filing.normalized_form] = counts.get(filing.normalized_form, 0) + 1
        return EdgarFilingActivityResult(
            symbol=company.ticker,
            cik=company.cik,
            company_name=company.name,
            activity_label=activity_label,
            since_days=since_days,
            tracked_forms=tracked_forms,
            filing_counts=counts,
            recent_filings=filings,
            fresh_activity_signal=_signal_for_count(sum(counts.values())),
            notes=notes,
        )


def _columnar_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not payload:
        return []
    lengths = [len(value) for value in payload.values() if isinstance(value, list)]
    if not lengths:
        return []
    count = max(lengths)
    rows: list[dict[str, Any]] = []
    for index in range(count):
        row = {
            key: value[index]
            for key, value in payload.items()
            if isinstance(value, list) and index < len(value)
        }
        if row:
            rows.append(row)
    return rows


def _parse_date(value: Any) -> date | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw).date()
    except ValueError:
        try:
            return date.fromisoformat(raw)
        except ValueError:
            return None


def _normalize_form(form: str) -> str:
    raw = str(form or "").strip().upper()
    if raw.startswith("SC 13D"):
        return "13D"
    if raw.startswith("SC 13G"):
        return "13G"
    if raw.endswith("/A"):
        raw = raw.removesuffix("/A")
    return raw


def _category_for_form(form: str) -> str:
    if form in OWNERSHIP_FORMS:
        return "ownership"
    if form in STAKE_FORMS:
        return "stake"
    if form in {"8-K", "10-Q", "10-K"}:
        return "disclosure"
    return "other"


def _build_filing_url(
    cik: str,
    accession_number: str | None,
    primary_document: str | None,
) -> str | None:
    if not accession_number:
        return None
    cik_numeric = str(int(cik))
    accession_no_dashes = accession_number.replace("-", "")
    if primary_document:
        return (
            "https://www.sec.gov/Archives/edgar/data/"
            f"{cik_numeric}/{accession_no_dashes}/{primary_document}"
        )
    return (
        "https://www.sec.gov/Archives/edgar/data/"
        f"{cik_numeric}/{accession_no_dashes}/index.json"
    )


def _file_may_overlap_cutoff(file_info: dict[str, Any], cutoff: date) -> bool:
    from_date = _parse_date(file_info.get("filingFrom"))
    to_date = _parse_date(file_info.get("filingTo"))
    if from_date is None and to_date is None:
        return True
    if to_date is not None and to_date < cutoff:
        return False
    return True


def _signal_for_count(count: int) -> str:
    if count >= 3:
        return "elevated"
    if count >= 1:
        return "recent_activity"
    return "quiet"
