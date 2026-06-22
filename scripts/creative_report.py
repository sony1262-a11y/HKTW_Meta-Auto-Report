"""HKTW Meta Auto Report - Creative Report
Fetches creative assets (Image URL, Post URL, Page Name) for all ads.
No performance metrics — use this to build / refresh the creative library.
Output: GitHub Actions artifact only.
"""
import os, sys, io, logging
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import MARKETS
from scripts.meta_api_client import MetaAPIClient
from scripts.power_automate_client import PowerAutomateClient
from scripts.account_loader import load_accounts
from scripts.all_report import monthly_chunks

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Minimal insight fields — just enough to get ad identity, no metrics
INSIGHT_FIELDS = [
    "account_id", "account_name",
    "campaign_id", "campaign_name",
    "adset_id", "adset_name",
    "ad_id", "ad_name",
    "date_start", "date_stop",
]

OUTPUT_COLUMNS = [
    "Market",
    "Ad Account ID", "Ad Account Name",
    "Campaign ID", "Campaign Name",
    "Ad Set ID", "Ad Set Name",
    "Ad ID", "Ad Name",
    "Date Start", "Date Stop",
    "Page Name",
    "Post URL",
    "Creative Image URL",
]


def fetch_market(market, date_start, date_stop, pa):
    logger.info(f"[{market}] Fetching creative data {date_start} -> {date_stop}")
    accounts = load_accounts(market, pa)
    if not accounts:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    client = MetaAPIClient(market)
    all_rows = []
    chunks = monthly_chunks(date_start, date_stop)

    for acct in accounts:
        logger.info(f"[{market}]   -> {acct['name']} ({acct['id']})")
        for chunk_start, chunk_end in chunks:
            try:
                # Use monthly aggregation — we only need unique ads, not daily rows
                rows = client.get_insights(
                    ad_account_id=acct["id"],
                    date_start=chunk_start, date_stop=chunk_end,
                    level="ad", fields=INSIGHT_FIELDS,
                    time_increment="monthly",
                )
                all_rows.extend(rows)
                if rows: logger.info(f"[{market}]     {acct['name']}: {len(rows)} ads in {chunk_start}~{chunk_end}")
            except Exception as e:
                if "3018" in str(e):
                    logger.warning(f"[{market}]     Skipping {chunk_start}~{chunk_end} (beyond 37-month limit)")
                else:
                    logger.error(f"[{market}]     Error {acct['id']} [{chunk_start}~{chunk_end}]: {e}")

    if not all_rows:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    # Deduplicate: we only want one row per unique Ad ID
    seen = set()
    unique_rows = []
    for r in all_rows:
        ad_id = str(r.get("ad_id",""))
        if ad_id and ad_id not in seen:
            seen.add(ad_id)
            unique_rows.append(r)
    logger.info(f"[{market}] {len(unique_rows)} unique ads across all chunks")

    unique_ad_ids = [str(r["ad_id"]) for r in unique_rows]
    story_id_map = {}; page_name_map = {}; creative_info_map = {}

    try:
        creative_info_map = client.get_creative_info_for_ads(unique_ad_ids)
        for ad_id, info in creative_info_map.items():
            osi = info.get("object_story_id","")
            if osi and "_" in str(osi): story_id_map[ad_id] = osi
            elif info.get("page_id"): story_id_map[ad_id] = f"{info['page_id']}_0"
        page_name_map = client.get_page_names_for_ads(unique_ad_ids, story_id_map=story_id_map)
        missing_img = [
            ad_id for ad_id in unique_ad_ids
            if not creative_info_map.get(ad_id, {}).get("image_url")
            and story_id_map.get(ad_id, "")
        ]
        if missing_img:
            msi = list({story_id_map[a] for a in missing_img if story_id_map.get(a)})
            post_media = client.get_post_media(msi)
            for ad_id in missing_img:
                sid = story_id_map.get(ad_id, "")
                if sid and sid in post_media and post_media[sid].get("image_url"):
                    creative_info_map[ad_id]["image_url"] = post_media[sid]["image_url"]
        logger.info(
            f"[{market}] Pages: {sum(1 for v in page_name_map.values() if v)}/{len(unique_ad_ids)} | "
            f"Images: {sum(1 for v in creative_info_map.values() if v.get('image_url'))}/{len(unique_ad_ids)}"
        )
    except Exception as e:
        import traceback
        logger.warning(f"[{market}] Creative lookup failed: {e}\n{traceback.format_exc()}")

    # Build output rows
    from scripts.kol_transformer import get_market_from_account
    records = []
    for r in unique_rows:
        ad_id    = str(r.get("ad_id",""))
        info     = creative_info_map.get(ad_id, {})
        sid      = story_id_map.get(ad_id, "")
        post_url = ""
        if sid and "_" in str(sid):
            parts = str(sid).split("_", 1)
            if len(parts) == 2 and parts[1] != "0":
                post_url = f"https://www.facebook.com/{parts[0]}/posts/{parts[1]}"

        records.append({
            "Market":           get_market_from_account(str(r.get("account_name",""))),
            "Ad Account ID":    str(r.get("account_id","")),
            "Ad Account Name":  str(r.get("account_name","")),
            "Campaign ID":      str(r.get("campaign_id","")),
            "Campaign Name":    str(r.get("campaign_name","")),
            "Ad Set ID":        str(r.get("adset_id","")),
            "Ad Set Name":      str(r.get("adset_name","")),
            "Ad ID":            ad_id,
            "Ad Name":          str(r.get("ad_name","")),
            "Date Start":       str(r.get("date_start","")),
            "Date Stop":        str(r.get("date_stop","")),
            "Page Name":        page_name_map.get(ad_id, ""),
            "Post URL":         post_url,
            "Creative Image URL": info.get("image_url", ""),
        })

    return pd.DataFrame(records, columns=OUTPUT_COLUMNS)


def main():
    market     = os.environ.get("MARKET", "ALL").upper()
    date_start = os.environ.get("DATE_START")
    date_stop  = os.environ.get("DATE_STOP")
    if not date_start or not date_stop:
        raise ValueError("DATE_START and DATE_STOP required")
    markets_to_run = list(MARKETS.keys()) if market == "ALL" else [market]
    logger.info(f"Creative Report | {markets_to_run} | {date_start} -> {date_stop}")
    pa = PowerAutomateClient()
    all_frames = []
    for m in markets_to_run:
        df_m = fetch_market(m, date_start, date_stop, pa)
        if not df_m.empty: all_frames.append(df_m)
    if not all_frames:
        logger.warning("No data fetched")
        df_out = pd.DataFrame(columns=OUTPUT_COLUMNS)
    else:
        df_out = pd.concat(all_frames, ignore_index=True)
    logger.info(f"Total unique ads: {len(df_out)}")

    from datetime import datetime as _dt
    mkt_str   = market if market != "ALL" else "HKTW"
    timestamp = _dt.utcnow().strftime("%Y%m%d_%H%M")
    artifact_dir  = os.environ.get("ARTIFACT_DIR", "report_output")
    os.makedirs(artifact_dir, exist_ok=True)
    artifact_name = f"Creative_{mkt_str}_{date_start}_{date_stop}_{timestamp}.xlsx"
    artifact_path = os.path.join(artifact_dir, artifact_name)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df_out.to_excel(w, sheet_name="Creative Library", index=False)
    with open(artifact_path, "wb") as f:
        f.write(buf.getvalue())
    logger.info(f"Artifact saved: {artifact_path}")

if __name__ == "__main__":
    main()
