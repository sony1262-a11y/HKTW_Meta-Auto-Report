"""HKTW Meta Auto Report - CPAS Debug Fetch"""
import os, sys, io, json, logging
import pandas as pd
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import MARKETS
from scripts.meta_api_client import MetaAPIClient
from scripts.cpas_transformer import transform, flatten_row, OUTPUT_COLUMNS
from scripts.cpas_report import INSIGHT_FIELDS, SP_FOLDER, OUTPUT_FILE, SHEET_NAME
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
    return path


def debug_fetch_market(market, date_start, date_stop, pa, time_increment=1):
    summary = {"market": market, "accounts": [], "raw_rows": 0, "transformed_rows": 0, "errors": []}
    accounts = load_accounts(market, pa, report_type="CPAS")
    summary["accounts"] = [{"id": a["id"], "name": a["name"], "status": "enabled"} for a in accounts]
    logger.info(f"[{market}] CPAS accounts: {len(accounts)}")
    for a in accounts: logger.info(f"  {a['id']} | {a['name']}")
    if not accounts:
        summary["errors"].append(f"[{market}] No CPAS accounts found")
        return summary
    try:
        client = MetaAPIClient(market)
    except Exception as e:
        summary["errors"].append(f"[{market}] MetaAPIClient init failed: {e}")
        return summary

    all_raw_rows = []; all_flat_rows = []
    for acct in accounts:
        try:
            rows = client.get_insights(
                ad_account_id=acct["id"], date_start=date_start, date_stop=date_stop,
                level="ad", fields=INSIGHT_FIELDS, time_increment=time_increment,
            )
            logger.info(f"[{market}] {acct['name']}: {len(rows)} raw rows")
            for r in rows:
                flat_raw = {k: v for k, v in r.items() if not isinstance(v, list)}
                flat_raw["_actions_json"]                 = json.dumps(r.get("actions", []))
                flat_raw["_action_values_json"]           = json.dumps(r.get("action_values", []))
                flat_raw["_purchase_roas_json"]           = json.dumps(r.get("purchase_roas", []))
                flat_raw["_catalog_segment_actions_json"] = json.dumps(r.get("catalog_segment_actions", []))
                flat_raw["_catalog_segment_value_json"]   = json.dumps(r.get("catalog_segment_value", []))
                all_raw_rows.append(flat_raw)
            all_flat_rows.extend(rows)
        except Exception as e:
            if "3018" in str(e):
                logger.warning(f"[{market}] Skipping {acct['id']} (beyond 37-month limit)")
            else:
                msg = f"[{market}] Error {acct['id']}: {e}"
                logger.error(msg); summary["errors"].append(msg)

    summary["raw_rows"] = len(all_flat_rows)
    if not all_raw_rows:
        logger.warning(f"[{market}] No rows fetched")
        return summary

    save_excel(pd.DataFrame(all_raw_rows), f"CPAS_raw_{market}_{date_start}_{date_stop}.xlsx", "Raw API Response")

    story_id_map = {}; creative_info_map = {}; video_url_map = {}; campaign_map = {}
    try:
        unique_ad_ids = list({str(r.get("ad_id","")) for r in all_flat_rows if r.get("ad_id")})
        creative_info_map = client.get_creative_info_for_ads(unique_ad_ids)
        for ad_id, info in creative_info_map.items():
            osi = info.get("object_story_id","")
            if osi and "_" in str(osi): story_id_map[ad_id] = osi
            elif info.get("page_id"): story_id_map[ad_id] = f"{info['page_id']}_0"
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
        unique_cids = list({str(r.get("campaign_id","")) for r in all_flat_rows if r.get("campaign_id")})
        campaign_map = client.get_campaign_info(unique_cids)
        logger.info(f"[{market}] Images: {sum(1 for v in creative_info_map.values() if v.get('image_url'))}/{len(unique_ad_ids)} | "
                    f"Videos: {sum(1 for v in video_url_map.values() if v)}/{len(video_ids) if video_ids else 0} | "
                    f"Campaigns: {sum(1 for v in campaign_map.values() if v.get('start'))}/{len(unique_cids)}")
    except Exception as e:
        logger.warning(f"[{market}] Creative/campaign lookup failed: {e}")

    try:
        df_t = transform(all_flat_rows, creative_info_map=creative_info_map,
                         video_url_map=video_url_map, story_id_map=story_id_map,
                         campaign_map=campaign_map)
        summary["transformed_rows"] = len(df_t)
        save_excel(df_t, f"CPAS_transformed_{market}_{date_start}_{date_stop}.xlsx", "Transformed")
    except Exception as e:
        msg = f"[{market}] Transform error: {e}"
        logger.error(msg); summary["errors"].append(msg)

    return summary


def main():
    market         = os.environ.get("MARKET", "ALL").upper()
    date_start     = os.environ.get("DATE_START")
    date_stop      = os.environ.get("DATE_STOP")
    upload         = os.environ.get("UPLOAD_TO_SHAREPOINT","false").lower() == "true"
    time_increment = os.environ.get("TIME_INCREMENT", "1")
    if time_increment not in ("1","monthly"): time_increment = "1"
    if not date_start or not date_stop: raise ValueError("DATE_START and DATE_STOP required")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    markets_to_run = list(MARKETS.keys()) if market == "ALL" else [market]
    logger.info("=" * 60)
    logger.info("DEBUG CPAS FETCH")
    logger.info(f"Markets: {markets_to_run} | {date_start} -> {date_stop}")
    logger.info("=" * 60)
    pa = PowerAutomateClient(); all_summaries = []; all_transformed = []
    for m in markets_to_run:
        s = debug_fetch_market(m, date_start, date_stop, pa, time_increment)
        all_summaries.append(s)
        t_file = os.path.join(OUTPUT_DIR, f"CPAS_transformed_{m}_{date_start}_{date_stop}.xlsx")
        if os.path.exists(t_file):
            try: all_transformed.append(pd.read_excel(t_file))
            except Exception: pass
    if all_transformed:
        df_merged = pd.concat(all_transformed, ignore_index=True)
        save_excel(df_merged, f"CPAS_transformed_HKTW_{date_start}_{date_stop}.xlsx", "CPAS Data")
    for s in all_summaries:
        logger.info(f"\n-- {s['market']} -- | Accounts: {len(s['accounts'])} | Raw: {s['raw_rows']} | Transformed: {s['transformed_rows']}")
        for e in s["errors"]: logger.info(f"  !! {e}")
    has_errors = any(s["errors"] for s in all_summaries)
    if has_errors: logger.error("Completed with errors"); sys.exit(1)
    logger.info("Debug fetch completed successfully.")

if __name__ == "__main__":
    main()
