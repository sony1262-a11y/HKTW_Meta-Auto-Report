# Control Panel

Place the following files in this folder:

| File | Sheet | Purpose |
|---|---|---|
| `HK_Ad_Accounts.xlsx` | `Ad Accounts` | HK ad account list |
| `TW_Ad_Accounts.xlsx` | `Ad Accounts` | TW ad account list |
| `KOL_FX_Rates.xlsx` | `FX Rates` | USD conversion rates |

## Ad Accounts columns
- `Account ID` — Meta ad account ID (with or without `act_` prefix)
- `Account Name` — Display name
- `Type` — CPAS / KOL / Brand / EC
- `Enabled` — TRUE / FALSE
- `Large_Account` — (optional) TRUE for accounts with very large data volume (e.g. Momo CPAS); these will use day-by-day fetching to avoid HTTP 500 errors

## Notes
- Changes to these files take effect immediately on the next workflow run after commit+push to the repo
- These files are NOT uploaded to SharePoint; they live only in GitHub
