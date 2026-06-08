"""
HKTW Meta Auto Report - Account Loader
Reads account list from local control_panel/ folder in the repo.
No dependency on Power Automate download.
"""
import io
import os
import logging
import pandas as pd

logger = logging.getLogger(__name__)
SHEET_NAME       = "Ad Accounts"
REQUIRED_COLUMNS = ["Account ID", "Account Name", "Type", "Enabled"]

# Resolve control_panel path relative to repo root
_REPO_ROOT    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTROL_PANEL = os.path.join(_REPO_ROOT, "control_panel")

CONTROL_FILES = {
    "HK": "HK_Ad_Accounts.xlsx",
    "TW": "TW_Ad_Accounts.xlsx",
}


def load_accounts(market: str, pa_client=None, report_type: str | None = None) -> list[dict]:
    """
    Load enabled ad accounts for the given market from the local control_panel/ folder.
    pa_client is accepted for API compatibility but ignored.
    """
    filename  = CONTROL_FILES.get(market)
    if not filename:
        logger.error(f"[{market}] No control file defined for market '{market}'")
        return []

    filepath = os.path.join(CONTROL_PANEL, filename)
    if not os.path.exists(filepath):
        logger.error(f"[{market}] Control Panel file not found: {filepath}")
        logger.error(f"[{market}] Please add {filename} to the control_panel/ folder in the repo")
        return []

    logger.info(f"[{market}] Loading account list from: control_panel/{filename}")
    try:
        df = pd.read_excel(filepath, sheet_name=SHEET_NAME, dtype=str)
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
