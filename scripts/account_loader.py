"""
HKTW Meta Auto Report - Account Loader
"""
import io
import logging
import pandas as pd
from config.settings import SP_PATHS, SP_CONTROL_FILES

logger = logging.getLogger(__name__)
SHEET_NAME       = "Ad Accounts"
REQUIRED_COLUMNS = ["Account ID", "Account Name", "Type", "Enabled"]


def load_accounts(market: str, pa_client, report_type: str | None = None) -> list[dict]:
    filename  = SP_CONTROL_FILES[market]
    sp_folder = SP_PATHS["control_panel"]
    logger.info(f"[{market}] Loading account list from SharePoint: {filename}")
    try:
        data = pa_client.download_bytes(sp_folder, filename)
    except EnvironmentError as e:
        logger.error(f"[{market}] PA_DOWNLOAD_URL not set: {e}")
        return []
    except Exception as e:
        logger.error(f"[{market}] Failed to download {filename}: {e}")
        return []
    if data is None:
        logger.error(f"[{market}] Control Panel file not found: {sp_folder}/{filename}")
        return []
    try:
        df = pd.read_excel(io.BytesIO(data), sheet_name=SHEET_NAME, dtype=str)
        df.columns = [c.strip() for c in df.columns]
        missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
        if missing:
            logger.error(f"[{market}] {filename} is missing columns: {missing}")
            return []
        df["Enabled"] = df["Enabled"].str.strip().str.upper()
        df = df[df["Enabled"] == "TRUE"].copy()
        if report_type:
            df["Type"] = df["Type"].str.strip().str.upper()
            df = df[df["Type"] == report_type.upper()].copy()
        accounts = []
        for _, row in df.iterrows():
            acct_id   = str(row["Account ID"]).strip()
            acct_name = str(row["Account Name"]).strip()
            acct_type = str(row["Type"]).strip()
            if not acct_id.startswith("act_"):
                acct_id = f"act_{acct_id}"
            # Large_Account: if column exists and value is TRUE, mark as large
            large = False
            if "Large_Account" in df.columns:
                val = str(row.get("Large_Account", "")).strip().upper()
                large = val == "TRUE"
            accounts.append({
                "id":    acct_id,
                "name":  acct_name,
                "type":  acct_type,
                "large": large,
            })
        large_count = sum(1 for a in accounts if a["large"])
        logger.info(
            f"[{market}] Loaded {len(accounts)} enabled"
            f"{' ' + report_type if report_type else ''} accounts"
            f" ({large_count} large) from {filename}"
        )
        for a in accounts:
            flag = " [LARGE]" if a["large"] else ""
            logger.info(f"  {a['id']} | {a['name']} | type={a['type']}{flag}")
        return accounts
    except Exception as e:
        logger.error(f"[{market}] Failed to parse {filename}: {e}")
        return []
