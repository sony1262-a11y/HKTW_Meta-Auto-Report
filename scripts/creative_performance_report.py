"""
HKTW Meta Auto Report - Creative Performance Report
Fetches ALL Meta ad accounts (CPAS, Brand, EC, KOL) for HK & TW,
produces a report with full media metrics + direct downloadable URLs:
  - Post URL
  - Creative Image URL  (direct CDN, long-lived)
  - Creative Video URL  (direct .mp4 source URL, valid same day)

Output: downloaded as GitHub Actions artifact (no SharePoint upload).
Note: Video source URLs expire within hours — share report on same day.

Triggered by GitHub Actions workflow_dispatch with:
  MARKET         = HK | TW | ALL
  DATE_START     = YYYY-MM-DD
  DATE_STOP      = YYYY-MM-DD
  TIME_INCREMENT = 1 (daily) | monthly
  BREAKDOWN      = none | platform_placement | age_gender
"""
import os
import sys
import io
import logging
import pandas as pd
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import SP_PATHS, MARKETS
from scripts.meta_api_client import MetaAPIClient
from scripts.all_transformer import transform, OUTPUT_COLUMNS
from scripts.all_report import (
    INSIGHT_FIELDS, BREAKDOWN_MAP,
    load_fx_rates, _get_dedupe_keys,
)
from scripts.power_automate_client import PowerAutomateClient
from scripts.account_loader import load_accounts

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

OUTPUT_DIR  = os.environ.get("OUTPUT_DIR", "creative_output")
SHEET_NAME  = "Creative Performance"


# ─────────────────────────────────────────────────────────────────────────────
# Per-market fetch (same as all_report but uses source URL for video)
# ─────────────────────────────────────────────────────────────────────────────

def fetch_market(
    market: str,
    date_start: str,
    date_stop: str,
    fx_rates: dict,
    pa: PowerAutomateClient,
    time_increment: str | int = 1,
    breakdown: str = "none",
) -> pd.DataFrame:

    breakdowns = BREAKDOWN_MAP.get(breakdown) or None
    logger.info(
        f"[{market}] Fetching Creative Performance {date_start} → {date_stop} "
        f"(time_increment={time_increment}, breakdown={breakdown})"
    )

    accounts = load_accounts(market, pa, report_type=None)
    if not accounts:
        logger.warning(f"[{market}] No accounts found")
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    logger.info(f"[{market}] {len(accounts)} accounts loaded")
    client   = MetaAPIClient(market)
    all_rows = []

    for acct in accounts:
        acct_id   = acct["id"]
        acct_name = acct["name"]
        try:
            rows = client.get_insights(
                ad_account_id  = acct_id,
                date_start     = date_start,
                date_stop      = date_stop,
                level          = "ad",
                fields         = INSIGHT_FIELDS,
                breakdowns     = breakdowns,
                time_increment = time_increment,
            )
            all_rows.extend(rows)
            logger.info(f"[{market}] {acct_name}: {len(rows)} rows")
        except Exception as e:
            logger.error(f"[{market}] Error {acct_id} ({acct_name}): {e}")

    if not all_rows:
        logger.warning(f"[{market}] No data returned")
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    unique_ad_ids     = list({str(r.get("ad_id", "")) for r in all_rows if r.get("ad_id")})
    story_id_map:     dict[str, str] = {}
    page_name_map:    dict[str, str] = {}
    creative_info_map: dict[str, dict] = {}
    video_url_map:    dict[str, str] = {}

    try:
        creative_info_map = client.get_creative_info_for_ads(unique_ad_ids)
        for ad_id, info in creative_info_map.items():
            osi = info.get("object_story_id", "")
            if osi and "_" in str(osi):
                story_id_map[ad_id] = osi
            elif info.get("page_id"):
                story_id_map[ad_id] = f"{info['page_id']}_0"

        page_name_map = client.get_page_names_for_ads(unique_ad_ids, story_id_map=story_id_map)

        # ── Video: use source URL (direct downloadable CDN) ──
        video_ids = list({info["video_id"] for info in creative_info_map.values()
                          if info.get("video_id") and not info["video_id"].startswith("__post__")})
        if video_ids:
            video_url_map = client.get_video_source_urls(video_ids)

        # ── Fallback: post attachments for ads missing both image and video ──
        missing_media = [
            ad_id for ad_id in unique_ad_ids
            if not creative_info_map.get(ad_id, {}).get("image_url")
            and not creative_info_map.get(ad_id, {}).get("video_id")
            and story_id_map.get(ad_id, "")
        ]
        if missing_media:
            missing_story_ids = list({story_id_map[a] for a in missing_media if story_id_map.get(a)})
            post_media = client.get_post_media(missing_story_ids)
            for ad_id in missing_media:
                sid = story_id_map.get(ad_id, "")
                if sid and sid in post_media:
                    m = post_media[sid]
                    if m.get("image_url"):
                        creative_info_map[ad_id]["image_url"] = m["image_url"]
                    if m.get("video_url"):
                        key = f"__post__{sid}"
                        creative_info_map[ad_id]["video_id"] = key
                        video_url_map[key] = m["video_url"]

        logger.info(
            f"[{market}] Pages: {sum(1 for v in page_name_map.values() if v)}/{len(unique_ad_ids)} | "
            f"Images: {sum(1 for v in creative_info_map.values() if v.get('image_url'))}/{len(unique_ad_ids)} | "
            f"Videos: {sum(1 for v in video_url_map.values() if v)}/{len(video_ids) if video_ids else 0}"
        )

    except Exception as e:
        import traceback
        logger.warning(f"[{market}] Creative lookup failed: {e}\n{traceback.format_exc()}")

    df = transform(
        all_rows,
        fx_rates=fx_rates,
        page_name_map=page_name_map,
        creative_info_map=creative_info_map,
        video_url_map=video_url_map,
        story_id_map=story_id_map,
    )

    if breakdown == "age_gender" and "Platform" in df.columns:
        df = df.rename(columns={"Platform": "Age", "Placement": "Gender"})

    return df


# ─────────────────────────────────────────────────────────────────────────────
# Summary Excel
# ─────────────────────────────────────────────────────────────────────────────

def build_summary(df: pd.DataFrame) -> pd.DataFrame:
    """
    Produce a per-ad summary showing creative asset availability.
    One row per unique Ad ID.
    """
    if df.empty:
        return pd.DataFrame()

    summary_cols = [
        "Market", "Ad Account Name", "Brand", "Objective", "Campaign name",
        "Ad ID", "Ad name", "Date",
        "Post URL", "Creative Image URL", "Creative Video URL",
        "Amount spent", "Impressions", "Reach",
        "Link Clicks", "3s Views", "Thruplay",
    ]
    available = [c for c in summary_cols if c in df.columns]
    summary   = df[available].copy()

    # Status column
    def asset_status(row):
        has_img = bool(row.get("Creative Image URL", ""))
        has_vid = bool(row.get("Creative Video URL", ""))
        if has_img and has_vid:
            return "image + video"
        if has_img:
            return "image only"
        if has_vid:
            return "video only"
        return "no asset"

    summary["Asset Status"] = summary.apply(asset_status, axis=1)
    return summary.reset_index(drop=True)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    market         = os.environ.get("MARKET", "ALL").upper()
    date_start     = os.environ.get("DATE_START")
    date_stop      = os.environ.get("DATE_STOP")
    time_increment = os.environ.get("TIME_INCREMENT", "1")
    breakdown      = os.environ.get("BREAKDOWN", "none")

    if time_increment not in ("1", "monthly"):
        time_increment = "1"
    if breakdown not in ("none", "platform_placement", "age_gender"):
        breakdown = "none"

    if not date_start or not date_stop:
        raise ValueError("DATE_START and DATE_STOP are required")

    markets_to_run = list(MARKETS.keys()) if market == "ALL" else [market]

    logger.info(
        f"Creative Performance Report | Markets: {markets_to_run} | "
        f"{date_start} → {date_stop} | time_increment={time_increment} | breakdown={breakdown}"
    )
    logger.info("Note: Video source URLs expire within hours — share report on same day.")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    pa       = PowerAutomateClient()
    fx_rates = load_fx_rates(pa)

    all_frames = []
    for m in markets_to_run:
        df_m = fetch_market(m, date_start, date_stop, fx_rates, pa, time_increment, breakdown)
        if not df_m.empty:
            all_frames.append(df_m)

    if not all_frames:
        logger.error("No data fetched — aborting")
        sys.exit(1)

    df_all = pd.concat(all_frames, ignore_index=True)
    logger.info(f"Total rows: {len(df_all)}")

    # ── Asset coverage stats ──
    has_image = (df_all["Creative Image URL"].notna() & (df_all["Creative Image URL"] != "")).sum()
    has_video = (df_all["Creative Video URL"].notna() & (df_all["Creative Video URL"] != "")).sum()
    has_post  = (df_all["Post URL"].notna() & (df_all["Post URL"] != "")).sum()
    logger.info(f"Asset coverage → Post URL: {has_post}/{len(df_all)} | Image: {has_image}/{len(df_all)} | Video: {has_video}/{len(df_all)}")

    # ── Summary ──
    df_summary = build_summary(df_all)

    # ── Save to Excel (two sheets) ──
    timestamp   = datetime.utcnow().strftime("%Y%m%d_%H%M")
    output_file = os.path.join(OUTPUT_DIR, f"Creative_Performance_{date_start}_{date_stop}_{timestamp}.xlsx")

    with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
        df_all.to_excel(writer, sheet_name="Full Data", index=False)
        df_summary.to_excel(writer, sheet_name="Asset Summary", index=False)

    logger.info(f"Saved: {output_file}")

    # ── GitHub step summary ──
    _write_step_summary(markets_to_run, date_start, date_stop, time_increment, breakdown,
                        len(df_all), has_image, has_video, has_post)


def _write_step_summary(markets, date_start, date_stop, time_increment, breakdown,
                        total_rows, has_image, has_video, has_post):
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    lines = [
        "## Creative Performance Report — Completed",
        f"| Field | Value |",
        f"|-------|-------|",
        f"| Markets | {', '.join(markets)} |",
        f"| Date range | {date_start} → {date_stop} |",
        f"| Time increment | {time_increment} |",
        f"| Breakdown | {breakdown} |",
        f"| Total rows | {total_rows} |",
        f"| Post URL | {has_post}/{total_rows} |",
        f"| Creative Image URL | {has_image}/{total_rows} |",
        f"| Creative Video URL | {has_video}/{total_rows} |",
        f"",
        f"> Video source URLs expire within hours. Share report on same day.",
    ]
    with open(path, "a") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
