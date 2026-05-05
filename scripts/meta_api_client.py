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
    MAX_RETRIES = 3
    RETRY_DELAY = 5
    BATCH_SIZE  = 50

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

    # ── Token utilities ──────────────────────────────────────────────────────

    def get_token_info(self) -> dict:
        url = f"{META_API_BASE}/debug_token"
        params = {
            "input_token":  self.access_token,
            "access_token": f"{self.app_id}|{self.app_secret}",
        }
        resp = self._get(url, params)
        return resp.get("data", {})

    def get_token_expiry_days(self) -> int | None:
        info = self.get_token_info()
        expires_at = info.get("expires_at")
        if not expires_at or expires_at == 0:
            return None
        expiry_dt = datetime.utcfromtimestamp(expires_at)
        delta = expiry_dt - datetime.utcnow()
        return delta.days

    def extend_token(self) -> str:
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

    # ── Ad Account info ──────────────────────────────────────────────────────

    def get_account_info(self, ad_account_id: str) -> dict:
        url = f"{META_API_BASE}/{ad_account_id}"
        params = {
            "fields":       "id,name,account_status,currency",
            "access_token": self.access_token,
        }
        try:
            return self._get(url, params)
        except Exception as e:
            logger.warning(f"[{self.market}] Could not fetch info for {ad_account_id}: {e}")
            return {}

    # ── Insights ─────────────────────────────────────────────────────────────

    def get_insights(
        self,
        ad_account_id: str,
        date_start: str,
        date_stop: str,
        level: str = "ad",
        fields: list[str] | None = None,
        breakdowns: list[str] | None = None,
        filtering: list[dict] | None = None,
        time_increment: str | int = 1,
    ) -> list[dict]:
        if fields is None:
            fields = self._default_fields(level)
        url = f"{META_API_BASE}/{ad_account_id}/insights"
        params = {
            "level":          level,
            "fields":         ",".join(fields),
            "time_range":     f'{{"since":"{date_start}","until":"{date_stop}"}}',
            "time_increment": time_increment,
            "access_token":   self.access_token,
            "limit":          500,
        }
        if breakdowns:
            params["breakdowns"] = ",".join(breakdowns)
        if filtering:
            params["filtering"] = json.dumps(filtering)
        rows = self._paginate(url, params)
        logger.info(
            f"[{self.market}] {ad_account_id} | {date_start}~{date_stop} | "
            f"{level} level | {len(rows)} rows"
        )
        return rows

    # ── Campaign info ─────────────────────────────────────────────────────────

    def get_campaign_info(self, campaign_ids: list[str]) -> dict[str, dict]:
        """
        Batch query campaign-level fields: start_time, stop_time, budget.
        Returns { campaign_id: {"start": str, "stop": str, "budget": str} }
        Budget value is in account currency (already in full units, not cents for most currencies).
        """
        unique_ids = list(set(str(c) for c in campaign_ids if c))
        if not unique_ids:
            return {}

        logger.info(f"[{self.market}] Fetching campaign info for {len(unique_ids)} campaigns...")
        result: dict[str, dict] = {}
        empty = {"start": "", "stop": "", "budget": ""}

        for i in range(0, len(unique_ids), self.BATCH_SIZE):
            chunk = unique_ids[i:i + self.BATCH_SIZE]
            batch = [
                {
                    "method":       "GET",
                    "relative_url": (
                        f"{cid}?fields=start_time,stop_time,daily_budget,lifetime_budget"
                    ),
                }
                for cid in chunk
            ]
            try:
                resp = requests.post(
                    f"{META_API_BASE}/",
                    data={"access_token": self.access_token, "batch": json.dumps(batch)},
                    timeout=60,
                )
                resp.raise_for_status()
                responses = resp.json()

                for j, item in enumerate(responses):
                    cid = chunk[j]
                    if not item or item.get("code") != 200:
                        result[cid] = dict(empty)
                        continue
                    try:
                        body = json.loads(item["body"])
                        # Budget: prefer lifetime_budget, fallback daily_budget
                        # Meta returns budget in cents for some currencies — divide by 100
                        raw_budget = body.get("lifetime_budget") or body.get("daily_budget") or ""
                        if raw_budget and str(raw_budget).isdigit() and int(raw_budget) > 0:
                            budget = str(int(raw_budget) / 100)
                        else:
                            budget = str(raw_budget) if raw_budget else ""

                        start = body.get("start_time", "")
                        stop  = body.get("stop_time", "")
                        # Trim to date only (YYYY-MM-DD), drop timezone
                        result[cid] = {
                            "start":  start[:10] if start else "",
                            "stop":   stop[:10] if stop else "",
                            "budget": budget,
                        }
                    except Exception:
                        result[cid] = dict(empty)

                time.sleep(0.3)
            except Exception as e:
                logger.warning(f"[{self.market}] Batch campaign info failed (chunk {i}): {e}")
                for cid in chunk:
                    result[cid] = dict(empty)

        resolved = sum(1 for v in result.values() if v.get("start"))
        logger.info(f"[{self.market}] get_campaign_info: {resolved}/{len(unique_ids)} campaigns resolved")
        return result

    # ── Creative info ─────────────────────────────────────────────────────────

    def get_page_names_for_ads(self, ad_ids: list[str], story_id_map: dict[str, str] | None = None) -> dict[str, str]:
        unique_ids = list(set(str(i) for i in ad_ids if i))
        if not unique_ids:
            return {}
        logger.info(f"[{self.market}] Resolving page names for {len(unique_ids)} unique ads...")
        ad_to_page: dict[str, str] = {}
        if story_id_map:
            for ad_id in unique_ids:
                story_id = story_id_map.get(ad_id, "")
                if story_id and "_" in str(story_id):
                    page_id = str(story_id).split("_")[0]
                    if page_id.isdigit():
                        ad_to_page[ad_id] = page_id
        missing = [ad_id for ad_id in unique_ids if ad_id not in ad_to_page]
        if missing:
            logger.info(f"[{self.market}] Falling back to creative API for {len(missing)} ads...")
            creative_data = self._batch_get_creative_info(missing)
            for ad_id, info in creative_data.items():
                if info.get("page_id"):
                    ad_to_page[ad_id] = info["page_id"]
        unique_page_ids = list(set(v for v in ad_to_page.values() if v))
        page_id_to_name = self._batch_get_page_names(unique_page_ids)
        result = {}
        for ad_id in unique_ids:
            page_id   = ad_to_page.get(ad_id, "")
            page_name = page_id_to_name.get(page_id, "") if page_id else ""
            result[ad_id] = page_name
        resolved = sum(1 for v in result.values() if v)
        logger.info(f"[{self.market}] Page names resolved: {resolved}/{len(unique_ids)}")
        return result

    def get_creative_info_for_ads(self, ad_ids: list[str]) -> dict[str, dict]:
        unique_ids = list(set(str(i) for i in ad_ids if i))
        if not unique_ids:
            return {}
        logger.info(f"[{self.market}] Fetching creative info for {len(unique_ids)} unique ads...")
        return self._batch_get_creative_info(unique_ids)

    def get_video_urls(self, video_ids: list[str]) -> dict[str, dict]:
        """
        Fetch both permalink URL (stable, facebook.com domain) and
        source URL (direct CDN .mp4, expires within hours) for each video.
        Returns { video_id: {"permalink": str, "source": str} }
        """
        unique_ids = list(set(str(v) for v in video_ids if v and not str(v).startswith("__post__")))
        if not unique_ids:
            return {}
        logger.info(f"[{self.market}] Fetching video URLs (permalink+source) for {len(unique_ids)} unique videos...")
        result: dict[str, dict] = {}
        for i in range(0, len(unique_ids), self.BATCH_SIZE):
            chunk = unique_ids[i:i + self.BATCH_SIZE]
            batch = [{"method": "GET", "relative_url": f"{vid}?fields=permalink_url,source"} for vid in chunk]
            try:
                resp = requests.post(
                    f"{META_API_BASE}/",
                    data={"access_token": self.access_token, "batch": json.dumps(batch)},
                    timeout=60,
                )
                resp.raise_for_status()
                responses = resp.json()
                for j, item in enumerate(responses):
                    vid = chunk[j]
                    if not item or item.get("code") != 200:
                        result[vid] = {"permalink": "", "source": ""}
                        continue
                    try:
                        body      = json.loads(item["body"])
                        permalink = body.get("permalink_url", "")
                        if permalink and permalink.startswith("/"):
                            permalink = f"https://www.facebook.com{permalink}"
                        source = body.get("source", "")
                        result[vid] = {"permalink": permalink, "source": source}
                    except Exception:
                        result[vid] = {"permalink": "", "source": ""}
                time.sleep(0.5)
            except Exception as e:
                logger.warning(f"[{self.market}] Batch video URL lookup failed (chunk {i}): {e}")
                for vid in chunk:
                    result[vid] = {"permalink": "", "source": ""}
        resolved_pl = sum(1 for v in result.values() if v.get("permalink"))
        resolved_src = sum(1 for v in result.values() if v.get("source"))
        logger.info(
            f"[{self.market}] get_video_urls: "
            f"permalink={resolved_pl}/{len(unique_ids)}, source={resolved_src}/{len(unique_ids)}"
        )
        return result

    def get_video_source_urls(self, video_ids: list[str]) -> dict[str, str]:
        """Direct downloadable CDN source URLs (.mp4/.mov). Expire within hours."""
        unique_ids = [str(v) for v in video_ids if v and not str(v).startswith("__post__")]
        if not unique_ids:
            return {}
        logger.info(f"[{self.market}] Fetching video source URLs for {len(unique_ids)} unique videos...")
        result: dict[str, str] = {}
        for i in range(0, len(unique_ids), self.BATCH_SIZE):
            chunk = unique_ids[i:i + self.BATCH_SIZE]
            batch = [{"method": "GET", "relative_url": f"{vid}?fields=source"} for vid in chunk]
            try:
                resp = requests.post(
                    f"{META_API_BASE}/",
                    data={"access_token": self.access_token, "batch": json.dumps(batch)},
                    timeout=60,
                )
                resp.raise_for_status()
                responses = resp.json()
                resolved = 0
                for j, item in enumerate(responses):
                    vid = chunk[j]
                    if not item or item.get("code") != 200:
                        result[vid] = ""
                        continue
                    try:
                        body = json.loads(item["body"])
                        src  = body.get("source", "")
                        result[vid] = src
                        if src:
                            resolved += 1
                    except Exception:
                        result[vid] = ""
                if i == 0:
                    logger.info(f"[{self.market}] video source chunk 0: {resolved}/{len(chunk)} resolved")
                time.sleep(0.5)
            except Exception as e:
                logger.warning(f"[{self.market}] Batch video source lookup failed (chunk {i}): {e}")
                for vid in chunk:
                    result[vid] = ""
        resolved_total = sum(1 for v in result.values() if v)
        logger.info(f"[{self.market}] get_video_source_urls: {resolved_total}/{len(unique_ids)} URLs resolved")
        return result

    def get_post_media(self, story_ids: list[str]) -> dict[str, dict]:
        """
        Fallback: query post attachments via object_story_id ({page_id}_{post_id}).
        Returns { story_id: { "image_url": str, "video_url": str } }
        """
        unique_ids = [s for s in story_ids if s and "_" in str(s) and not str(s).endswith("_0")]
        if not unique_ids:
            return {}
        logger.info(f"[{self.market}] Fetching post media for {len(unique_ids)} posts (fallback)...")
        result: dict[str, dict] = {}
        for i in range(0, len(unique_ids), self.BATCH_SIZE):
            chunk = unique_ids[i:i + self.BATCH_SIZE]
            batch = [
                {
                    "method":       "GET",
                    "relative_url": f"{story_id}?fields=attachments{{media,subattachments{{media}}}}",
                }
                for story_id in chunk
            ]
            try:
                resp = requests.post(
                    f"{META_API_BASE}/",
                    data={"access_token": self.access_token, "batch": json.dumps(batch)},
                    timeout=60,
                )
                resp.raise_for_status()
                responses = resp.json()
                for j, item in enumerate(responses):
                    story_id = chunk[j]
                    empty_media = {"image_url": "", "video_url": ""}
                    if not item or item.get("code") != 200:
                        result[story_id] = empty_media
                        continue
                    try:
                        body        = json.loads(item["body"])
                        attachments = body.get("attachments", {}).get("data", [])
                        image_url   = ""
                        video_url   = ""
                        for att in attachments:
                            media = att.get("media", {})
                            if not image_url and media.get("image", {}).get("src"):
                                image_url = media["image"]["src"]
                            if not video_url and media.get("video_id"):
                                vid = media["video_id"]
                                video_url = f"https://www.facebook.com/video/{vid}/"
                            for sub in att.get("subattachments", {}).get("data", []):
                                sub_media = sub.get("media", {})
                                if not image_url and sub_media.get("image", {}).get("src"):
                                    image_url = sub_media["image"]["src"]
                                if not video_url and sub_media.get("video_id"):
                                    vid = sub_media["video_id"]
                                    video_url = f"https://www.facebook.com/video/{vid}/"
                        result[story_id] = {"image_url": image_url, "video_url": video_url}
                    except Exception:
                        result[story_id] = empty_media
                time.sleep(0.5)
            except Exception as e:
                logger.warning(f"[{self.market}] Batch post media lookup failed (chunk {i}): {e}")
                for story_id in chunk:
                    result[story_id] = {"image_url": "", "video_url": ""}
        resolved_img = sum(1 for v in result.values() if v.get("image_url"))
        resolved_vid = sum(1 for v in result.values() if v.get("video_url"))
        logger.info(
            f"[{self.market}] get_post_media: "
            f"{resolved_img}/{len(unique_ids)} images, {resolved_vid}/{len(unique_ids)} videos resolved"
        )
        return result

    # ── Internal batch helpers ────────────────────────────────────────────────

    def _batch_get_creative_info(self, ad_ids: list[str]) -> dict[str, dict]:
        result: dict[str, dict] = {}
        empty = {"page_id": "", "object_story_id": "", "image_url": "", "video_id": ""}
        for i in range(0, len(ad_ids), self.BATCH_SIZE):
            chunk = ad_ids[i:i + self.BATCH_SIZE]
            batch = [
                {
                    "method":       "GET",
                    "relative_url": (
                        f"{ad_id}?fields=creative{{"
                        f"actor_id,"            # Page ID for ALL ad types incl. dark posts
                        f"object_story_spec{{"
                        f"page_id,"
                        f"link_data{{picture}},"
                        f"video_data{{video_id,image_url}}"
                        f"}},"
                        f"object_story_id,"
                        f"image_url,"
                        f"video_id"
                        f"}}"
                    ),
                }
                for ad_id in chunk
            ]
            try:
                resp = requests.post(
                    f"{META_API_BASE}/",
                    data={"access_token": self.access_token, "batch": json.dumps(batch)},
                    timeout=60,
                )
                resp.raise_for_status()
                responses = resp.json()
                page_ids_found = 0
                for j, item in enumerate(responses):
                    ad_id = chunk[j]
                    if not item or item.get("code") != 200:
                        if j == 0 and i == 0:
                            logger.warning(
                                f"[{self.market}] creative API response code={item.get('code') if item else 'None'} "
                                f"body={str(item.get('body', ''))[:300] if item else 'None'}"
                            )
                        result[ad_id] = dict(empty)
                        continue
                    try:
                        body     = json.loads(item["body"])
                        creative = body.get("creative", {})
                        if j == 0 and i == 0:
                            logger.info(f"[{self.market}] creative API sample body: {str(body)[:300]}")
                        oss     = creative.get("object_story_spec", {})
                        # actor_id is the authoritative Page ID for all ad types
                        # (dark posts, video ads, catalog ads all populate actor_id)
                        # object_story_spec.page_id only works for page post boosts
                        page_id = (
                            creative.get("actor_id") or
                            oss.get("page_id", "")
                        )
                        object_story_id = creative.get("object_story_id", "")
                        image_url = (
                            creative.get("image_url", "") or
                            oss.get("video_data", {}).get("image_url", "") or
                            oss.get("link_data", {}).get("picture", "")
                        )
                        raw_vid = (
                            oss.get("video_data", {}).get("video_id") or
                            creative.get("video_id")
                        )
                        video_id = str(raw_vid) if raw_vid else ""
                        result[ad_id] = {
                            "page_id":         str(page_id) if page_id else "",
                            "object_story_id": str(object_story_id) if object_story_id else "",
                            "image_url":       image_url,
                            "video_id":        video_id,
                        }
                        if page_id:
                            page_ids_found += 1
                    except Exception:
                        result[ad_id] = dict(empty)
                if i == 0:
                    logger.info(f"[{self.market}] creative API chunk 0: {page_ids_found}/{len(chunk)} page_ids found")
                time.sleep(0.5)
            except Exception as e:
                logger.warning(f"[{self.market}] Batch creative lookup failed (chunk {i}): {e}")
                for ad_id in chunk:
                    result[ad_id] = dict(empty)

        total_page_ids = sum(1 for v in result.values() if v.get("page_id"))
        logger.info(f"[{self.market}] _batch_get_creative_info: {total_page_ids}/{len(ad_ids)} page_ids resolved")

        # Second pass: CPAS Collection ads — fetch effective_object_story_id
        needs_story = [
            ad_id for ad_id in ad_ids
            if result.get(ad_id, {}).get("page_id")
            and not result.get(ad_id, {}).get("object_story_id")
            and not result.get(ad_id, {}).get("image_url")
        ]
        if needs_story:
            logger.info(f"[{self.market}] Fetching effective_object_story_id for {len(needs_story)} catalog ads...")
            for i in range(0, len(needs_story), self.BATCH_SIZE):
                chunk = needs_story[i:i + self.BATCH_SIZE]
                batch = [
                    {"method": "GET", "relative_url": f"{ad_id}?fields=effective_object_story_id"}
                    for ad_id in chunk
                ]
                try:
                    resp = requests.post(
                        f"{META_API_BASE}/",
                        data={"access_token": self.access_token, "batch": json.dumps(batch)},
                        timeout=60,
                    )
                    resp.raise_for_status()
                    responses = resp.json()
                    found = 0
                    for j, item in enumerate(responses):
                        ad_id = chunk[j]
                        if not item or item.get("code") != 200:
                            continue
                        try:
                            body = json.loads(item["body"])
                            osi  = body.get("effective_object_story_id", "")
                            if osi and "_" in str(osi):
                                result[ad_id]["object_story_id"] = str(osi)
                                found += 1
                        except Exception:
                            pass
                    logger.info(f"[{self.market}] effective_object_story_id pass: {found}/{len(chunk)} resolved")
                    time.sleep(0.5)
                except Exception as e:
                    logger.warning(f"[{self.market}] effective_object_story_id batch failed: {e}")
        return result

    def _batch_get_page_names(self, page_ids: list[str]) -> dict[str, str]:
        result = {}
        if not page_ids:
            return result
        logger.info(f"[{self.market}] _batch_get_page_names: querying {len(page_ids)} page_ids")
        for i in range(0, len(page_ids), self.BATCH_SIZE):
            chunk = page_ids[i:i + self.BATCH_SIZE]
            batch = [{"method": "GET", "relative_url": f"{page_id}?fields=name"} for page_id in chunk]
            try:
                resp = requests.post(
                    f"{META_API_BASE}/",
                    data={"access_token": self.access_token, "batch": json.dumps(batch)},
                    timeout=60,
                )
                resp.raise_for_status()
                responses = resp.json()
                for j, item in enumerate(responses):
                    page_id = chunk[j]
                    if not item or item.get("code") != 200:
                        if j == 0 and i == 0:
                            logger.warning(
                                f"[{self.market}] page name API response code={item.get('code') if item else 'None'} "
                                f"body={str(item.get('body', ''))[:300] if item else 'None'}"
                            )
                        result[page_id] = ""
                        continue
                    try:
                        body = json.loads(item["body"])
                        if j == 0 and i == 0:
                            logger.info(f"[{self.market}] page name API sample body: {str(body)[:200]}")
                        result[page_id] = body.get("name", "")
                    except Exception:
                        result[page_id] = ""
                time.sleep(0.5)
            except Exception as e:
                logger.warning(f"[{self.market}] Batch page_name lookup failed (chunk {i}): {e}")
                for page_id in chunk:
                    result[page_id] = ""
        names_found = sum(1 for v in result.values() if v)
        logger.info(f"[{self.market}] _batch_get_page_names: {names_found}/{len(page_ids)} names resolved")
        return result

    # ── Internal HTTP helpers ─────────────────────────────────────────────────

    def _default_fields(self, level: str) -> list[str]:
        base = ["date_start", "date_stop", "campaign_id", "campaign_name", "adset_id", "adset_name"]
        if level == "ad":
            base += ["ad_id", "ad_name"]
        base += ["impressions", "clicks", "spend", "reach", "frequency", "actions", "action_values"]
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
                logger.error(
                    f"[{self.market}] Meta API error — "
                    f"HTTP {resp.status_code} | code={error_code} | "
                    f"type={error_type} | message={error_msg}"
                )
                if error_code in (4, 17, 32, 613) or resp.status_code in (429, 500, 503):
                    wait = self.RETRY_DELAY * attempt
                    logger.warning(f"[{self.market}] Retrying in {wait}s (attempt {attempt}/{self.MAX_RETRIES})...")
                    time.sleep(wait)
                else:
                    raise
        raise RuntimeError(f"[{self.market}] API call failed after {self.MAX_RETRIES} retries")

    def _paginate(self, url: str, params: dict) -> list[dict]:
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
            current_url = next_url
            current_params = {}
        return all_rows
