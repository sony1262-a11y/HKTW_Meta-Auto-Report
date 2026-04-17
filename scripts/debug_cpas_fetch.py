"""
HKTW Meta Auto Report - CPAS Debug Fetch
Fetches data for a given date range and outputs:
  1. debug_output/CPAS_raw_{market}_{date}.xlsx     ← raw API response (pre-transform)
  2. debug_output/CPAS_transformed_{market}_{date}.xlsx ← after transform (final columns)
  3. debug_output/CPAS_debug_summary.txt            ← account list, row counts, any errors

Does NOT accumulate or touch SharePoint existing data unless UPLOAD_TO_SHAREPOINT=true.
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
from scripts.cpas_transformer import transform, flatten_row, OUTPUT_COLUMNS
from scripts.cpas_report import INSIGHT_FIELDS, SP_FOLDER, OUTPUT_FILE, SHEET_NAME
from scripts.power_automate_client import PowerAutomateClient
from scripts.account_loader import load_accounts

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "debug_output")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def save_excel(df: pd.DataFrame, filename: str, sheet_name: str = "Data"):
    path = os.path.join(OUTPUT_DIR, filename)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name=sheet_name, index=False)
    logger.info(f"Saved: {path} ({len(df)} rows)")
    return path


def append_summary(lines: list[str]):
    path = os.path.join(OUTPUT_DIR, "CPAS_debug_summary.txt")
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


# ─────────────────────────────────────────────────────────────────────────────
# Per-market debug fetch
# ─────────────────────────────────────────────────────────────────────────────

def debug_fetch_market(market: str, date_start: str, date_stop: str, pa: PowerAutomateClient, time_increment: str | int = 1) -> dict:
    """
    Fetch + transform for one market.
    Returns a summary dict.
    """
    summary = {
        "market":           market,
        "accounts":         [],
        "raw_rows":         0,
        "transformed_rows": 0,
        "errors":           [],
    }

    accounts = load_accounts(market, pa, report_type="CPAS")

    summary["accounts"] = [
        {"id": a["id"], "name": a["name"], "status": "enabled"}
        for a in accounts
    ]

    logger.info(f"[{market}] CPAS accounts loaded from Control Panel: {len(accounts)}")
    for a in accounts:
        logger.info(f"  {a['id']} | {a['name']}")

    if not accounts:
        summary["errors"].append(
            f"[{market}] No CPAS accounts found in Control Panel. "
            "Check HK_Ad_Accounts.xlsx / TW_Ad_Accounts.xlsx on SharePoint."
        )
        return summary

    try:
        client = MetaAPIClient(market)
    except Exception as e:
        summary["errors"].append(f"[{market}] MetaAPIClient init failed: {e}")
        return summary

    all_raw_rows  = []
    all_flat_rows = []

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
                time_increment = time_increment,
            )
            logger.info(f"[{market}] {acct_name}: {len(rows)} raw rows")

            # Save raw JSON-style rows (scalar fields only — no nested arrays)
            for r in rows:
                flat_raw = {k: v for k, v in r.items() if not isinstance(v, list)}
                flat_raw["_actions_json"]                = json.dumps(r.get("actions", []))
                flat_raw["_action_values_json"]          = json.dumps(r.get("action_values", []))
                flat_raw["_purchase_roas_json"]          = json.dumps(r.get("purchase_roas", []))
                flat_raw["_catalog_segment_actions_json"]= json.dumps(r.get("catalog_segment_actions", []))
                flat_raw["_catalog_segment_value_json"]  = json.dumps(r.get("catalog_segment_value", []))
                all_raw_rows.append(flat_raw)

            all_flat_rows.extend(rows)

        except Exception as e:
            msg = f"[{market}] Error fetching {acct_id} ({acct_name}): {e}"
            logger.error(msg)
            summary["errors"].append(msg)

    if not all_raw_rows:
        logger.warning(f"[{market}] No rows fetched")
        return summary

    # ── Save raw output ───────────────────────────────────────────────────────
    df_raw = pd.DataFrame(all_raw_rows)
    save_excel(
        df_raw,
        f"CPAS_raw_{market}_{date_start}_{date_stop}.xlsx",
        sheet_name="Raw API Response",
    )

    # ── Creative info lookup ──────────────────────────────────────────────────
    creative_info_map: dict[str, dict] = {}
    video_url_map: dict[str, str] = {}
    story_id_map: dict[str, str] = {}
    try:
        unique_ad_ids = list({str(r.get("ad_id", "")) for r in all_flat_rows if r.get("ad_id")})

        creative_info_map = client.get_creative_info_for_ads(unique_ad_ids)
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

        resolved_images = sum(1 for v in creative_info_map.values() if v.get("image_url"))
        resolved_videos = sum(1 for v in video_url_map.values() if v)
        resolved_posts  = sum(1 for v in story_id_map.values() if "_" in v and not v.endswith("_0"))
        logger.info(f"[{market}] Images: {resolved_images}/{len(unique_ad_ids)} | "
                    f"Videos: {resolved_videos}/{len(video_ids) if video_ids else 0} | "
                    f"Post URLs: {resolved_posts}/{len(unique_ad_ids)}")
    except Exception as e:
        logger.warning(f"[{market}] Creative lookup failed — fields will be blank: {e}")

    # ── Save transformed output ───────────────────────────────────────────────
    try:
        df_transformed = transform(
            all_flat_rows,
            creative_info_map=creative_info_map,
            video_url_map=video_url_map,
            story_id_map=story_id_map,
        )
        summary["transformed_rows"] = len(df_transformed)
        save_excel(
            df_transformed,
            f"CPAS_transformed_{market}_{date_start}_{date_stop}.xlsx",
            sheet_name="Transformed",
        )
    except Exception as e:
        msg = f"[{market}] Transform error: {e}"
        logger.error(msg)
        summary["errors"].append(msg)

    return summary


# ─────────────────────────────────────────────────────────────────────────────
# Optional SharePoint upload
# ─────────────────────────────────────────────────────────────────────────────

def upload_to_sharepoint_if_requested(market: str, date_start: str, date_stop: str):
    """
    If UPLOAD_TO_SHAREPOINT=true, run the full accumulate+upload flow.
    Imports from cpas_report to avoid code duplication.
    """
    from scripts.cpas_report import fetch_market, load_existing, merge_and_deduplicate, save_to_excel

    logger.info(f"[{market}] Running full SharePoint upload flow...")
    pa       = PowerAutomateClient()
    new_data = fetch_market(market, date_start, date_stop)
    existing = load_existing(pa)
    merged   = merge_and_deduplicate(existing, new_data)
    excel_bytes = save_to_excel(merged)
    pa.upload_bytes(excel_bytes, SP_FOLDER, OUTPUT_FILE)
    logger.info(f"[{market}] SharePoint upload complete ({len(merged)} total rows)")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

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

    logger.info("=" * 60)
    logger.info(f"DEBUG CPAS FETCH")
    logger.info(f"Markets:        {markets_to_run}")
    logger.info(f"Date range:     {date_start} → {date_stop}")
    logger.info(f"Time increment: {time_increment}")
    logger.info(f"SharePoint upload: {upload}")
    logger.info("=" * 60)

    all_summaries = []
    all_transformed = []
    pa = PowerAutomateClient()
    for m in markets_to_run:
        s = debug_fetch_market(m, date_start, date_stop, pa, time_increment=time_increment)
        all_summaries.append(s)
        # Collect transformed data for merged file
        t_file = os.path.join(OUTPUT_DIR, f"CPAS_transformed_{m}_{date_start}_{date_stop}.xlsx")
        if os.path.exists(t_file):
            try:
                df_t = pd.read_excel(t_file)
                all_transformed.append(df_t)
            except Exception:
                pass

    # ── Save merged HKTW transformed file ────────────────────────────────────
    if all_transformed:
        df_merged = pd.concat(all_transformed, ignore_index=True)
        save_excel(df_merged, f"CPAS_transformed_HKTW_{date_start}_{date_stop}.xlsx", "CPAS Data")
        logger.info(f"Merged HKTW file saved: {len(df_merged)} rows")

    # ── Write summary txt ─────────────────────────────────────────────────────
    run_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "=" * 60,
        f"CPAS DEBUG FETCH SUMMARY",
        f"Run time:   {run_time}",
        f"Markets:    {', '.join(markets_to_run)}",
        f"Date range: {date_start} → {date_stop}",
        "=" * 60,
    ]
    for s in all_summaries:
        lines += [
            "",
            f"── {s['market']} ──────────────────────────────────",
            f"CPAS accounts in Control Panel: {len(s['accounts'])}",
        ]
        for a in s["accounts"]:
            lines.append(f"  {a['id']} | {a['name']}")
        lines += [
            f"Raw rows fetched:      {s['raw_rows']}",
            f"Transformed rows:      {s['transformed_rows']}",
        ]
        if s["errors"]:
            lines.append("ERRORS:")
            for e in s["errors"]:
                lines.append(f"  !! {e}")
        else:
            lines.append("Errors: none")

    lines += ["", "=" * 60]
    append_summary(lines)

    # Print to Actions log as well
    for line in lines:
        logger.info(line)

    # ── Write GitHub Step Summary ──────────────────────────────────────────────
    gh_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if gh_summary:
        md_lines = [
            "## [DEBUG] CPAS Fetch Results",
            "",
            f"**Date range:** {date_start} → {date_stop}  ",
            f"**Run time:** {run_time}",
            "",
            "| Market | Accounts | Raw rows | Transformed rows | Errors |",
            "|--------|----------|----------|-----------------|--------|",
        ]
        for s in all_summaries:
            err_count = len(s["errors"])
            err_icon  = "✅" if err_count == 0 else f"❌ {err_count}"
            md_lines.append(
                f"| {s['market']} | {len(s['accounts'])} | "
                f"{s['raw_rows']:,} | {s['transformed_rows']:,} | {err_icon} |"
            )
        md_lines += [
            "",
            "### Files in artifact",
            "- `CPAS_raw_{market}_{date_start}_{date_stop}.xlsx` — raw API response",
            "- `CPAS_transformed_{market}_{date_start}_{date_stop}.xlsx` — final columns",
            "- `CPAS_debug_summary.txt` — full account list & error log",
        ]
        with open(gh_summary, "a") as f:
            f.write("\n".join(md_lines) + "\n")

    # ── Optional SharePoint upload ────────────────────────────────────────────
    if upload:
        for m in markets_to_run:
            upload_to_sharepoint_if_requested(m, date_start, date_stop)

    # Exit with error if any market had errors
    has_errors = any(s["errors"] for s in all_summaries)
    if has_errors:
        logger.error("Completed with errors — check summary above")
        sys.exit(1)

    logger.info("Debug fetch completed successfully.")


if __name__ == "__main__":
    main()
