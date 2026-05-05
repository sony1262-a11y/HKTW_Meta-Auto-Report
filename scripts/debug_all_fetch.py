"""HKTW Meta Auto Report - All Accounts Debug Fetch"""
import os, sys, io, json, logging
import pandas as pd
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import MARKETS
from scripts.meta_api_client import MetaAPIClient
from scripts.all_transformer import transform, OUTPUT_COLUMNS
from scripts.all_report import (
    INSIGHT_FIELDS, BREAKDOWN_MAP, SP_FOLDER, SHEET_NAME,
    load_fx_rates, load_existing, merge_and_deduplicate, save_to_excel,
    _output_filename, monthly_chunks, daily_chunks,
)
from scripts.power_automate_client import PowerAutomateClient
from scripts.account_loader import load_accounts

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "debug_output")


def save_excel(df, filename, sheet_name="Data"):
    path = os.path.join(OUTPUT_DIR, filename)
    with pd.ExcelWriter(path, engine="openpyxl") as w:
        df.to_excel(w, sheet_name=sheet_name, index=False)
    logger.info(f"Saved: {path} ({len(df)} rows)")


def debug_fetch_market(market, date_start, date_stop, fx_rates, pa, time_increment=1, breakdown="platform_placement"):
    summary = {"market": market, "accounts": [], "raw_rows": 0, "transformed_rows": 0, "errors": []}
    breakdowns = BREAKDOWN_MAP.get(breakdown) or None
    accounts = load_accounts(market, pa, report_type=None)
    summary["accounts"] = [{"id": a["id"], "name": a["name"]} for a in accounts]
    logger.info(f"[{market}] All accounts loaded: {len(accounts)}")
    for a in accounts: logger.info(f"  {a['id']} | {a['name']} | type={a.get('type','?')} ")
    if not accounts:
        summary["errors"].append(f"[{market}] No accounts found")
        return summary
    try:
        client = MetaAPIClient(market)
    except Exception as e:
        summary["errors"].append(f"[{market}] MetaAPIClient init failed: {e}")
        return summary

    all_raw_rows = []; all_full_rows = []
    chunks = monthly_chunks(date_start, date_stop)
    if len(chunks) > 1: logger.info(f"[{market}] Fetching {len(chunks)} months")

    for acct in accounts:
        acct_rows = []
        for chunk_start, chunk_end in chunks:
            try:
                rows = client.get_insights(
                    ad_account_id=acct["id"], date_start=chunk_start, date_stop=chunk_end,
                    level="ad", fields=INSIGHT_FIELDS, breakdowns=breakdowns, time_increment=time_increment,
                )
                acct_rows.extend(rows)
            except Exception as e:
                if "3018" in str(e):
                    logger.warning(f"[{market}] Skipping {chunk_start}~{chunk_end} (beyond 37-month limit)")
                elif "Please reduce the amount of data" in str(e) or ("500" in str(e) and chunk_start != chunk_end):
                    logger.warning(
                        f"[{market}] HTTP 500 on {acct['id']} [{chunk_start}~{chunk_end}] "
                        f"— retrying day by day..."
                    )
                    from scripts.all_report import daily_chunks as _daily_chunks
                    for day_start, day_end in _daily_chunks(chunk_start, chunk_end):
                        try:
                            day_rows = client.get_insights(
                                ad_account_id=acct["id"], date_start=day_start, date_stop=day_end,
                                level="ad", fields=INSIGHT_FIELDS, breakdowns=breakdowns, time_increment=time_increment,
                            )
                            acct_rows.extend(day_rows)
                        except Exception as day_e:
                            if "3018" in str(day_e):
                                logger.warning(f"[{market}] Skipping {day_start} (beyond 37-month limit)")
                            else:
                                msg = f"[{market}] Error {acct['id']} [{day_start}]: {day_e}"
                                logger.error(msg); summary["errors"].append(msg)
                else:
                    msg = f"[{market}] Error {acct['id']} [{chunk_start}~{chunk_end}]: {e}"
                    logger.error(msg)
                    summary["errors"].append(msg)
        for r in acct_rows:
            flat_raw = {k: v for k, v in r.items() if not isinstance(v, list)}
            flat_raw["_actions_json"]                 = json.dumps(r.get("actions", []))
            flat_raw["_catalog_segment_actions_json"] = json.dumps(r.get("catalog_segment_actions", []))
            flat_raw["_catalog_segment_value_json"]   = json.dumps(r.get("catalog_segment_value", []))
            flat_raw["_purchase_roas_json"]           = json.dumps(r.get("purchase_roas", []))
            all_raw_rows.append(flat_raw)
        all_full_rows.extend(acct_rows)
        if acct_rows: logger.info(f"[{market}] {acct['name']}: {len(acct_rows)} rows")

    summary["raw_rows"] = len(all_full_rows)
    if not all_raw_rows:
        logger.warning(f"[{market}] No rows fetched")
        return summary

    df_raw = pd.DataFrame(all_raw_rows)
    save_excel(df_raw, f"All_raw_{market}_{date_start}_{date_stop}_{breakdown}.xlsx", "Raw API Response")

    story_id_map = {}; page_name_map = {}; creative_info_map = {}
    video_url_map = {}; campaign_map = {}

    try:
        unique_ad_ids = list({str(r.get("ad_id","")) for r in all_full_rows if r.get("ad_id")})
        logger.info(f"[{market}] Starting creative/campaign lookup for {len(unique_ad_ids)} unique ads...")
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
        unique_cids = list({str(r.get("campaign_id","")) for r in all_full_rows if r.get("campaign_id")})
        campaign_map = client.get_campaign_info(unique_cids)
        logger.info(
            f"[{market}] Post URLs: {sum(1 for v in story_id_map.values() if '_' in v and not v.endswith('_0'))}/{len(unique_ad_ids)} | "
            f"Pages: {sum(1 for v in page_name_map.values() if v)}/{len(unique_ad_ids)} | "
            f"Images: {sum(1 for v in creative_info_map.values() if v.get('image_url'))}/{len(unique_ad_ids)} | "
            f"Videos: {sum(1 for v in video_url_map.values() if v)}/{len(video_ids) if video_ids else 0} | "
            f"Campaigns: {sum(1 for v in campaign_map.values() if v.get('start'))}/{len(unique_cids)}"
        )
    except Exception as e:
        import traceback
        logger.warning(f"[{market}] Lookup failed: {e}")
        logger.warning(traceback.format_exc())

    try:
        df_t = transform(
            all_full_rows, fx_rates=fx_rates, page_name_map=page_name_map,
            creative_info_map=creative_info_map, video_url_map=video_url_map,
            story_id_map=story_id_map, campaign_map=campaign_map,
        )
        if breakdown == "age_gender" and "Platform" in df_t.columns:
            df_t = df_t.rename(columns={"Platform": "Age", "Placement": "Gender"})
        summary["transformed_rows"] = len(df_t)
        save_excel(df_t, f"All_transformed_{market}_{date_start}_{date_stop}_{breakdown}.xlsx", "All Meta Data")
    except Exception as e:
        msg = f"[{market}] Transform error: {e}"
        logger.error(msg)
        summary["errors"].append(msg)

    return summary


def main():
    market         = os.environ.get("MARKET", "ALL").upper()
    date_start     = os.environ.get("DATE_START")
    date_stop      = os.environ.get("DATE_STOP")
    upload         = os.environ.get("UPLOAD_TO_SHAREPOINT","false").lower() == "true"
    time_increment = os.environ.get("TIME_INCREMENT", "1")
    breakdown      = os.environ.get("BREAKDOWN", "platform_placement")
    if time_increment not in ("1","monthly"): time_increment = "1"
    if breakdown not in ("none","platform_placement","age_gender"): breakdown = "platform_placement"
    if not date_start or not date_stop: raise ValueError("DATE_START and DATE_STOP required")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    markets_to_run = list(MARKETS.keys()) if market == "ALL" else [market]
    pa       = PowerAutomateClient()
    fx_rates = load_fx_rates(pa)
    logger.info("=" * 60)
    logger.info("DEBUG ALL META FETCH")
    logger.info(f"Markets: {markets_to_run} | {date_start} -> {date_stop} | {breakdown}")
    logger.info(f"FX rates: {fx_rates} | SharePoint upload: {upload}")
    logger.info("=" * 60)
    all_summaries = []; all_transformed = []
    for m in markets_to_run:
        s = debug_fetch_market(m, date_start, date_stop, fx_rates, pa, time_increment, breakdown)
        all_summaries.append(s)
        t_file = os.path.join(OUTPUT_DIR, f"All_transformed_{m}_{date_start}_{date_stop}_{breakdown}.xlsx")
        if os.path.exists(t_file):
            try: all_transformed.append(pd.read_excel(t_file))
            except Exception: pass
    if all_transformed:
        df_merged = pd.concat(all_transformed, ignore_index=True)
        save_excel(df_merged, f"All_transformed_HKTW_{date_start}_{date_stop}_{breakdown}.xlsx", "All Meta Data")
        logger.info(f"Merged HKTW file: {len(df_merged)} rows")
    if upload and all_transformed:
        output_file = _output_filename(time_increment, breakdown)
        df_merged   = pd.concat(all_transformed, ignore_index=True)
        existing  = load_existing(pa, output_file)
        merged    = merge_and_deduplicate(existing, df_merged, breakdown)
        pa.upload_bytes(save_to_excel(merged), SP_FOLDER, output_file)
        logger.info(f"Uploaded {len(merged)} rows -> {output_file}")
    logger.info("=" * 60)
    logger.info("ALL META DEBUG FETCH SUMMARY")
    logger.info("=" * 60)
    has_errors = False
    for s in all_summaries:
        logger.info(f"\n-- {s['market']} --")
        logger.info(f"Accounts: {len(s['accounts'])} | Raw rows: {s['raw_rows']} | Transformed: {s['transformed_rows']}")
        if s["errors"]:
            has_errors = True
            for err in s["errors"]: logger.info(f"  !! {err}")
        else:
            logger.info("Errors: none")
    logger.info("=" * 60)
    if has_errors:
        logger.error("Completed with errors")
        sys.exit(1)
    logger.info("Debug All Meta fetch completed successfully.")

if __name__ == "__main__":
    main()
