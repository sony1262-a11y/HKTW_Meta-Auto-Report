"""
HKTW Meta Auto Report - KOL Report
Fetches Meta KOL ad data, transforms (with FX conversion), accumulates, uploads to SharePoint.

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

from config.settings import SP_PATHS, MARKETS
from scripts.meta_api_client import MetaAPIClient
from scripts.kol_transformer import transform, OUTPUT_COLUMNS
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

KOL_KEYWORD  = "KOL"
DEDUPE_KEYS  = ["Ad Account ID", "Ad ID", "Date", "Platform", "Placement"]
SP_FOLDER    = SP_PATHS["kol"]
OUTPUT_FILE  = "HKTW_Meta_KOL_Data.xlsx"
SHEET_NAME   = "KOL Data"

# FX Rate Control Panel on SharePoint
FX_SP_FOLDER = SP_PATHS["control_panel"]
FX_FILE      = "KOL_FX_Rates.xlsx"
FX_SHEET     = "FX Rates"

# Meta insights fields to request
INSIGHT_FIELDS = [
    "account_id", "account_name",
    "campaign_id", "campaign_name",
    "adset_id", "adset_name",
    "ad_id", "ad_name",
    "impressions", "spend",
    "actions",
    "date_start", "date_stop",
]

# Breakdowns: daily + platform/placement
BREAKDOWNS = ["publisher_platform", "platform_position"]


# ─────────────────────────────────────────────────────────────────────────────
# FX Rate loader
# ─────────────────────────────────────────────────────────────────────────────

def load_fx_rates(pa: PowerAutomateClient) -> dict[str, float]:
    """
    Download FX rate file from SharePoint Control Panel.

    Expected sheet structure (FX Rates sheet):
      | Market | FX Rate (1 USD = ?) |
      | HK     | 7.78                |
      | TW     | 32.5                |

    Amount Spent (USD) = Amount Spent (local currency) ÷ FX Rate
    Returns dict: { "HK": 7.78, "TW": 32.5 }
    Returns empty dict on any failure — Amount Spent (USD) will be blank but script continues.
    """
    logger.info(f"Loading FX rates from SharePoint: {FX_FILE}")

    try:
        data = pa.download_bytes(FX_SP_FOLDER, FX_FILE)
    except EnvironmentError as e:
        logger.warning(f"PA_DOWNLOAD_URL not set — skipping FX rates. Amount Spent (USD) will be blank. ({e})")
        return {}
    except Exception as e:
        logger.warning(f"Failed to download FX file — skipping. Amount Spent (USD) will be blank. ({e})")
        return {}

    if data is None:
        logger.warning(
            f"FX rate file not found on SharePoint: {FX_SP_FOLDER}/{FX_FILE}. "
            "Amount Spent (USD) will be blank."
        )
        return {}

    try:
        df = pd.read_excel(io.BytesIO(data), sheet_name=FX_SHEET)
        df.columns = [c.strip() for c in df.columns]

        if "Market" not in df.columns or "FX Rate (1 USD = ?)" not in df.columns:
            logger.error(
                f"FX sheet must have columns 'Market' and 'FX Rate (1 USD = ?)'. "
                f"Found: {list(df.columns)}"
            )
            return {}

        rates = {}
        for _, row in df.iterrows():
            market = str(row["Market"]).strip().upper()
            try:
                rates[market] = float(row["FX Rate (1 USD = ?)"])
            except (ValueError, TypeError):
                logger.warning(f"Invalid FX rate for {market}: {row['FX Rate']}")

        logger.info(f"FX rates loaded: {rates}")
        return rates

    except Exception as e:
        logger.error(f"Failed to read FX rate file: {e}")
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# Per-market fetch
# ─────────────────────────────────────────────────────────────────────────────

def fetch_market(
    market: str,
    date_start: str,
    date_stop: str,
    fx_rates: dict[str, float],
    pa: PowerAutomateClient | None = None,
) -> pd.DataFrame:
    """Fetch all KOL ad accounts for one market and return transformed DataFrame."""
    logger.info(f"[{market}] Fetching KOL data {date_start} → {date_stop}")

    accounts = load_accounts(market, pa, report_type=None)  # all types: Brand, EC, CPAS, KOL

    if not accounts:
        logger.warning(f"[{market}] No KOL accounts found in Control Panel — skipping")
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    client   = MetaAPIClient(market)
    all_rows = []

    for acct in accounts:
        acct_id   = acct["id"]
        acct_name = acct["name"]
        logger.info(f"[{market}]   → {acct_name} ({acct_id})")

        try:
            rows = client.get_insights(
                ad_account_id = acct_id,
                date_start    = date_start,
                date_stop     = date_stop,
                level         = "ad",
                fields        = INSIGHT_FIELDS,
                breakdowns    = BREAKDOWNS,
            )
            all_rows.extend(rows)
            logger.info(f"[{market}]     {len(rows)} rows fetched")
        except Exception as e:
            logger.error(f"[{market}]     Error fetching {acct_id}: {e}")
            continue

    if not all_rows:
        logger.warning(f"[{market}] No data returned")
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    return transform(all_rows, fx_rates=fx_rates)


# ─────────────────────────────────────────────────────────────────────────────
# Accumulation logic
# ─────────────────────────────────────────────────────────────────────────────

def load_existing(pa: PowerAutomateClient) -> pd.DataFrame:
    logger.info(f"Downloading existing data: {OUTPUT_FILE}")
    data = pa.download_bytes(SP_FOLDER, OUTPUT_FILE)

    if data is None:
        logger.info("No existing file — starting fresh")
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    try:
        df = pd.read_excel(io.BytesIO(data), sheet_name=SHEET_NAME, dtype=str)
        logger.info(f"Loaded {len(df)} existing rows")
        return df
    except Exception as e:
        logger.error(f"Failed to read existing file: {e} — starting fresh")
        return pd.DataFrame(columns=OUTPUT_COLUMNS)


def merge_and_deduplicate(existing: pd.DataFrame, new_data: pd.DataFrame) -> pd.DataFrame:
    if new_data.empty:
        return existing

    combined = pd.concat([existing, new_data], ignore_index=True)

    for col in DEDUPE_KEYS:
        if col in combined.columns:
            combined[col] = combined[col].astype(str).str.strip()

    before = len(combined)
    combined = combined.drop_duplicates(subset=DEDUPE_KEYS, keep="last")
    after  = len(combined)
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
    market     = os.environ.get("MARKET", "ALL").upper()
    date_start = os.environ.get("DATE_START")
    date_stop  = os.environ.get("DATE_STOP")

    if not date_start or not date_stop:
        raise ValueError("DATE_START and DATE_STOP environment variables are required")

    markets_to_run = list(MARKETS.keys()) if market == "ALL" else [market]

    logger.info(f"KOL Report | Markets: {markets_to_run} | {date_start} → {date_stop}")

    pa       = PowerAutomateClient()
    fx_rates = load_fx_rates(pa)

    new_frames = []
    for m in markets_to_run:
        df_m = fetch_market(m, date_start, date_stop, fx_rates, pa)
        if not df_m.empty:
            new_frames.append(df_m)

    new_data = pd.concat(new_frames, ignore_index=True) if new_frames else pd.DataFrame(columns=OUTPUT_COLUMNS)
    logger.info(f"Total new rows fetched: {len(new_data)}")

    existing = load_existing(pa)
    merged   = merge_and_deduplicate(existing, new_data)

    logger.info(f"Uploading {len(merged)} rows → {SP_FOLDER}/{OUTPUT_FILE}")
    pa.upload_bytes(save_to_excel(merged), SP_FOLDER, OUTPUT_FILE)

    logger.info("KOL Report completed successfully.")
    _write_summary(markets_to_run, date_start, date_stop, len(new_data), len(merged))


def _write_summary(markets, date_start, date_stop, new_rows, total_rows):
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    lines = [
        "## KOL Report — Completed",
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
