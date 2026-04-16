"""
HKTW Meta Auto Report - Meta Graph API Client
Supports HK and TW markets with independent App credentials and tokens.
"""
import os
import json
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
                error_msg  = body.get("error", {}).get("message", "")
                error_type = body.get("error", {}).get("type", "")
                # Log full Meta error for diagnosis
                logger.error(
                    f"[{self.market}] Meta API error — "
                    f"HTTP {resp.status_code} | code={error_code} | "
                    f"type={error_type} | message={error_msg}"
                )
                # Throttling / transient errors — retry
                if error_code in (4, 17, 32, 613) or resp.status_code in (429, 500, 503):
                    wait = self.RETRY_DELAY * attempt
                    logger.warning(
                        f"[{self.market}] Retrying in {wait}s (attempt {attempt}/{self.MAX_RETRIES})..."
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

    # ─────────────────────────────────────────
    # Page Name lookup (for KOL report)
    # ─────────────────────────────────────────

    BATCH_SIZE = 50  # Meta Batch API limit

    def get_page_names_for_ads(self, ad_ids: list[str], story_id_map: dict[str, str] | None = None) -> dict[str, str]:
        """
        Given a list of ad IDs, return a mapping of ad_id → page_name.

        Primary:  extract page_id from effective_object_story_id ("{page_id}_{post_id}")
                  passed in via story_id_map — no extra API call needed.
        Fallback: batch-query ad creatives to get page_id (for ads without story_id).
        Then:     batch-query page names from page_ids.

        Returns "" for any ad whose page cannot be resolved.
        """
        unique_ids = list(set(str(i) for i in ad_ids if i))
        if not unique_ids:
            return {}

        logger.info(f"[{self.market}] Resolving page names for {len(unique_ids)} unique ads...")

        # Step 1: ad_id → page_id
        ad_to_page: dict[str, str] = {}

        # Primary: extract from effective_object_story_id
        if story_id_map:
            for ad_id in unique_ids:
                story_id = story_id_map.get(ad_id, "")
                if story_id and "_" in str(story_id):
                    page_id = str(story_id).split("_")[0]
                    if page_id.isdigit():
                        ad_to_page[ad_id] = page_id

        # Fallback: creative API for ads still missing page_id
        missing = [ad_id for ad_id in unique_ids if ad_id not in ad_to_page]
        if missing:
            logger.info(f"[{self.market}] Falling back to creative API for {len(missing)} ads...")
            fallback = self._batch_get_page_ids(missing)
            ad_to_page.update(fallback)

        # Step 2: page_id → page_name
        unique_page_ids = list(set(v for v in ad_to_page.values() if v))
        page_id_to_name = self._batch_get_page_names(unique_page_ids)

        # Step 3: join
        result = {}
        for ad_id in unique_ids:
            page_id   = ad_to_page.get(ad_id, "")
            page_name = page_id_to_name.get(page_id, "") if page_id else ""
            result[ad_id] = page_name

        resolved = sum(1 for v in result.values() if v)
        logger.info(f"[{self.market}] Page names resolved: {resolved}/{len(unique_ids)}")
        return result

    def _batch_get_page_ids(self, ad_ids: list[str]) -> dict[str, str]:
        """
        Batch query: ad_id → page_id via ad creative.
        Returns { ad_id: page_id }
        """
        result = {}

        for i in range(0, len(ad_ids), self.BATCH_SIZE):
            chunk = ad_ids[i:i + self.BATCH_SIZE]
            batch = [
                {
                    "method":       "GET",
                    "relative_url": f"{ad_id}?fields=creative{{object_story_spec{{page_id}}}}",
                }
                for ad_id in chunk
            ]
            try:
                resp = requests.post(
                    "https://graph.facebook.com/",
                    data={
                        "access_token": self.access_token,
                        "batch":        json.dumps(batch),
                    },
                    timeout=60,
                )
                resp.raise_for_status()
                responses = resp.json()

                for j, item in enumerate(responses):
                    ad_id = chunk[j]
                    if not item or item.get("code") != 200:
                        result[ad_id] = ""
                        continue
                    try:
                        body    = json.loads(item["body"])
                        page_id = (
                            body.get("creative", {})
                                .get("object_story_spec", {})
                                .get("page_id", "")
                        )
                        result[ad_id] = str(page_id) if page_id else ""
                    except Exception:
                        result[ad_id] = ""

                time.sleep(0.5)

            except Exception as e:
                logger.warning(f"[{self.market}] Batch page_id lookup failed (chunk {i}): {e}")
                for ad_id in chunk:
                    result[ad_id] = ""

        return result

    def _batch_get_page_names(self, page_ids: list[str]) -> dict[str, str]:
        """
        Batch query: page_id → page_name.
        Returns { page_id: page_name }
        """
        result = {}
        if not page_ids:
            return result

        for i in range(0, len(page_ids), self.BATCH_SIZE):
            chunk = page_ids[i:i + self.BATCH_SIZE]
            batch = [
                {
                    "method":       "GET",
                    "relative_url": f"{page_id}?fields=name",
                }
                for page_id in chunk
            ]
            try:
                resp = requests.post(
                    "https://graph.facebook.com/",
                    data={
                        "access_token": self.access_token,
                        "batch":        json.dumps(batch),
                    },
                    timeout=60,
                )
                resp.raise_for_status()
                responses = resp.json()

                for j, item in enumerate(responses):
                    page_id = chunk[j]
                    if not item or item.get("code") != 200:
                        result[page_id] = ""
                        continue
                    try:
                        body = json.loads(item["body"])
                        result[page_id] = body.get("name", "")
                    except Exception:
                        result[page_id] = ""

                time.sleep(0.5)

            except Exception as e:
                logger.warning(f"[{self.market}] Batch page_name lookup failed (chunk {i}): {e}")
                for page_id in chunk:
                    result[page_id] = ""

        return result
