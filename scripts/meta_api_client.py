"""
HKTW Meta Auto Report - Meta Graph API Client
Supports HK and TW markets with independent App credentials and tokens.
"""
import os
import time
import logging
import requests
from datetime import datetime, timedelta
from config.settings import META_API_BASE, MARKETS

logger = logging.getLogger(__name__)


class MetaAPIClient:
    """
    Meta Graph API client scoped to a single market (HK or TW).

    Usage:
        client = MetaAPIClient("HK")
        accounts = client.get_ad_accounts()
    """

    MAX_RETRIES = 3
    RETRY_DELAY = 5  # seconds

    def __init__(self, market: str):
        if market not in MARKETS:
            raise ValueError(f"Unknown market '{market}'. Must be one of {list(MARKETS.keys())}")

        self.market = market
        creds = MARKETS[market]

        self.app_id       = creds["app_id"]
        self.app_secret   = creds["app_secret"]
        self.access_token = creds["access_token"]

        if not all([self.app_id, self.app_secret, self.access_token]):
            raise EnvironmentError(
                f"Missing Meta credentials for market {market}. "
                f"Check META_{market}_APP_ID / META_{market}_APP_SECRET / META_{market}_ACCESS_TOKEN."
            )

        logger.info(f"[{market}] MetaAPIClient initialized (App ID: {self.app_id})")

    # ─────────────────────────────────────────
    # Token utilities
    # ─────────────────────────────────────────

    def get_token_info(self) -> dict:
        """Inspect current access token via debug_token endpoint."""
        url = f"{META_API_BASE}/debug_token"
        params = {
            "input_token":  self.access_token,
            "access_token": f"{self.app_id}|{self.app_secret}",
        }
        resp = self._get(url, params)
        return resp.get("data", {})

    def get_token_expiry_days(self) -> int | None:
        """Return days until token expiry, or None if non-expiring / unreadable."""
        info = self.get_token_info()
        expires_at = info.get("expires_at")
        if not expires_at or expires_at == 0:
            return None  # non-expiring token
        expiry_dt = datetime.utcfromtimestamp(expires_at)
        delta = expiry_dt - datetime.utcnow()
        return delta.days

    def extend_token(self) -> str:
        """
        Exchange current short-lived token for a long-lived token (~60 days).
        Updates self.access_token in place and returns the new token.
        """
        url = f"{META_API_BASE}/oauth/access_token"
        params = {
            "grant_type":        "fb_exchange_token",
            "client_id":         self.app_id,
            "client_secret":     self.app_secret,
            "fb_exchange_token": self.access_token,
        }
        resp = self._get(url, params)
        new_token = resp.get("access_token")
        if not new_token:
            raise RuntimeError(f"[{self.market}] Token extension failed: {resp}")
        self.access_token = new_token
        logger.info(f"[{self.market}] Token extended successfully.")
        return new_token

    # ─────────────────────────────────────────
    # Ad Account info
    # ─────────────────────────────────────────

    def get_account_info(self, ad_account_id: str) -> dict:
        """
        Fetch basic info for a single ad account by ID.
        Used to verify account is accessible with current token.
        System User Tokens cannot use /me/adaccounts — must specify account ID directly.

        Returns dict with id, name, account_status, currency.
        Returns {} on error.
        """
        url = f"{META_API_BASE}/{ad_account_id}"
        params = {
            "fields":       "id,name,account_status,currency",
            "access_token": self.access_token,
        }
        try:
            result = self._get(url, params)
            return result
        except Exception as e:
            logger.warning(f"[{self.market}] Could not fetch info for {ad_account_id}: {e}")
            return {}

    # ─────────────────────────────────────────
    # Insights (core data fetch)
    # ─────────────────────────────────────────

    def get_insights(
        self,
        ad_account_id: str,
        date_start: str,
        date_stop: str,
        level: str = "ad",
        fields: list[str] | None = None,
        breakdowns: list[str] | None = None,
        filtering: list[dict] | None = None,
    ) -> list[dict]:
        """
        Fetch ad insights for a given ad account and date range.

        Args:
            ad_account_id: e.g. "act_1234567890"
            date_start:    "YYYY-MM-DD"
            date_stop:     "YYYY-MM-DD"
            level:         "ad" | "adset" | "campaign" | "account"
            fields:        list of insight fields to request
            breakdowns:    optional breakdown dimensions
            filtering:     optional filter array

        Returns:
            List of row dicts.
        """
        if fields is None:
            fields = self._default_fields(level)

        url = f"{META_API_BASE}/{ad_account_id}/insights"
        params = {
            "level":        level,
            "fields":       ",".join(fields),
            "time_range":   f'{{"since":"{date_start}","until":"{date_stop}"}}',
            "time_increment": 1,       # daily breakdown
            "access_token": self.access_token,
            "limit":        500,
        }
        if breakdowns:
            params["breakdowns"] = ",".join(breakdowns)
        if filtering:
            import json
            params["filtering"] = json.dumps(filtering)

        rows = self._paginate(url, params)
        logger.info(
            f"[{self.market}] {ad_account_id} | {date_start}~{date_stop} | "
            f"{level} level | {len(rows)} rows"
        )
        return rows

    def get_insights_async(
        self,
        ad_account_id: str,
        date_start: str,
        date_stop: str,
        level: str = "ad",
        fields: list[str] | None = None,
        breakdowns: list[str] | None = None,
        filtering: list[dict] | None = None,
        poll_interval: int = 10,
        max_wait: int = 300,
    ) -> list[dict]:
        """
        Create an async insights report job and poll until complete.
        Use for large date ranges to avoid API timeouts.
        """
        if fields is None:
            fields = self._default_fields(level)

        import json

        url = f"{META_API_BASE}/{ad_account_id}/insights"
        payload = {
            "level":          level,
            "fields":         ",".join(fields),
            "time_range":     json.dumps({"since": date_start, "until": date_stop}),
            "time_increment": 1,
            "access_token":   self.access_token,
            "limit":          500,
        }
        if breakdowns:
            payload["breakdowns"] = ",".join(breakdowns)
        if filtering:
            payload["filtering"] = json.dumps(filtering)

        # Create async job
        resp = requests.post(url, data=payload)
        resp.raise_for_status()
        report_run_id = resp.json().get("report_run_id")
        if not report_run_id:
            raise RuntimeError(f"[{self.market}] Failed to create async job: {resp.json()}")

        logger.info(f"[{self.market}] Async job created: {report_run_id}")

        # Poll for completion
        job_url = f"{META_API_BASE}/{report_run_id}"
        waited = 0
        while waited < max_wait:
            time.sleep(poll_interval)
            waited += poll_interval
            status_resp = self._get(job_url, {"access_token": self.access_token})
            status = status_resp.get("async_status")
            pct = status_resp.get("async_percent_completion", 0)
            logger.info(f"[{self.market}] Job {report_run_id}: {status} ({pct}%)")
            if status == "Job Completed":
                break
            if status in ("Job Failed", "Job Skipped"):
                raise RuntimeError(f"[{self.market}] Async job failed: {status}")

        # Retrieve results
        results_url = f"{META_API_BASE}/{report_run_id}/insights"
        rows = self._paginate(results_url, {"access_token": self.access_token, "limit": 500})
        logger.info(f"[{self.market}] Async job {report_run_id}: {len(rows)} rows retrieved")
        return rows

    # ─────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────

    def _default_fields(self, level: str) -> list[str]:
        base = [
            "date_start", "date_stop",
            "campaign_id", "campaign_name",
            "adset_id", "adset_name",
        ]
        if level == "ad":
            base += ["ad_id", "ad_name"]
        base += [
            "impressions", "clicks", "spend",
            "reach", "frequency",
            "actions", "action_values",
        ]
        return base

    def _get(self, url: str, params: dict) -> dict:
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                resp = requests.get(url, params=params, timeout=30)
                resp.raise_for_status()
                return resp.json()
            except requests.HTTPError as e:
                body = {}
                try:
                    body = resp.json()
                except Exception:
                    pass
                error_code = body.get("error", {}).get("code")
                # Throttling / transient errors — retry
                if error_code in (4, 17, 32, 613) or resp.status_code in (429, 500, 503):
                    wait = self.RETRY_DELAY * attempt
                    logger.warning(
                        f"[{self.market}] API error {error_code} on attempt {attempt}, "
                        f"retrying in {wait}s..."
                    )
                    time.sleep(wait)
                else:
                    raise
        raise RuntimeError(f"[{self.market}] API call failed after {self.MAX_RETRIES} retries")

    def _paginate(self, url: str, params: dict) -> list[dict]:
        """Follow paging.next cursors and collect all rows."""
        all_rows = []
        current_url = url
        current_params = params.copy()

        while True:
            resp = self._get(current_url, current_params)
            data = resp.get("data", [])
            all_rows.extend(data)

            next_url = resp.get("paging", {}).get("next")
            if not next_url:
                break
            # next URL has params baked in — pass empty params
            current_url = next_url
            current_params = {}

        return all_rows
