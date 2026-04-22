"""
HKTW Meta Auto Report - KOL Debug Fetch
Outputs:
  1. KOL_raw_{market}_{date}.xlsx        ← raw API response
  2. KOL_transformed_{market}_{date}.xlsx ← after transform
  3. KOL_debug_summary.txt               ← account list, row counts, errors
"""
import os
import sys
import io
import json
import logging
import pandas as pd
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import MARKETS
from scripts.meta_api_client import MetaAPIClient
from scripts.kol_transformer import transform, OUTPUT_COLUMNS
from scripts.kol_report import (
    INSIGHT_FIELDS, BREAKDOWNS,
    SP_FOLDER, OUTPUT_FILE, SHEET_NAME,
    load_fx_rates, load_existing, merge_and_deduplicate, save_to_excel,
)
from scripts.power_automate_client import PowerAutomateClient
from scripts.account_loader import load_accounts

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "debug_output")


def save_excel(df: pd.DataFrame, filename: str, sheet_name: str = "Data"):
    path = os.path.join(OUTPUT_DIR, filename)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name=sheet_name, index=False)
    logger.info(f"Saved: {path} ({len(df)} rows)")


def append_summary(lines: list[str]):
    path = os.path.join(OUTPUT_DIR, "KOL_debug_summary.txt")
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def debug_fetch_market(
    market: str,
    date_start: str,
    date_stop: str,
    fx_rates: dict,
    pa: PowerAutomateClient,
    time_increment: str | int = 1,
) -> dict:
    summary = {
        "market":           market,
        "accounts":         [],
        "raw_rows":         0,
        "transformed_rows": 0,
        "errors":           [],
    }

    accounts = load_accounts(market, pa, report_type=None)
    summary["accounts"] = [{"id": a["id"], "name": a["name"]} for a in accounts]

    logger.info(f"[{market}] KOL accounts loaded from Control Panel: {len(accounts)}")
    for a in accounts:
        logger.info(f"  {a['id']} | {a['name']}")

    if not accounts:
        summary["errors"].append(
            f"[{market}] No KOL accounts found in Control Panel. "
            "Check HK_Ad_Accounts.xlsx / TW_Ad_Accounts.xlsx on SharePoint."
        )
        return summary

    try:
        client = MetaAPIClient(market)
    except Exception as e:
        summary["errors"].append(f"[{market}] MetaAPIClient init failed: {e}")
        return summary

    all_raw_rows  = []
    all_full_rows = []

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
                breakdowns     = BREAKDOWNS,
                time_increment = time_increment,
            )
            logger.info(f"[{market}] {acct_name}: {len(rows)} rows")

            for r in rows:
                flat_raw = {k: v for k, v in r.items() if not isinstance(v, list)}
                flat_raw["_actions_json"] = json.dumps(r.get("actions", []))
                all_raw_rows.append(flat_raw)

            all_full_rows.extend(rows)

        except Exception as e:
            msg = f"[{market}] Error {acct_id} ({acct_name}): {e}"
            logger.error(msg)
            summary["errors"].append(msg)

    summary["raw_rows"] = len(all_raw_rows)

    if not all_raw_rows:
        logger.warning(f"[{market}] No rows fetched")
        return summary

    # Save raw
    df_raw = pd.DataFrame(all_raw_rows)
    save_excel(df_raw, f"KOL_raw_{market}_{date_start}_{date_stop}.xlsx", "Raw API Response")

    # Page name + creative info lookup
    page_name_map: dict[str, str] = {}
    creative_info_map: dict[str, dict] = {}
    video_url_map: dict[str, str] = {}
    story_id_map_final: dict[str, str] = {}
    try:
        unique_ad_ids = list({str(r.get("ad_id", "")) for r in all_full_rows if r.get("ad_id")})
        story_id_map: dict[str, str] = {}

        logger.info(f"[{market}] Starting creative/page lookup for {len(unique_ad_ids)} unique ads...")

        creative_info_map = client.get_creative_info_for_ads(unique_ad_ids)

        # Build story_id_map from object_story_id in creative response
        for ad_id, info in creative_info_map.items():
            osi = info.get("object_story_id", "")
            if osi and "_" in str(osi):
                story_id_map[ad_id] = osi
            elif info.get("page_id"):
                story_id_map[ad_id] = f"{info['page_id']}_0"

        story_id_map_final = story_id_map
        page_name_map = client.get_page_names_for_ads(unique_ad_ids, story_id_map=story_id_map)

        video_ids = list({info["video_id"] for info in creative_info_map.values() if info.get("video_id")})
        if video_ids:
            video_url_map = client.get_video_urls(video_ids)

        # Fallback: query post attachments for ads missing both image and video
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

        resolved_pages  = sum(1 for v in page_name_map.values() if v)
        resolved_images = sum(1 for v in creative_info_map.values() if v.get("image_url"))
        resolved_videos = sum(1 for v in video_url_map.values() if v)
        resolved_posts  = sum(1 for v in story_id_map.values() if "_" in v and not v.endswith("_0"))
        logger.info(f"[{market}] Page names: {resolved_pages}/{len(unique_ad_ids)} | "
                    f"Images: {resolved_images}/{len(unique_ad_ids)} | "
                    f"Videos: {resolved_videos}/{len(video_ids) if video_ids else 0} | "
                    f"Post URLs: {resolved_posts}/{len(unique_ad_ids)}")
    except Exception as e:
        import traceback
        logger.warning(f"[{market}] Creative/page lookup failed — fields will be blank: {e}")
        logger.warning(traceback.format_exc())

    # Save transformed
    try:
        df_t = transform(
            all_full_rows,
            fx_rates=fx_rates,
            page_name_map=page_name_map,
            creative_info_map=creative_info_map,
            video_url_map=video_url_map,
            story_id_map=story_id_map_final,
        )
        summary["transformed_rows"] = len(df_t)
        save_excel(df_t, f"KOL_transformed_{market}_{date_start}_{date_stop}.xlsx", "Transformed")
    except Exception as e:
        msg = f"[{market}] Transform error: {e}"
        logger.error(msg)
        summary["errors"].append(msg)

    return summary


def main():
    market         = os.environ.get("MARKET", "ALL").upper()
    date_start     = os.environ.get("DATE_START")
    date_stop      = os.environ.get("DATE_STOP")
    upload         = os.environ.get("UPLOAD_TO_SHAREPOINT", "false").lower() == "true"
    time_increment = os.environ.get("TIME_INCREMENT", "1")
    if time_increment not in ("1", "monthly"):
        time_increment = "1"

    if not date_start or not date_stop:
        raise ValueError("DATE_START and DATE_STOP are required")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    markets_to_run = list(MARKETS.keys()) if market == "ALL" else [market]

    pa       = PowerAutomateClient()
    fx_rates = load_fx_rates(pa)

    logger.info("=" * 60)
    logger.info("DEBUG KOL FETCH")
    logger.info(f"Markets:        {markets_to_run}")
    logger.info(f"Date range:     {date_start} → {date_stop}")
    logger.info(f"Time increment: {time_increment}")
    logger.info(f"FX rates:       {fx_rates}")
    logger.info(f"SharePoint upload: {upload}")
    logger.info("=" * 60)

    all_summaries = []
    all_transformed = []
    for m in markets_to_run:
        s = debug_fetch_market(m, date_start, date_stop, fx_rates, pa, time_increment=time_increment)
        all_summaries.append(s)
        t_file = os.path.join(OUTPUT_DIR, f"KOL_transformed_{m}_{date_start}_{date_stop}.xlsx")
        if os.path.exists(t_file):
            try:
                df_t = pd.read_excel(t_file)
                all_transformed.append(df_t)
            except Exception:
                pass

    # ── Save merged HKTW transformed file ─────────────────────────────────────
    if all_transformed:
        df_merged = pd.concat(all_transformed, ignore_index=True)
        save_excel(df_merged, f"KOL_transformed_HKTW_{date_start}_{date_stop}.xlsx", "KOL Data")
        logger.info(f"Merged HKTW file saved: {len(df_merged)} rows")

    run_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "=" * 60,
        "KOL DEBUG FETCH SUMMARY",
        f"Run time:   {run_time}",
        f"Markets:    {', '.join(markets_to_run)}",
        f"Date range: {date_start} → {date_stop}",
        f"FX rates:   {fx_rates}",
        "=" * 60,
    ]
    for s in all_summaries:
        lines += ["", f"── {s['market']} ──────────────────────────────────",
                  f"KOL Accounts found: {len(s['accounts'])}"]
        for a in s["accounts"]:
            lines.append(f"  {a['id']} | {a['name']}")
        lines += [
            f"Raw rows fetched:   {s['raw_rows']}",
            f"Transformed rows:   {s['transformed_rows']}",
            "Errors: " + ("none" if not s["errors"] else ""),
        ]
        for e in s["errors"]:
            lines.append(f"  !! {e}")

    lines += ["", "=" * 60]
    append_summary(lines)
    for line in lines:
        logger.info(line)

    # GitHub Step Summary
    gh_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if gh_summary:
        md = [
            "## [DEBUG] KOL Fetch Results",
            "",
            f"**Date range:** {date_start} → {date_stop}  ",
            f"**FX rates:** {fx_rates}  ",
            f"**Run time:** {run_time}",
            "",
            "| Market | Accounts | Raw rows | Transformed rows | Errors |",
            "|--------|----------|----------|-----------------|--------|",
        ]
        for s in all_summaries:
            err_icon = "✅" if not s["errors"] else f"❌ {len(s['errors'])}"
            md.append(
                f"| {s['market']} | {len(s['accounts'])} | "
                f"{s['raw_rows']:,} | {s['transformed_rows']:,} | {err_icon} |"
            )
        md += [
            "",
            "### Files in artifact",
            "- `KOL_raw_{market}_*.xlsx` — raw API response with actions JSON",
            "- `KOL_transformed_{market}_*.xlsx` — final columns incl. FX conversion",
            "- `KOL_debug_summary.txt` — account list & error log",
        ]
        with open(gh_summary, "a") as f:
            f.write("\n".join(md) + "\n")

    if upload:
        for m in markets_to_run:
            logger.info(f"[{m}] Running SharePoint upload flow...")
            new_data = debug_fetch_market(m, date_start, date_stop, fx_rates)
            # Re-use full flow
            from scripts.kol_report import fetch_market as full_fetch
            df_new   = full_fetch(m, date_start, date_stop, fx_rates)
            existing = load_existing(pa)
            merged   = merge_and_deduplicate(existing, df_new)
            pa.upload_bytes(save_to_excel(merged), SP_FOLDER, OUTPUT_FILE)
            logger.info(f"[{m}] Uploaded {len(merged)} rows")

    has_errors = any(s["errors"] for s in all_summaries)
    if has_errors:
        logger.error("Completed with errors")
        sys.exit(1)

    logger.info("Debug KOL fetch completed successfully.")


if __name__ == "__main__":
    main()
