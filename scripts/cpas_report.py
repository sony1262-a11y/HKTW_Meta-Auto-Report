"""
HKTW Meta Auto Report - CPAS Report
Fetches Meta CPAS ad data, transforms, accumulates, and uploads to SharePoint.

Triggered by GitHub Actions workflow_dispatch with:
  MARKET     = HK | TW | ALL
  DATE_START = YYYY-MM-DD
  DATE_STOP  = YYYY-MM-DD
"""
import os
import sys
import io
import logging
import pandas as pd
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import SP_PATHS, SP_CONTROL_FILES, MARKETS
from scripts.meta_api_client import MetaAPIClient
from scripts.cpas_transformer import transform, OUTPUT_COLUMNS
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

CPAS_KEYWORD  = "CPAS"           # Ad accounts must contain this keyword
DEDUPE_KEYS   = ["Account name", "Ad name", "Date"]
SP_FOLDER     = SP_PATHS["cpas"]
OUTPUT_FILE   = "HKTW_Meta_CPAS_Data.xlsx"
SHEET_NAME    = "CPAS Data"

# Meta insights fields to request
INSIGHT_FIELDS = [
    "account_name", "ad_id",
    "campaign_name", "adset_name", "ad_name",
    "spend", "reach", "frequency", "impressions",
    "cpm", "cpc", "ctr",
    "actions", "action_values", "purchase_roas",
    "catalog_segment_actions", "catalog_segment_value",
    "date_start", "date_stop",
]


# ─────────────────────────────────────────────────────────────────────────────
# Per-market fetch
# ─────────────────────────────────────────────────────────────────────────────

def fetch_market(market: str, date_start: str, date_stop: str, pa: PowerAutomateClient, time_increment: str | int = 1) -> pd.DataFrame:
    """Fetch all CPAS ad accounts for one market and return transformed DataFrame."""
    logger.info(f"[{market}] Fetching CPAS data {date_start} → {date_stop} (time_increment={time_increment})")

    accounts = load_accounts(market, pa, report_type="CPAS")

    if not accounts:
        logger.warning(f"[{market}] No CPAS accounts found in Control Panel — skipping")
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    client   = MetaAPIClient(market)
    all_rows = []

    for acct in accounts:
        acct_id   = acct["id"]
        acct_name = acct["name"]
        logger.info(f"[{market}]   → {acct_name} ({acct_id})")

        try:
            rows = client.get_insights(
                ad_account_id  = acct_id,
                date_start     = date_start,
                date_stop      = date_stop,
                level          = "ad",
                fields         = INSIGHT_FIELDS,
                time_increment = time_increment,
            )
            all_rows.extend(rows)
            logger.info(f"[{market}]     {len(rows)} rows fetched")
        except Exception as e:
            logger.error(f"[{market}]     Error fetching {acct_id}: {e}")
            continue

    if not all_rows:
        logger.warning(f"[{market}] No data returned")
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    # Creative info lookup (Post URL, Image URL, Video URL)
    unique_ad_ids = list({str(r.get("ad_id", "")) for r in all_rows if r.get("ad_id")})
    story_id_map: dict[str, str] = {}

    creative_info_map: dict[str, dict] = {}
    video_url_map: dict[str, str] = {}

    try:
        creative_info_map = client.get_creative_info_for_ads(unique_ad_ids)
        # Supplement story_id_map from creative object_story_id
        for ad_id, info in creative_info_map.items():
            if ad_id not in story_id_map:
                osi = info.get("object_story_id", "")
                if osi and "_" in str(osi):
                    story_id_map[ad_id] = osi
                elif info.get("page_id"):
                    story_id_map[ad_id] = f"{info['page_id']}_0"
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
    except Exception as e:
        logger.warning(f"[{market}] Creative lookup failed — creative fields will be blank: {e}")

    return transform(all_rows, creative_info_map=creative_info_map, video_url_map=video_url_map, story_id_map=story_id_map)


# ─────────────────────────────────────────────────────────────────────────────
# Accumulation logic
# ─────────────────────────────────────────────────────────────────────────────

def load_existing(pa: PowerAutomateClient) -> pd.DataFrame:
    """Download existing accumulated file from SharePoint. Returns empty df if not found."""
    logger.info(f"Downloading existing data from SharePoint: {OUTPUT_FILE}")
    data = pa.download_bytes(SP_FOLDER, OUTPUT_FILE)
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


def merge_and_deduplicate(existing: pd.DataFrame, new_data: pd.DataFrame) -> pd.DataFrame:
    """
    Merge new data into existing, deduplicate on DEDUPE_KEYS.
    New data wins on conflict (keeps last occurrence).
    """
    if new_data.empty:
        return existing

    combined = pd.concat([existing, new_data], ignore_index=True)

    # Normalise key columns before dedup
    for col in DEDUPE_KEYS:
        if col in combined.columns:
            combined[col] = combined[col].astype(str).str.strip()

    before = len(combined)
    combined = combined.drop_duplicates(subset=DEDUPE_KEYS, keep="last")
    after  = len(combined)
    logger.info(f"Dedup: {before} → {after} rows ({before - after} duplicates removed)")

    return combined.reset_index(drop=True)


def save_to_excel(df: pd.DataFrame) -> bytes:
    """Serialize DataFrame to Excel bytes."""
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
    # Allow "1" or "monthly"; default to daily
    if time_increment not in ("1", "monthly"):
        time_increment = "1"

    if not date_start or not date_stop:
        raise ValueError("DATE_START and DATE_STOP environment variables are required")

    if market == "ALL":
        markets_to_run = list(MARKETS.keys())
    elif market in MARKETS:
        markets_to_run = [market]
    else:
        raise ValueError(f"Unknown MARKET value: {market}")

    logger.info(f"CPAS Report | Markets: {markets_to_run} | {date_start} → {date_stop} | time_increment={time_increment}")

    pa = PowerAutomateClient()

    new_frames = []
    for m in markets_to_run:
        df_m = fetch_market(m, date_start, date_stop, pa, time_increment=time_increment)
        if not df_m.empty:
            new_frames.append(df_m)

    new_data = pd.concat(new_frames, ignore_index=True) if new_frames else pd.DataFrame(columns=OUTPUT_COLUMNS)
    logger.info(f"Total new rows fetched: {len(new_data)}")

    existing = load_existing(pa)
    merged   = merge_and_deduplicate(existing, new_data)

    logger.info(f"Uploading {len(merged)} rows → {SP_FOLDER}/{OUTPUT_FILE}")
    excel_bytes = save_to_excel(merged)
    pa.upload_bytes(excel_bytes, SP_FOLDER, OUTPUT_FILE)

    logger.info("CPAS Report completed successfully.")
    _write_summary(markets_to_run, date_start, date_stop, len(new_data), len(merged))


def _write_summary(markets, date_start, date_stop, new_rows, total_rows):
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    lines = [
        "## CPAS Report — Completed",
        "",
        f"| | |",
        f"|---|---|",
        f"| Markets | {', '.join(markets)} |",
        f"| Date range | {date_start} → {date_stop} |",
        f"| New rows fetched | {new_rows:,} |",
        f"| Total rows in file | {total_rows:,} |",
        f"| Run time (UTC) | {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} |",
    ]
    with open(path, "a") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
