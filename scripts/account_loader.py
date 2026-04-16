"""
HKTW Meta Auto Report - Account Loader
Loads ad account lists from SharePoint Control Panel Excel files.

Excel format (HK_Ad_Accounts.xlsx / TW_Ad_Accounts.xlsx):
Sheet: "Ad Accounts"
  | Account ID   | Account Name                    | Type | Enabled |
  | act_12345678 | EC Whisper HKTVMall CPAS HKD    | CPAS | TRUE    |
  | act_87654321 | EC Ariel TW KOL CY~TWD          | KOL  | TRUE    |
  | act_11111111 | EC Brand Old Account            | CPAS | FALSE   |
"""
import io
import logging
import pandas as pd

from config.settings import SP_PATHS, SP_CONTROL_FILES

logger = logging.getLogger(__name__)

SHEET_NAME       = "Ad Accounts"
REQUIRED_COLUMNS = ["Account ID", "Account Name", "Type", "Enabled"]


def load_accounts(
    market: str,
    pa_client,
    report_type: str | None = None,
) -> list[dict]:
    """
    Load ad accounts for a market from SharePoint Control Panel.

    Args:
        market:      "HK" or "TW"
        pa_client:   PowerAutomateClient instance
        report_type: "CPAS" | "KOL" | None (None = return all enabled accounts)

    Returns:
        List of dicts: [{"id": "act_xxx", "name": "...", "type": "CPAS"}, ...]
        Returns empty list on failure.
    """
    filename   = SP_CONTROL_FILES[market]
    sp_folder  = SP_PATHS["control_panel"]

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
        logger.error(
            f"[{market}] Control Panel file not found: {sp_folder}/{filename}\n"
            f"  → Please upload the file to SharePoint first."
        )
        return []

    try:
        df = pd.read_excel(io.BytesIO(data), sheet_name=SHEET_NAME, dtype=str)
        df.columns = [c.strip() for c in df.columns]

        missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
        if missing:
            logger.error(
                f"[{market}] {filename} is missing columns: {missing}\n"
                f"  → Found: {list(df.columns)}"
            )
            return []

        # Filter enabled only
        df["Enabled"] = df["Enabled"].str.strip().str.upper()
        df = df[df["Enabled"] == "TRUE"].copy()

        # Filter by report type if specified
        if report_type:
            df["Type"] = df["Type"].str.strip().str.upper()
            df = df[df["Type"] == report_type.upper()].copy()

        accounts = []
        for _, row in df.iterrows():
            acct_id   = str(row["Account ID"]).strip()
            acct_name = str(row["Account Name"]).strip()
            acct_type = str(row["Type"]).strip()

            # Ensure act_ prefix
            if not acct_id.startswith("act_"):
                acct_id = f"act_{acct_id}"

            accounts.append({
                "id":   acct_id,
                "name": acct_name,
                "type": acct_type,
            })

        logger.info(
            f"[{market}] Loaded {len(accounts)} enabled"
            f"{' ' + report_type if report_type else ''} accounts from {filename}"
        )
        for a in accounts:
            logger.info(f"  {a['id']} | {a['name']} | type={a['type']}")

        return accounts

    except Exception as e:
        logger.error(f"[{market}] Failed to parse {filename}: {e}")
        return []
