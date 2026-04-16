# HKTW Meta Auto Report

Automated Meta Ads data fetch for HK & TW markets — CPAS and KOL quarterly review reports.

## Architecture

```
GitHub Actions (workflow_dispatch)
    ↓ triggered by Power Automate
Meta Graph API  →  Python scripts  →  Power Automate  →  SharePoint
```

## Repo Structure

```
HKTW_Meta_Auto_Report/
├── config/
│   └── settings.py              # All paths, market config, SharePoint URLs
├── scripts/
│   ├── meta_api_client.py       # Meta Graph API wrapper (HK/TW market switching)
│   ├── token_manager.py         # Token health check & expiry warnings
│   ├── power_automate_client.py # SharePoint upload/download
│   ├── cpas_report.py           # CPAS report logic  ← Phase 2
│   └── kol_report.py            # KOL report logic   ← Phase 2
└── .github/workflows/
    ├── token_health_check.yml   # Weekly token check (Monday 09:00 TWN)
    ├── fetch_cpas_report.yml    # CPAS fetch (workflow_dispatch)
    └── fetch_kol_report.yml     # KOL fetch  (workflow_dispatch)
```

## GitHub Secrets Required

| Secret | Description |
|--------|-------------|
| `META_HK_APP_ID` | HK Meta App ID |
| `META_HK_APP_SECRET` | HK Meta App Secret |
| `META_HK_ACCESS_TOKEN` | HK Long-lived access token (~60 days) |
| `META_TW_APP_ID` | TW Meta App ID |
| `META_TW_APP_SECRET` | TW Meta App Secret |
| `META_TW_ACCESS_TOKEN` | TW Long-lived access token (~60 days) |
| `PA_UPLOAD_URL` | Power Automate HTTP trigger — SharePoint upload |
| `PA_DOWNLOAD_URL` | Power Automate HTTP trigger — SharePoint download |

## SharePoint Output

```
PGHKTWDigitalTeam-COETeam / Shared Documents / COE Team / Media Report /
├── Control_Panel/
│   ├── HK_Ad_Accounts.xlsx
│   └── TW_Ad_Accounts.xlsx
├── HKTW_Meta CPAS/
│   ├── HK/
│   └── TW/
└── HKTW_Meta KOL/
    ├── HK/
    └── TW/
```

## Token Management

- HK and TW tokens each expire after ~60 days
- Weekly health check runs every Monday, warns at ≤10 days remaining
- Renew via Meta Business Manager → System Users → Generate Token

## Triggering Reports

Workflows are `workflow_dispatch` only — triggered manually or via Power Automate HTTP action.

Parameters:
- `market`: `HK` / `TW` / `ALL`
- `date_start`: `YYYY-MM-DD`
- `date_stop`: `YYYY-MM-DD`
