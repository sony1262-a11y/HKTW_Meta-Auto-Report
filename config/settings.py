"""
HKTW Meta Auto Report - Central Configuration
"""
import os

# ─────────────────────────────────────────────
# Meta API
# ─────────────────────────────────────────────
META_API_VERSION = "v21.0"
META_API_BASE = f"https://graph.facebook.com/{META_API_VERSION}"

MARKETS = {
    "HK": {
        "app_id":       os.environ.get("META_HK_APP_ID"),
        "app_secret":   os.environ.get("META_HK_APP_SECRET"),
        "access_token": os.environ.get("META_HK_ACCESS_TOKEN"),
    },
    "TW": {
        "app_id":       os.environ.get("META_TW_APP_ID"),
        "app_secret":   os.environ.get("META_TW_APP_SECRET"),
        "access_token": os.environ.get("META_TW_ACCESS_TOKEN"),
    },
}

# ─────────────────────────────────────────────
# SharePoint
# ─────────────────────────────────────────────
SHAREPOINT_SITE = "PGHKTWDigitalTeam-COETeam"

SP_PATHS = {
    "control_panel": "/Shared Documents/COE Team/Media Report/Control_Panel",
    "cpas":          "/Shared Documents/COE Team/Media Report/HKTW_Meta CPAS",
    "kol":           "/Shared Documents/COE Team/Media Report/HKTW_Meta KOL",
    "all":           "/Shared Documents/COE Team/Media Report/HKTW_Meta All",
}

# Control Panel files (Ad Account lists + Token sheets)
SP_CONTROL_FILES = {
    "HK": "HK_Ad_Accounts.xlsx",
    "TW": "TW_Ad_Accounts.xlsx",
}

# ─────────────────────────────────────────────
# Power Automate
# ─────────────────────────────────────────────
PA_UPLOAD_URL   = os.environ.get("PA_UPLOAD_URL")
PA_DOWNLOAD_URL = os.environ.get("PA_DOWNLOAD_URL")

# ─────────────────────────────────────────────
# Report Types
# ─────────────────────────────────────────────
REPORT_TYPES = ["CPAS", "KOL"]
