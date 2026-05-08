"""
HKTW Meta Auto Report - KOL Report
"""
import os, sys, io, logging
import pandas as pd
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import SP_PATHS, MARKETS
from scripts.meta_api_client import MetaAPIClient
from scripts.kol_transformer import transform, OUTPUT_COLUMNS
from scripts.power_automate_client import PowerAutomateClient
from scripts.account_loader import load_accounts

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DEDUPE_KEYS = ["Ad Account ID", "Ad ID", "Date", "Platform", "Placement"]
SP_FOLDER   = SP_PATHS["kol"]
OUTPUT_FILE = "HKTW_Meta_KOL_Data.xlsx"
SHEET_NAME  = "KOL Data"
FX_SP_FOLDER = SP_PATHS["control_panel"]
FX_FILE     = "KOL_FX_Rates.xlsx"
FX_SHEET    = "FX Rates"

INSIGHT_FIELDS = [
    "account_id", "account_name", "campaign_id", "campaign_name",
    "adset_id", "adset_name", "ad_id", "ad_name",
    "buying_type",
    "impressions", "spend", "actions",
    "video_p25_watched_actions", "video_p50_watched_actions",
    "video_p75_watched_actions", "video_p100_watched_actions",
    "video_thruplay_watched_actions",
    "date_start", "date_stop",
]
BREAKDOWNS = ["publisher_platform", "platform_position"]


def load_fx_rates(pa):
    logger.info(f"Loading FX rates from SharePoint: {FX_FILE}")
    try:
        data = pa.download_bytes(FX_SP_FOLDER, FX_FILE)
    except Exception as e:
        logger.warning(f"FX load failed: {e}")
        return {}
    if data is None:
        logger.warning("FX rate file not found — USD conversion skipped")
        return {}
    try:
        df = pd.read_excel(io.BytesIO(data), sheet_name=FX_SHEET)
        df.columns = [c.strip() for c in df.columns]
        rates = {}
        for _, row in df.iterrows():
            market = str(row.get("Market", "")).strip().upper()
            rate   = row.get("FX Rate (1 USD = ?)", None)
            if market and rate:
                rates[market] = float(rate)
        logger.info(f"FX rates loaded: {rates}")
        return rates
    except Exception as e:
        logger.error(f"Failed to read FX rates: {e}")
        return {}


def fetch_market(market, date_start, date_stop, fx_rates, pa, time_increment=1):
    logger.info(f"[{market}] Fetching KOL data {date_start} → {date_stop}")
    accounts = load_accounts(market, pa, report_type=None)
    if not accounts:
        logger.warning(f"[{market}] No accounts found")
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    client   = MetaAPIClient(market)
    all_rows = []
    for acct in accounts:
        try:
            rows = client.get_insights(
                ad_account_id=acct["id"], date_start=date_start, date_stop=date_stop,
                level="ad", fields=INSIGHT_FIELDS, breakdowns=BREAKDOWNS,
                time_increment=time_increment,
            )
            all_rows.extend(rows)
            if rows: logger.info(f"[{market}] {acct['name']}: {len(rows)} rows")
        except Exception as e:
            if "3018" in str(e):
                logger.warning(f"[{market}] Skipping {acct['id']} (beyond 37-month limit)")
            else:
                logger.error(f"[{market}] Error {acct['id']}: {e}")

    if not all_rows:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    unique_ad_ids = list({str(r.get("ad_id","")) for r in all_rows if r.get("ad_id")})
    story_id_map = {}; page_name_map = {}; creative_info_map = {}
    campaign_map = {}

    try:
        creative_info_map = client.get_creative_info_for_ads(unique_ad_ids)
        for ad_id, info in creative_info_map.items():
            osi = info.get("object_story_id","")
            if osi and "_" in str(osi): story_id_map[ad_id] = osi
            elif info.get("page_id"): story_id_map[ad_id] = f"{info['page_id']}_0"
        page_name_map = client.get_page_names_for_ads(unique_ad_ids, story_id_map=story_id_map)
        missing_media = [
            ad_id for ad_id in unique_ad_ids
            if not creative_info_map.get(ad_id,{}).get("image_url")
            and not creative_info_map.get(ad_id,{}).get("video_id")
            and story_id_map.get(ad_id,"")
        ]
        if missing_media:
            msi = list({story_id_map[a] for a in missing_media if story_id_map.get(a)})
            post_media = client.get_post_media(msi)
            for ad_id in missing_media:
                sid = story_id_map.get(ad_id,"")
                if sid and sid in post_media:
                    m = post_media[sid]
                    if m.get("image_url"): creative_info_map[ad_id]["image_url"] = m["image_url"]
                    if m.get("video_url"):
                        key = f"__post__{sid}"
                        creative_info_map[ad_id]["video_id"] = key
                        video_url_map[key] = m["video_url"]
        unique_cids = list({str(r.get("campaign_id","")) for r in all_rows if r.get("campaign_id")})
        campaign_map = client.get_campaign_info(unique_cids)
    except Exception as e:
        logger.warning(f"[{market}] Creative/campaign lookup failed: {e}")

    return transform(
        all_rows, fx_rates=fx_rates, page_name_map=page_name_map,
        creative_info_map=creative_info_map, video_url_map=None,
        story_id_map=story_id_map, campaign_map=campaign_map,
    )


def _migrate_existing_schema(df):
    """Bring older SharePoint file up to current OUTPUT_COLUMNS schema."""
    from scripts.kol_transformer import get_quarter, get_duration_group
    rename_map = {}  # no column renames needed
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})
    for col in OUTPUT_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    empty_q = df["Quarter"].isna() | (df["Quarter"].astype(str).str.strip() == "")
    if empty_q.any():
        dates = pd.to_datetime(df.loc[empty_q, "Date"], errors="coerce")
        df.loc[empty_q, "Quarter"] = dates.apply(get_quarter)
    empty_d = df["Duration Group"].isna() | (df["Duration Group"].astype(str).str.strip() == "")
    if empty_d.any() and "Creative Format" in df.columns:
        df.loc[empty_d, "Duration Group"] = df.loc[empty_d, "Creative Format"].fillna("").apply(get_duration_group)
    return df[OUTPUT_COLUMNS]


def load_existing(pa):
    data = pa.download_bytes(SP_FOLDER, OUTPUT_FILE)
    if data is None:
        logger.info("No existing file — starting fresh")
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    try:
        df = pd.read_excel(io.BytesIO(data), sheet_name=SHEET_NAME, dtype=str)
        logger.info(f"Loaded {len(df)} existing rows")
        df = _migrate_existing_schema(df)
        return df
    except Exception as e:
        logger.error(f"Failed to read existing: {e}")
        return pd.DataFrame(columns=OUTPUT_COLUMNS)


def merge_and_deduplicate(existing, new_data):
    if new_data.empty: return existing
    combined = pd.concat([existing, new_data], ignore_index=True)
    for col in DEDUPE_KEYS:
        if col in combined.columns:
            combined[col] = combined[col].astype(str).str.strip()
    before = len(combined)
    combined = combined.drop_duplicates(subset=DEDUPE_KEYS, keep="last")
    logger.info(f"Dedup: {before} → {len(combined)} rows ({before-len(combined)} removed)")
    return combined.reset_index(drop=True)


def save_to_excel(df):
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, sheet_name=SHEET_NAME, index=False)
    return buf.getvalue()


def main():
    market         = os.environ.get("MARKET", "ALL").upper()
    date_start     = os.environ.get("DATE_START")
    date_stop      = os.environ.get("DATE_STOP")
    time_increment = os.environ.get("TIME_INCREMENT", "1")
    if time_increment not in ("1","monthly"): time_increment = "1"
    if not date_start or not date_stop:
        raise ValueError("DATE_START and DATE_STOP required")
    markets_to_run = list(MARKETS.keys()) if market == "ALL" else [market]
    logger.info(f"KOL Report | {markets_to_run} | {date_start} → {date_stop}")
    pa       = PowerAutomateClient()
    fx_rates = load_fx_rates(pa)
    new_frames = []
    for m in markets_to_run:
        df_m = fetch_market(m, date_start, date_stop, fx_rates, pa, time_increment)
        if not df_m.empty: new_frames.append(df_m)
    new_data = pd.concat(new_frames, ignore_index=True) if new_frames else pd.DataFrame(columns=OUTPUT_COLUMNS)
    logger.info(f"Total new rows: {len(new_data)}")
    # ── SharePoint accumulation skipped (upload disabled) ──
    merged      = new_data
    excel_bytes = save_to_excel(merged)

    # ── Save timestamped artifact locally ──
    from datetime import datetime as _dt
    mkt_str   = market if market != "ALL" else "HKTW"
    timestamp = _dt.utcnow().strftime("%Y%m%d_%H%M")
    artifact_dir  = os.environ.get("ARTIFACT_DIR", "report_output")
    os.makedirs(artifact_dir, exist_ok=True)
    artifact_name = f"KOL_{mkt_str}_{date_start}_{date_stop}_{timestamp}.xlsx"
    artifact_path = os.path.join(artifact_dir, artifact_name)
    with open(artifact_path, "wb") as f:
        f.write(excel_bytes)
    logger.info(f"Artifact saved: {artifact_path} ({len(merged)} rows)")

    # ── SharePoint upload temporarily disabled ──
    # pa.upload_bytes(excel_bytes, SP_FOLDER, OUTPUT_FILE)
    logger.info("KOL Report completed (SharePoint upload skipped).")

if __name__ == "__main__":
    main()
