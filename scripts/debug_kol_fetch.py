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
    KOL_KEYWORD, INSIGHT_FIELDS, BREAKDOWNS,
    SP_FOLDER, OUTPUT_FILE, SHEET_NAME,
    load_fx_rates, load_existing, merge_and_deduplicate, save_to_excel,
)
from scripts.power_automate_client import PowerAutomateClient

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
) -> dict:
    summary = {
        "market":            market,
        "accounts":          [],
        "raw_rows":          0,
        "transformed_rows":  0,
        "errors":            [],
    }

    try:
        client   = MetaAPIClient(market)
        accounts = client.get_ad_accounts()
    except Exception as e:
        summary["errors"].append(f"[{market}] get_ad_accounts failed: {e}")
        return summary

    kol_accounts = [a for a in accounts if KOL_KEYWORD in a.get("name", "")]
    summary["accounts"] = [
        {"id": a["id"], "name": a.get("name", ""), "status": a.get("account_status")}
        for a in kol_accounts
    ]

    logger.info(f"[{market}] {len(kol_accounts)} KOL accounts:")
    for a in kol_accounts:
        logger.info(f"  {a['id']} | {a.get('name','')}")

    all_raw_rows  = []
    all_full_rows = []

    for acct in kol_accounts:
        acct_id   = acct["id"]
        acct_name = acct.get("name", acct_id)
        try:
            rows = client.get_insights(
                ad_account_id = acct_id,
                date_start    = date_start,
                date_stop     = date_stop,
                level         = "ad",
                fields        = INSIGHT_FIELDS,
                breakdowns    = BREAKDOWNS,
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

    # Save transformed
    try:
        df_t = transform(all_full_rows, fx_rates=fx_rates)
        summary["transformed_rows"] = len(df_t)
        save_excel(df_t, f"KOL_transformed_{market}_{date_start}_{date_stop}.xlsx", "Transformed")
    except Exception as e:
        msg = f"[{market}] Transform error: {e}"
        logger.error(msg)
        summary["errors"].append(msg)

    return summary


def main():
    market     = os.environ.get("MARKET", "ALL").upper()
    date_start = os.environ.get("DATE_START")
    date_stop  = os.environ.get("DATE_STOP")
    upload     = os.environ.get("UPLOAD_TO_SHAREPOINT", "false").lower() == "true"

    if not date_start or not date_stop:
        raise ValueError("DATE_START and DATE_STOP are required")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    markets_to_run = list(MARKETS.keys()) if market == "ALL" else [market]

    pa       = PowerAutomateClient()
    fx_rates = load_fx_rates(pa)

    logger.info("=" * 60)
    logger.info("DEBUG KOL FETCH")
    logger.info(f"Markets:    {markets_to_run}")
    logger.info(f"Date range: {date_start} → {date_stop}")
    logger.info(f"FX rates:   {fx_rates}")
    logger.info(f"SharePoint upload: {upload}")
    logger.info("=" * 60)

    all_summaries = []
    for m in markets_to_run:
        s = debug_fetch_market(m, date_start, date_stop, fx_rates)
        all_summaries.append(s)

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
            lines.append(f"  {a['id']} | {a['name']} | status={a['status']}")
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
