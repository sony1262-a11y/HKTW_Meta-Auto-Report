"""
PATCH INSTRUCTIONS for meta_api_client.py
==========================================
Add get_insights_async() method AFTER get_insights() method.
The method uses the existing _get() and _paginate() helpers.
"""

# ── Paste this method inside class MetaAPIClient, after get_insights() ────────

PATCH = '''
    def get_insights_async(
        self,
        ad_account_id: str,
        date_start: str,
        date_stop: str,
        level: str = "ad",
        fields: list[str] | None = None,
        breakdowns: list[str] | None = None,
        filtering: list[dict] | None = None,
        time_increment: str | int = 1,
        poll_interval: int = 10,
        max_wait: int = 3600,
    ) -> list[dict]:
        """
        Submit a Meta Async Insights job and poll until complete.
        Use for large accounts where synchronous requests return HTTP 500
        'Please reduce the amount of data'.

        Flow:
          1. POST /{account}/insights  → report_run_id
          2. Poll GET /{report_run_id} until async_status == 'Job Complete'
          3. GET /{report_run_id}/insights (paginated) → rows
        """
        if fields is None:
            fields = self._default_fields(level)

        # ── Step 1: Submit async job ──────────────────────────────────────────
        url    = f"{META_API_BASE}/{ad_account_id}/insights"
        params = {
            "level":          level,
            "fields":         ",".join(fields),
            "time_range":     f\'{{"since":"{date_start}","until":"{date_stop}"}}\',
            "time_increment": time_increment,
            "access_token":   self.access_token,
            "limit":          500,
        }
        if breakdowns:
            params["breakdowns"] = ",".join(breakdowns)
        if filtering:
            params["filtering"] = json.dumps(filtering)

        logger.info(
            f"[{self.market}] {ad_account_id} | {date_start}~{date_stop} | "
            f"submitting async job..."
        )
        resp = requests.post(url, data=params, timeout=60)
        resp.raise_for_status()
        job_data = resp.json()
        report_run_id = job_data.get("report_run_id")
        if not report_run_id:
            raise RuntimeError(
                f"[{self.market}] Async job submission failed — no report_run_id in: {job_data}"
            )
        logger.info(f"[{self.market}] Async job submitted: {report_run_id}")

        # ── Step 2: Poll until Job Complete ──────────────────────────────────
        elapsed = 0
        while elapsed < max_wait:
            time.sleep(poll_interval)
            elapsed += poll_interval
            status = self._get(
                f"{META_API_BASE}/{report_run_id}",
                {"access_token": self.access_token},
            )
            async_status = status.get("async_status", "")
            pct          = status.get("async_percent_completion", 0)
            logger.info(
                f"[{self.market}] Job {report_run_id}: {async_status} ({pct}%)"
            )
            if async_status == "Job Complete":
                break
            if async_status in ("Job Failed", "Job Skipped"):
                raise RuntimeError(
                    f"[{self.market}] Async job {async_status}: {status}"
                )
        else:
            raise RuntimeError(
                f"[{self.market}] Async job {report_run_id} timed out after {max_wait}s"
            )

        # ── Step 3: Fetch results (paginated) ─────────────────────────────────
        results_url    = f"{META_API_BASE}/{report_run_id}/insights"
        results_params = {"access_token": self.access_token, "limit": 500}
        rows = self._paginate(results_url, results_params)
        logger.info(
            f"[{self.market}] {ad_account_id} | {date_start}~{date_stop} | "
            f"async | {len(rows)} rows"
        )
        return rows
'''

if __name__ == "__main__":
    print("This file documents the patch. Apply to meta_api_client.py manually.")
    print(PATCH)
