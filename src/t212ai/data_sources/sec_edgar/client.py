"""SEC EDGAR API client."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


SEC_EDGAR_SUBMISSIONS_BASE_URL = "https://data.sec.gov/submissions"
SEC_EDGAR_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
DEFAULT_SEC_EDGAR_USER_AGENT = "t212ai-sec-edgar/0.1"


class SecEdgarApiError(RuntimeError):
    pass


class SecEdgarClient:
    def __init__(
        self,
        *,
        submissions_base_url: str = SEC_EDGAR_SUBMISSIONS_BASE_URL,
        tickers_url: str = SEC_EDGAR_TICKERS_URL,
        user_agent: str = DEFAULT_SEC_EDGAR_USER_AGENT,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.submissions_base_url = submissions_base_url.rstrip("/")
        self.tickers_url = tickers_url
        self.user_agent = str(user_agent or DEFAULT_SEC_EDGAR_USER_AGENT).strip()
        self.timeout_seconds = float(timeout_seconds)

    @classmethod
    def from_settings(cls, settings: object | None = None) -> "SecEdgarClient":
        resolved = settings
        return cls(
            submissions_base_url=getattr(
                resolved,
                "sec_edgar_submissions_base_url",
                os.getenv(
                    "SEC_EDGAR_SUBMISSIONS_BASE_URL",
                    SEC_EDGAR_SUBMISSIONS_BASE_URL,
                ),
            ),
            tickers_url=getattr(
                resolved,
                "sec_edgar_tickers_url",
                os.getenv("SEC_EDGAR_TICKERS_URL", SEC_EDGAR_TICKERS_URL),
            ),
            user_agent=getattr(
                resolved,
                "sec_edgar_user_agent",
                os.getenv("SEC_EDGAR_USER_AGENT", DEFAULT_SEC_EDGAR_USER_AGENT),
            )
            or DEFAULT_SEC_EDGAR_USER_AGENT,
        )

    def get_company_tickers(self) -> dict[str, Any]:
        return self._read_json_url(self.tickers_url)

    def get_submissions(self, cik: str) -> dict[str, Any]:
        resolved_cik = _normalize_cik(cik)
        url = f"{self.submissions_base_url}/CIK{resolved_cik}.json"
        return self._read_json_url(url)

    def get_submissions_file(self, name: str) -> dict[str, Any]:
        resolved_name = str(name or "").strip()
        if not resolved_name:
            raise ValueError("submissions file name is required.")
        url = f"{self.submissions_base_url}/{urllib.parse.quote(resolved_name)}"
        return self._read_json_url(url)

    def _read_json_url(self, url: str) -> dict[str, Any]:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept-Encoding": "gzip, deflate",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            raw_body = exc.read().decode("utf-8", errors="replace")
            raise SecEdgarApiError(
                f"SEC EDGAR HTTP {exc.code} for {url}. Body preview: {raw_body[:400]}"
            ) from exc
        except urllib.error.URLError as exc:
            raise SecEdgarApiError(
                f"Network error contacting SEC EDGAR: {exc.reason}"
            ) from exc

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SecEdgarApiError(
                f"SEC EDGAR returned invalid JSON for {url}."
            ) from exc
        if not isinstance(data, dict):
            raise SecEdgarApiError(
                f"SEC EDGAR returned a non-object JSON payload for {url}."
            )
        return data


def _normalize_cik(value: str) -> str:
    raw = "".join(ch for ch in str(value or "").strip() if ch.isdigit())
    if not raw:
        raise ValueError("cik is required.")
    return raw.zfill(10)
