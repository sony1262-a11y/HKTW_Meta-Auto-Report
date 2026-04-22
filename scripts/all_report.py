"""
HKTW Meta Auto Report - All Accounts Report
Fetches ALL Meta ad accounts (CPAS, Brand, EC, KOL) for HK & TW,
transforms with unified schema, accumulates, and uploads to SharePoint.

Triggered by GitHub Actions workflow_dispatch with:
  MARKET         = HK | TW | ALL
  DATE_START     = YYYY-MM-DD
  DATE_STOP      = YYYY-MM-DD
  TIME_INCREMENT = 1 (daily) | monthly
  BREAKDOWN      = platform_placement | age_gender
"""
import os
import sys
import io
import logging
import pandas as pd
from datetime import datetime, date
from dateutil.relativedelta import relativedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import SP_PATHS, SP_CONTROL_FILES, MARKETS
from scripts.meta_api_client import MetaAPIClient
from scripts.all_transformer import transform, OUTPUT_COLUMNS
from scripts.power_automate_client import PowerAutomateClient
from scripts.account_loader import load_accounts

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

DEDUPE_KEYS = ["Ad Account ID", "Ad ID", "Date", "Platform", "Placement"]
SP_FOLDER   = SP_PATHS["all"]
SHEET_NAME  = "All Meta Data"

# FX rates
FX_SP_FOLDER = SP_PATHS["control_panel"]
FX_FILE      = "KOL_FX_Rates.xlsx"
FX_SHEET     = "FX Rates"

# Meta insights fields
INSIGHT_FIELDS = [
    "account_id", "account_name",
    "campaign_id", "campaign_name",
    "adset_id", "adset_name",
    "ad_id", "ad_name",
    "spend", "reach", "frequency", "impressions",
    "cpm", "cpc", "ctr",
    "actions",
    "catalog_segment_actions", "catalog_segment_value",
    "purchase_roas",
    "date_start", "date_stop",
]

# Breakdown options
BREAKDOWN_MAP = {
    "none":               [],
    "platform_placement": ["publisher_platform", "platform_position"],
    "age_gender":         ["age", "gender"],
}

# DEDUPE_KEYS for age/gender breakdown (no Platform/Placement)
DEDUPE_KEYS_AGE_GENDER = ["Ad Account ID", "Ad ID", "Date", "Age", "Gender"]
DEDUPE_KEYS_NONE       = ["Ad Account ID", "Ad ID", "Date"]


# ─────────────────────────────────────────────────────────────────────────────
# Date range chunking
# ─────────────────────────────────────────────────────────────────────────────

def monthly_chunks(date_start: str, date_stop: str) -> list[tuple[str, str]]:
    """
    Split a date range into monthly chunks.
    e.g. 2025-07-01 → 2025-09-30 → [(2025-07-01, 2025-07-31), (2025-08-01, 2025-08-31), (2025-09-01, 2025-09-30)]
    Returns a single chunk if range is within one calendar month.
    """
    start = date.fromisoformat(date_start)
    stop  = date.fromisoformat(date_stop)

    # Same month — no split needed
    if start.year == stop.year and start.month == stop.month:
        return [(date_start, date_stop)]

    chunks = []
    cur = start
    while cur <= stop:
        # Last day of current month
        month_end = (cur + relativedelta(months=1)) - relativedelta(days=1)
        chunk_end = min(month_end, stop)
        chunks.append((cur.isoformat(), chunk_end.isoformat()))
        cur = chunk_end + relativedelta(days=1)

    return chunks

def load_fx_rates(pa: PowerAutomateClient) -> dict[str, float]:
    logger.info(f"Loading FX rates from SharePoint: {FX_FILE}")
    data = pa.download_bytes(FX_SP_FOLDER, FX_FILE)
    if data is None:
        logger.warning("FX rate file not found — USD conversion will be skipped")
        return {}
    try:
        df = pd.read_excel(io.BytesIO(data), sheet_name=FX_SHEET)
        rates = {}
        for _, row in df.iterrows():
            market = str(row.get("Market", "")).strip().upper()
            rate   = row.get("FX Rate (1 USD = ?)", None)
            if market and rate:
                rates[market] = float(rate)
        logger.info(f"FX rates loaded: {rates}")
        return rates
    except Exception as e:
        logger.error(f"Failed to load FX rates: {e}")
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# Per-market fetch
# ─────────────────────────────────────────────────────────────────────────────

def fetch_market(
    market: str,
    date_start: str,
    date_stop: str,
    fx_rates: dict[str, float],
    pa: PowerAutomateClient,
    time_increment: str | int = 1,
    breakdown: str = "platform_placement",
) -> pd.DataFrame:
    """Fetch all ad accounts for one market and return transformed DataFrame."""
    breakdowns = BREAKDOWN_MAP.get(breakdown) or None  # empty list → None → no breakdown param
    logger.info(
        f"[{market}] Fetching All Meta data {date_start} → {date_stop} "
        f"(time_increment={time_increment}, breakdown={breakdown})"
    )

    accounts = load_accounts(market, pa, report_type=None)  # all types

    if not accounts:
        logger.warning(f"[{market}] No accounts found — skipping")
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    logger.info(f"[{market}] {len(accounts)} accounts loaded")
    client   = MetaAPIClient(market)
    all_rows = []

    # Split into monthly chunks to avoid Meta 500 "too much data" errors
    chunks = monthly_chunks(date_start, date_stop)
    if len(chunks) > 1:
        logger.info(f"[{market}] Date range spans {len(chunks)} months — fetching month by month")

    for acct in accounts:
        acct_id   = acct["id"]
        acct_name = acct["name"]
        acct_rows = []
        for chunk_start, chunk_end in chunks:
            try:
                rows = client.get_insights(
                    ad_account_id  = acct_id,
                    date_start     = chunk_start,
                    date_stop      = chunk_end,
                    level          = "ad",
                    fields         = INSIGHT_FIELDS,
                    breakdowns     = breakdowns,
                    time_increment = time_increment,
                )
                acct_rows.extend(rows)
            except Exception as e:
                logger.error(f"[{market}] Error fetching {acct_id} ({acct_name}) [{chunk_start}~{chunk_end}]: {e}")
                continue
        all_rows.extend(acct_rows)
        if acct_rows:
            logger.info(f"[{market}] {acct_name}: {len(acct_rows)} rows")

    if not all_rows:
        logger.warning(f"[{market}] No data returned")
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    # Creative info + page name lookup
    unique_ad_ids = list({str(r.get("ad_id", "")) for r in all_rows if r.get("ad_id")})
    story_id_map: dict[str, str] = {}
    page_name_map: dict[str, str] = {}
    creative_info_map: dict[str, dict] = {}
    video_url_map: dict[str, str] = {}

    try:
        creative_info_map = client.get_creative_info_for_ads(unique_ad_ids)
        for ad_id, info in creative_info_map.items():
            osi = info.get("object_story_id", "")
            if osi and "_" in str(osi):
                story_id_map[ad_id] = osi
            elif info.get("page_id"):
                story_id_map[ad_id] = f"{info['page_id']}_0"

        page_name_map = client.get_page_names_for_ads(unique_ad_ids, story_id_map=story_id_map)

        video_ids = list({info["video_id"] for info in creative_info_map.values() if info.get("video_id")})
        if video_ids:
            video_url_map = client.get_video_urls(video_ids)

        # Fallback: for ads with no image_url and no video_id, query post attachments
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
        logger.warning(f"[{market}] Creative/page lookup failed — fields will be blank: {e}")

    df = transform(
        all_rows,
        fx_rates=fx_rates,
        page_name_map=page_name_map,
        creative_info_map=creative_info_map,
        video_url_map=video_url_map,
        story_id_map=story_id_map,
    )

    # For age/gender breakdown, rename breakdown columns
    if breakdown == "age_gender":
        if "Platform" in df.columns:
            df = df.rename(columns={"Platform": "Age", "Placement": "Gender"})

    return df


# ─────────────────────────────────────────────────────────────────────────────
# Accumulation logic
# ─────────────────────────────────────────────────────────────────────────────

def _output_filename(time_increment: str | int, breakdown: str) -> str:
    ti = "monthly" if str(time_increment) == "monthly" else "daily"
    bd = breakdown if breakdown in ("none", "age_gender", "platform_placement") else "platform_placement"
    return f"HKTW_Meta_All_{ti}_{bd}.xlsx"


def load_existing(pa: PowerAutomateClient, output_file: str) -> pd.DataFrame:
    logger.info(f"Downloading existing data: {output_file}")
    data = pa.download_bytes(SP_FOLDER, output_file)
    if data is None:
        logger.info("No existing file found — starting fresh")
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    try:
        df = pd.read_excel(io.BytesIO(data), sheet_name=SHEET_NAME, dtype=str)
        logger.info(f"Loaded {len(df)} existing rows")
        return df
    except Exception as e:
        logger.error(f"Failed to read existing file: {e} — starting fresh")
        return pd.DataFrame(columns=OUTPUT_COLUMNS)


def _get_dedupe_keys(breakdown: str) -> list[str]:
    if breakdown == "age_gender":
        return DEDUPE_KEYS_AGE_GENDER
    if breakdown == "none":
        return DEDUPE_KEYS_NONE
    return DEDUPE_KEYS


def merge_and_deduplicate(
    existing: pd.DataFrame,
    new_data: pd.DataFrame,
    breakdown: str = "platform_placement",
) -> pd.DataFrame:
    if new_data.empty:
        return existing

    dedupe_keys = _get_dedupe_keys(breakdown)
    combined    = pd.concat([existing, new_data], ignore_index=True)

    for col in dedupe_keys:
        if col in combined.columns:
            combined[col] = combined[col].astype(str).str.strip()

    before   = len(combined)
    combined = combined.drop_duplicates(subset=dedupe_keys, keep="last")
    after    = len(combined)
    logger.info(f"Dedup: {before} → {after} rows ({before - after} removed)")
    return combined.reset_index(drop=True)


def save_to_excel(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name=SHEET_NAME, index=False)
    return buf.getvalue()


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    market         = os.environ.get("MARKET", "ALL").upper()
    date_start     = os.environ.get("DATE_START")
    date_stop      = os.environ.get("DATE_STOP")
    time_increment = os.environ.get("TIME_INCREMENT", "1")
    breakdown      = os.environ.get("BREAKDOWN", "platform_placement")

    if time_increment not in ("1", "monthly"):
        time_increment = "1"
    if breakdown not in ("none", "platform_placement", "age_gender"):
        breakdown = "platform_placement"

    if not date_start or not date_stop:
        raise ValueError("DATE_START and DATE_STOP environment variables are required")

    markets_to_run = list(MARKETS.keys()) if market == "ALL" else [market]
    output_file    = _output_filename(time_increment, breakdown)

    logger.info(
        f"All Meta Report | Markets: {markets_to_run} | {date_start} → {date_stop} | "
        f"time_increment={time_increment} | breakdown={breakdown} | file={output_file}"
    )

    pa       = PowerAutomateClient()
    fx_rates = load_fx_rates(pa)

    new_frames = []
    for m in markets_to_run:
        df_m = fetch_market(m, date_start, date_stop, fx_rates, pa, time_increment, breakdown)
        if not df_m.empty:
            new_frames.append(df_m)

    new_data = pd.concat(new_frames, ignore_index=True) if new_frames else pd.DataFrame(columns=OUTPUT_COLUMNS)
    logger.info(f"Total new rows fetched: {len(new_data)}")

    existing = load_existing(pa, output_file)
    merged   = merge_and_deduplicate(existing, new_data, breakdown)

    logger.info(f"Uploading {len(merged)} rows → {SP_FOLDER}/{output_file}")
    pa.upload_bytes(save_to_excel(merged), SP_FOLDER, output_file)

    logger.info("All Meta Report completed successfully.")
    _write_summary(markets_to_run, date_start, date_stop, time_increment, breakdown, len(new_data), len(merged))


def _write_summary(markets, date_start, date_stop, time_increment, breakdown, new_rows, total_rows):
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    lines = [
        "## All Meta Report — Completed",
        f"| Field | Value |",
        f"|-------|-------|",
        f"| Markets | {', '.join(markets)} |",
        f"| Date range | {date_start} → {date_stop} |",
        f"| Time increment | {time_increment} |",
        f"| Breakdown | {breakdown} |",
        f"| New rows | {new_rows} |",
        f"| Total rows | {total_rows} |",
    ]
    with open(path, "a") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
