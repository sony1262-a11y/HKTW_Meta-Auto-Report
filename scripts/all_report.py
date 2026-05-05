"""HKTW Meta Auto Report - All Accounts Report"""
import os, sys, io, logging
import pandas as pd
from datetime import datetime, date
from dateutil.relativedelta import relativedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import SP_PATHS, SP_CONTROL_FILES, MARKETS
from scripts.meta_api_client import MetaAPIClient
from scripts.all_transformer import transform, OUTPUT_COLUMNS
from scripts.power_automate_client import PowerAutomateClient
from scripts.account_loader import load_accounts

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DEDUPE_KEYS            = ["Ad Account ID", "Ad ID", "Date", "Platform", "Placement"]
DEDUPE_KEYS_AGE_GENDER = ["Ad Account ID", "Ad ID", "Date", "Age", "Gender"]
DEDUPE_KEYS_NONE       = ["Ad Account ID", "Ad ID", "Date"]
SP_FOLDER              = SP_PATHS["all"]
SHEET_NAME             = "All Meta Data"
FX_SP_FOLDER           = SP_PATHS["control_panel"]
FX_FILE                = "KOL_FX_Rates.xlsx"
FX_SHEET               = "FX Rates"

INSIGHT_FIELDS = [
    "account_id", "account_name", "campaign_id", "campaign_name",
    "adset_id", "adset_name", "ad_id", "ad_name",
    "buying_type",
    "spend", "reach", "frequency", "impressions", "cpm", "cpc", "ctr",
    "actions",
    "video_p25_watched_actions", "video_p50_watched_actions",
    "video_p75_watched_actions", "video_p100_watched_actions",
    "video_thruplay_watched_actions",
    "catalog_segment_actions", "catalog_segment_value",
    "purchase_roas", "date_start", "date_stop",
]

BREAKDOWN_MAP = {
    "none":               [],
    "platform_placement": ["publisher_platform", "platform_position"],
    "age_gender":         ["age", "gender"],
}


def monthly_chunks(date_start, date_stop):
    start = date.fromisoformat(date_start)
    stop  = date.fromisoformat(date_stop)
    if start.year == stop.year and start.month == stop.month:
        return [(date_start, date_stop)]
    chunks = []
    cur = start
    while cur <= stop:
        month_end = (cur + relativedelta(months=1)) - relativedelta(days=1)
        chunk_end = min(month_end, stop)
        chunks.append((cur.isoformat(), chunk_end.isoformat()))
        cur = chunk_end + relativedelta(days=1)
    return chunks


def daily_chunks(chunk_start, chunk_end):
    """Split a date range into individual days."""
    from datetime import timedelta
    start = date.fromisoformat(chunk_start)
    stop  = date.fromisoformat(chunk_end)
    days  = []
    cur   = start
    while cur <= stop:
        days.append((cur.isoformat(), cur.isoformat()))
        cur += timedelta(days=1)
    return days


def load_fx_rates(pa):
    logger.info(f"Loading FX rates from SharePoint: {FX_FILE}")
    data = pa.download_bytes(FX_SP_FOLDER, FX_FILE)
    if data is None:
        logger.warning("FX rate file not found")
        return {}
    try:
        df = pd.read_excel(io.BytesIO(data), sheet_name=FX_SHEET)
        rates = {}
        for _, row in df.iterrows():
            m = str(row.get("Market","")).strip().upper()
            r = row.get("FX Rate (1 USD = ?)", None)
            if m and r: rates[m] = float(r)
        logger.info(f"FX rates loaded: {rates}")
        return rates
    except Exception as e:
        logger.error(f"Failed to load FX rates: {e}")
        return {}


def fetch_market(market, date_start, date_stop, fx_rates, pa, time_increment=1, breakdown="platform_placement"):
    breakdowns = BREAKDOWN_MAP.get(breakdown) or None
    logger.info(f"[{market}] Fetching All Meta {date_start} -> {date_stop} (breakdown={breakdown})")
    accounts = load_accounts(market, pa, report_type=None)
    if not accounts:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    client   = MetaAPIClient(market)
    all_rows = []
    chunks   = monthly_chunks(date_start, date_stop)
    if len(chunks) > 1:
        logger.info(f"[{market}] Date range spans {len(chunks)} months — fetching month by month")

    for acct in accounts:
        acct_rows = []
        for chunk_start, chunk_end in chunks:
            try:
                rows = client.get_insights(
                    ad_account_id=acct["id"], date_start=chunk_start, date_stop=chunk_end,
                    level="ad", fields=INSIGHT_FIELDS, breakdowns=breakdowns,
                    time_increment=time_increment,
                )
                acct_rows.extend(rows)
            except Exception as e:
                if "3018" in str(e):
                    logger.warning(f"[{market}] Skipping {chunk_start}~{chunk_end} (beyond 37-month limit)")
                elif "Please reduce the amount of data" in str(e) or ("500" in str(e) and chunk_start != chunk_end):
                    # HTTP 500: too much data — fall back to day-by-day fetch
                    logger.warning(
                        f"[{market}] HTTP 500 on {acct['id']} [{chunk_start}~{chunk_end}] "
                        f"— retrying day by day..."
                    )
                    for day_start, day_end in daily_chunks(chunk_start, chunk_end):
                        try:
                            day_rows = client.get_insights(
                                ad_account_id=acct["id"], date_start=day_start, date_stop=day_end,
                                level="ad", fields=INSIGHT_FIELDS, breakdowns=breakdowns,
                                time_increment=time_increment,
                            )
                            acct_rows.extend(day_rows)
                        except Exception as day_e:
                            if "3018" in str(day_e):
                                logger.warning(f"[{market}] Skipping {day_start} (beyond 37-month limit)")
                            else:
                                logger.error(f"[{market}] Error {acct['id']} [{day_start}]: {day_e}")
                else:
                    logger.error(f"[{market}] Error {acct['id']} [{chunk_start}~{chunk_end}]: {e}")
        all_rows.extend(acct_rows)
        if acct_rows: logger.info(f"[{market}] {acct['name']}: {len(acct_rows)} rows")

    if not all_rows:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    unique_ad_ids = list({str(r.get("ad_id","")) for r in all_rows if r.get("ad_id")})
    story_id_map = {}; page_name_map = {}; creative_info_map = {}
    video_url_map = {}; campaign_map = {}

    try:
        creative_info_map = client.get_creative_info_for_ads(unique_ad_ids)
        for ad_id, info in creative_info_map.items():
            osi = info.get("object_story_id","")
            if osi and "_" in str(osi): story_id_map[ad_id] = osi
            elif info.get("page_id"): story_id_map[ad_id] = f"{info['page_id']}_0"
        page_name_map = client.get_page_names_for_ads(unique_ad_ids, story_id_map=story_id_map)
        video_ids = list({info["video_id"] for info in creative_info_map.values() if info.get("video_id")})
        if video_ids: video_url_map = client.get_video_urls(video_ids)
        missing_media = [
            a for a in unique_ad_ids
            if not creative_info_map.get(a,{}).get("image_url")
            and not creative_info_map.get(a,{}).get("video_id")
            and story_id_map.get(a,"")
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
        logger.info(
            f"[{market}] Pages: {sum(1 for v in page_name_map.values() if v)}/{len(unique_ad_ids)} | "
            f"Images: {sum(1 for v in creative_info_map.values() if v.get('image_url'))}/{len(unique_ad_ids)} | "
            f"Campaigns: {sum(1 for v in campaign_map.values() if v.get('start'))}/{len(unique_cids)}"
        )
    except Exception as e:
        import traceback
        logger.warning(f"[{market}] Creative/campaign lookup failed: {e}")
        logger.warning(traceback.format_exc())

    df = transform(
        all_rows, fx_rates=fx_rates, page_name_map=page_name_map,
        creative_info_map=creative_info_map, video_url_map=video_url_map,
        story_id_map=story_id_map, campaign_map=campaign_map,
    )
    if breakdown == "age_gender" and "Platform" in df.columns:
        df = df.rename(columns={"Platform": "Age", "Placement": "Gender"})
    return df


def _output_filename(time_increment, breakdown):
    ti = "monthly" if str(time_increment) == "monthly" else "daily"
    bd = breakdown if breakdown in ("none","age_gender","platform_placement") else "platform_placement"
    return f"HKTW_Meta_All_{ti}_{bd}.xlsx"


def migrate_existing_schema(df: "pd.DataFrame") -> "pd.DataFrame":
    """
    Bring a DataFrame loaded from an older SharePoint file up to the current
    OUTPUT_COLUMNS schema.  Safe to call even if the file is already current.
    """
    from scripts.kol_transformer import get_quarter, get_duration_group

    # ── 1. Rename old column names to new ones ───────────────────────────────
    rename_map = {
        "Creative Video URL": "Creative Video URL (Permalink)",   # old → new split column
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

    # ── 2. Add missing columns with empty default ────────────────────────────
    for col in OUTPUT_COLUMNS:
        if col not in df.columns:
            df[col] = ""

    # ── 3. Backfill derived columns for old rows that are empty ─────────────
    # Quarter — derive from Date column
    empty_quarter = df["Quarter"].isna() | (df["Quarter"].astype(str).str.strip() == "")
    if empty_quarter.any():
        dates = pd.to_datetime(df.loc[empty_quarter, "Date"], errors="coerce")
        df.loc[empty_quarter, "Quarter"] = dates.apply(get_quarter)
        filled = empty_quarter.sum() - (df["Quarter"].isna() | (df["Quarter"].astype(str).str.strip() == "")).sum()
        logger.info(f"Schema migration: filled {filled} Quarter values from Date")

    # Duration Group — derive from Creative Type
    empty_dur = df["Duration Group"].isna() | (df["Duration Group"].astype(str).str.strip() == "")
    if empty_dur.any() and "Creative Type" in df.columns:
        df.loc[empty_dur, "Duration Group"] = df.loc[empty_dur, "Creative Type"].fillna("").apply(get_duration_group)
        filled = empty_dur.sum() - (df["Duration Group"].isna() | (df["Duration Group"].astype(str).str.strip() == "")).sum()
        logger.info(f"Schema migration: filled {filled} Duration Group values from Creative Type")

    # Media Buying — derive from buying_type is not available after the fact,
    # so leave as empty string for old rows (acceptable — only affects historical data)

    # ── 4. Reorder to current OUTPUT_COLUMNS (drop any extra legacy columns) ─
    df = df[OUTPUT_COLUMNS]
    return df


def load_existing(pa, output_file):
    data = pa.download_bytes(SP_FOLDER, output_file)
    if data is None:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    try:
        df = pd.read_excel(io.BytesIO(data), sheet_name=SHEET_NAME, dtype=str)
        logger.info(f"Loaded {len(df)} existing rows")
        df = migrate_existing_schema(df)
        return df
    except Exception as e:
        logger.error(f"Failed to read existing: {e}")
        return pd.DataFrame(columns=OUTPUT_COLUMNS)


def _get_dedupe_keys(breakdown):
    if breakdown == "age_gender": return DEDUPE_KEYS_AGE_GENDER
    if breakdown == "none": return DEDUPE_KEYS_NONE
    return DEDUPE_KEYS


def merge_and_deduplicate(existing, new_data, breakdown="platform_placement"):
    if new_data.empty: return existing
    dedupe_keys = _get_dedupe_keys(breakdown)
    combined = pd.concat([existing, new_data], ignore_index=True)
    for col in dedupe_keys:
        if col in combined.columns:
            combined[col] = combined[col].astype(str).str.strip()
    before = len(combined)
    combined = combined.drop_duplicates(subset=dedupe_keys, keep="last")
    logger.info(f"Dedup: {before} -> {len(combined)} rows ({before-len(combined)} removed)")
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
    breakdown      = os.environ.get("BREAKDOWN", "platform_placement")
    if time_increment not in ("1","monthly"): time_increment = "1"
    if breakdown not in ("none","platform_placement","age_gender"): breakdown = "platform_placement"
    if not date_start or not date_stop:
        raise ValueError("DATE_START and DATE_STOP required")
    markets_to_run = list(MARKETS.keys()) if market == "ALL" else [market]
    output_file = _output_filename(time_increment, breakdown)
    logger.info(f"All Meta Report | {markets_to_run} | {date_start} -> {date_stop} | {breakdown} | {output_file}")
    pa       = PowerAutomateClient()
    fx_rates = load_fx_rates(pa)
    new_frames = []
    for m in markets_to_run:
        df_m = fetch_market(m, date_start, date_stop, fx_rates, pa, time_increment, breakdown)
        if not df_m.empty: new_frames.append(df_m)
    new_data = pd.concat(new_frames, ignore_index=True) if new_frames else pd.DataFrame(columns=OUTPUT_COLUMNS)
    logger.info(f"Total new rows: {len(new_data)}")
    existing = load_existing(pa, output_file)
    merged   = merge_and_deduplicate(existing, new_data, breakdown)
    excel_bytes = save_to_excel(merged)

    # ── Save timestamped artifact locally (for GitHub Actions artifact download) ──
    from datetime import datetime as _dt
    mkt_str   = market if market != "ALL" else "HKTW"
    ti_str    = "monthly" if str(time_increment) == "monthly" else "daily"
    timestamp = _dt.utcnow().strftime("%Y%m%d_%H%M")
    artifact_dir  = os.environ.get("ARTIFACT_DIR", "report_output")
    os.makedirs(artifact_dir, exist_ok=True)
    artifact_name = f"All_Meta_{mkt_str}_{date_start}_{date_stop}_{ti_str}_{breakdown}_{timestamp}.xlsx"
    artifact_path = os.path.join(artifact_dir, artifact_name)
    with open(artifact_path, "wb") as f:
        f.write(excel_bytes)
    logger.info(f"Artifact saved: {artifact_path} ({len(merged)} rows)")

    # ── Upload to SharePoint (fixed filename for accumulation) ──
    logger.info(f"Uploading {len(merged)} rows -> {SP_FOLDER}/{output_file}")
    pa.upload_bytes(excel_bytes, SP_FOLDER, output_file)
    logger.info("All Meta Report completed.")

if __name__ == "__main__":
    main()
