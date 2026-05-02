"""HKTW Meta Auto Report - Token Manager"""
import os, sys, logging
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import MARKETS
from scripts.meta_api_client import MetaAPIClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)
WARN_DAYS = 10
CRIT_DAYS = 3

def check_market_token(market):
    result = {"market": market, "status": "unknown", "days_left": None, "expires_at": None, "message": ""}
    try:
        client = MetaAPIClient(market)
        info = client.get_token_info()
        if not info:
            result.update({"status": "error", "message": "debug_token returned empty response"})
            return result
        if not info.get("is_valid", False):
            result.update({"status": "invalid", "message": info.get("error", {}).get("message", "Token invalid")})
            return result
        expires_at = info.get("expires_at")
        if expires_at and expires_at != 0:
            expiry_dt = datetime.utcfromtimestamp(expires_at)
            days_left = (expiry_dt - datetime.utcnow()).days
            result["days_left"] = days_left
            result["expires_at"] = expiry_dt.strftime("%Y-%m-%d")
            if days_left <= CRIT_DAYS:
                result.update({"status": "critical", "message": f"Token expires in {days_left} days — renew IMMEDIATELY"})
            elif days_left <= WARN_DAYS:
                result.update({"status": "warning", "message": f"Token expires in {days_left} days — renew soon"})
            else:
                result.update({"status": "ok", "message": f"Token valid for {days_left} days"})
        else:
            result.update({"status": "ok", "message": "Non-expiring token (system user)"})
    except EnvironmentError as e:
        result.update({"status": "missing", "message": str(e)})
    except Exception as e:
        result.update({"status": "error", "message": str(e)})
    return result

def check_all_tokens():
    results = []
    for market in MARKETS.keys():
        logger.info(f"Checking token for market: {market}")
        r = check_market_token(market)
        results.append(r)
        log_level = {"ok": 20, "warning": 30, "critical": 40, "invalid": 40, "missing": 40, "error": 40}.get(r["status"], 20)
        logger.log(log_level, f"[{market}] {r['status'].upper()} — {r['message']}")
    return results

def write_github_summary(results):
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path: return
    status_emoji = {"ok": "✅", "warning": "⚠️", "critical": "🚨", "invalid": "❌", "missing": "❌", "error": "❌"}
    lines = ["## Token Health Check", "", f"Run time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}", "",
             "| Market | Status | Expiry | Message |", "|--------|--------|--------|---------|"]
    for r in results:
        emoji = status_emoji.get(r["status"], "❓")
        lines.append(f"| {r['market']} | {emoji} {r['status'].upper()} | {r['expires_at'] or 'N/A'} | {r['message']} |")
    with open(summary_path, "a") as f:
        f.write("\n".join(lines) + "\n")

if __name__ == "__main__":
    results = check_all_tokens()
    write_github_summary(results)
    bad = [r for r in results if r["status"] in ("critical","invalid","missing","error")]
    if bad:
        logger.error("One or more tokens require attention.")
        sys.exit(1)
    logger.info("All tokens healthy.")
