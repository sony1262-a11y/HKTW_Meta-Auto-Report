import os
SP_PATHS = {"all": "", "cpas": "", "kol": "", "control_panel": ""}
SP_CONTROL_FILES = {"HK": "HK_Ad_Accounts.xlsx", "TW": "TW_Ad_Accounts.xlsx"}
MARKETS = {"HK": {}, "TW": {}}
META_API_VERSION = "v21.0"
META_API_BASE = f"https://graph.facebook.com/{META_API_VERSION}"
PA_UPLOAD_URL = os.environ.get("PA_UPLOAD_URL")
PA_DOWNLOAD_URL = os.environ.get("PA_DOWNLOAD_URL")
