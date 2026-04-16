"""
HKTW Meta Auto Report - KOL Data Transformer
Parses Meta naming conventions and derives all required KOL report columns.
"""
import re
import logging
import pandas as pd

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

CHANNEL_KEYWORDS = {
    "HKTVMall":  "HKTVMall",
    "Momo":      "Momo",
    "momo":      "Momo",
    "iWAT":      "Watsons",
    "Watsons":   "Watsons",
    "Sephora":   "Sephora",
    "PChome":    "PChome",
    "Shopee":    "Shopee",
    "ParknShop": "ParknShop",
    "Mannings":  "Mannings",
}

# Brand → (Category Type, Category)
# Source: mapping table provided by Alishia Chang
BRAND_CATEGORY_MAPPING: dict[str, tuple[str, str]] = {
    "Whisper":         ("Brand", "Fem Care"),
    "Ariel":           ("Brand", "Fabric Care"),
    "Hair Recipe":     ("Brand", "Hair Care"),
    "Pampers":         ("Brand", "Baby Care"),
    "Febreze":         ("Brand", "Home Care"),
    "Lenor":           ("Brand", "Fabric Care"),
    "Olay":            ("Brand", "Skin Care"),
    "Oral-B":          ("Brand", "Oral Care"),
    "Gillette":        ("Brand", "Grooming"),
    "EC PTN":          ("EC",    "EC Hair Care"),
    "EC Pampers":      ("EC",    "EC Baby Care"),
    "EC HR":           ("EC",    "EC Hair Care"),
    "Pantene":         ("Brand", "Hair Care"),
    "EC Crest":        ("EC",    "EC Oral Care"),
    "Herbal Essences": ("Brand", "Hair Care"),
    "H&S":             ("Brand", "Hair Care"),
    "EC Gillette":     ("EC",    "EC Grooming"),
    "EC Olay":         ("EC",    "EC Skin Care"),
    "Pert":            ("Brand", "Hair Care"),
    "Braun":           ("Brand", "Grooming"),
    "EC H&S":          ("EC",    "EC Hair Care"),
    "EC Hair Recipe":  ("EC",    "EC Hair Care"),
    "EC Ariel":        ("EC",    "EC Fabric Care"),
    "EC Lenor":        ("EC",    "EC Fabric Care"),
    "EC Pantene":      ("EC",    "EC Hair Care"),
    "EC Braun":        ("EC",    "EC Grooming"),
    "Crest":           ("Brand", "Oral Care"),
    "VS":              ("Brand", "Hair Care"),
    "OralB":           ("Brand", "Oral Care"),
    "First Aid Beauty":("",      "Skin Care"),
}

# OB~ raw value → human-readable Objective label
# Only Whisper (BA-RH/BA-ARL→Awareness), Ariel (CW-LC→Traffic),
# Hair Recipe (EN-TP/BA-TP→Video Views) have defined mappings.
# All other OB~ values pass through as-is.
OBJECTIVE_MAPPING: dict[str, str] = {
    "BA-RH":  "Awareness",
    "BA-ARL": "Awareness",
    "CW-LC":  "Traffic",
    "EN-TP":  "Video Views",
    "BA-TP":  "Video Views",
}


# ─────────────────────────────────────────────────────────────────────────────
# Shared parsers (same logic as CPAS)
# ─────────────────────────────────────────────────────────────────────────────

def get_market_from_account(account_name: str) -> str:
    if not isinstance(account_name, str):
        return ""
    if "HKD" in account_name:
        return "HK"
    if "TWD" in account_name:
        return "TW"
    return ""


def get_fy(date: pd.Timestamp) -> str:
    if pd.isna(date):
        return ""
    year, month = date.year, date.month
    if month >= 7:
        fy_start, fy_end = year, year + 1
    else:
        fy_start, fy_end = year - 1, year
    return f"FY{str(fy_start)[2:]}{str(fy_end)[2:]}"


def get_an_value(campaign_name: str) -> str:
    """Brand = value between _AN~ and _CN~."""
    if not isinstance(campaign_name, str):
        return ""
    m = re.search(r"_AN~(.+?)_CN~", campaign_name)
    return m.group(1).strip() if m else ""


# ─────────────────────────────────────────────────────────────────────────────
# KOL-specific parsers
# ─────────────────────────────────────────────────────────────────────────────

def get_boutique(campaign_name: str) -> str:
    """
    Boutique = value between _CN~ and @.
    e.g. "_CN~Ariel@FabricCare..." → "Ariel"
    """
    if not isinstance(campaign_name, str):
        return ""
    m = re.search(r"_CN~([^@_]+)@", campaign_name)
    return m.group(1).strip() if m else ""


def get_objective(campaign_name: str) -> str:
    """
    Objective = value between _OB~ and _RT~.
    e.g. "_OB~CW-LC_RT~Auction" → "CW-LC"
    """
    if not isinstance(campaign_name, str):
        return ""
    m = re.search(r"_OB~(.+?)_RT~", campaign_name)
    return m.group(1).strip() if m else ""


def get_campaign(campaign_name: str) -> str:
    """
    Campaign = value between _CN~ and _YR~.
    e.g. "_CN~Ariel@FabricCareKOLJun'25:崇崇(Post1)#6/11-6/18_YR~2025"
         → "Ariel@FabricCareKOLJun'25:崇崇(Post1)#6/11-6/18"
    """
    if not isinstance(campaign_name, str):
        return ""
    m = re.search(r"_CN~(.+?)_YR~", campaign_name)
    return m.group(1).strip() if m else ""


def get_ta(adset_name: str) -> str:
    """
    TA = contents of the first [...] in Ad Set Name.
    e.g. "_ST~INT[P25-54 & [...]]_AG~[...]" → "P25-54 & [...]"
    Note: handles nested brackets — takes everything up to the matching close bracket.
    """
    if not isinstance(adset_name, str):
        return ""
    m = re.search(r"\[(.+)\](?:_AG~)", adset_name)
    if m:
        return m.group(1).strip()
    # fallback: first [...] if _AG~ pattern not found
    m = re.search(r"\[([^\]]+)\]", adset_name)
    return m.group(1).strip() if m else ""


def get_creative_name(ad_name: str) -> str:
    """
    Creative Name = everything after _AS~ in Ad Name.
    e.g. "..._AS~Ad1-MO-LIQ:CLTPR#Chung-Chungalwayson-MO-0611-display"
         → "Ad1-MO-LIQ:CLTPR#Chung-Chungalwayson-MO-0611-display"
    """
    if not isinstance(ad_name, str):
        return ""
    m = re.search(r"_AS~(.+)$", ad_name)
    return m.group(1).strip() if m else ""


def get_creative_tag(creative_name: str) -> str:
    """
    Creative Tag = everything after the first : in Creative Name.
    e.g. "Ad1-MO-LIQ:CLTPR#Chung-Chungalwayson-MO-0611-display"
         → "CLTPR#Chung-Chungalwayson-MO-0611-display"
    """
    if not isinstance(creative_name, str) or ":" not in creative_name:
        return ""
    return creative_name.split(":", 1)[1].strip()


def get_p2p(creative_name: str) -> str:
    """
    P2P = value between : and # in Creative Name.
    e.g. "Ad1-MO-LIQ:CLTPR#Chung-..." → "CLTPR"
    Returns "" if either : or # not found.
    """
    if not isinstance(creative_name, str):
        return ""
    m = re.search(r":([^#]+)#", creative_name)
    return m.group(1).strip() if m else ""


def get_creative_code(creative_tag: str) -> str:
    """
    Creative Code = value between 1st and 2nd '-' in Creative Tag.
    Creative Tag format: {KOL_name}-{CreativeCode}-{Channel}-{DateCode}-{Format}
    e.g. "Chung-Chungalwayson-MO-0611-display" → "Chungalwayson"
    """
    if not isinstance(creative_tag, str):
        return ""
    # Strip everything before # (the P2P prefix)
    tag = creative_tag.split("#", 1)[-1] if "#" in creative_tag else creative_tag
    parts = tag.split("-")
    return parts[1].strip() if len(parts) > 1 else ""


def get_channel_from_tag(creative_tag: str) -> str:
    """
    Channel = value between 2nd and 3rd '-' in Creative Tag (after # prefix).
    e.g. "Chung-Chungalwayson-MO-0611-display" → "MO"
    """
    if not isinstance(creative_tag, str):
        return ""
    tag = creative_tag.split("#", 1)[-1] if "#" in creative_tag else creative_tag
    parts = tag.split("-")
    return parts[2].strip() if len(parts) > 2 else ""


def get_creative_format(creative_tag: str) -> str:
    """
    Creative Format = value after the last '-' in Creative Tag (after # prefix).
    e.g. "Chung-Chungalwayson-MO-0611-display" → "display"
    """
    if not isinstance(creative_tag, str) or not creative_tag:
        return ""
    tag = creative_tag.split("#", 1)[-1] if "#" in creative_tag else creative_tag
    return tag.rsplit("-", 1)[-1].strip()


def map_objective(raw_ob: str) -> str:
    """
    Map raw OB~ value to human-readable Objective label.
    Falls back to raw value if not in mapping (so no data is lost).

    e.g. "CW-LC"  → "Traffic"
         "BA-RH"  → "Awareness"
         "EN-TP"  → "Video Views"
         "XY-ZZ"  → "XY-ZZ"   (passthrough)
    """
    if not isinstance(raw_ob, str) or not raw_ob:
        return ""
    return OBJECTIVE_MAPPING.get(raw_ob, raw_ob)


def get_category_type_and_category(brand: str) -> tuple[str, str]:
    """Lookup Category Type and Category from Brand. Returns ('', '') if not mapped."""
    return BRAND_CATEGORY_MAPPING.get(brand, ("", ""))


# ─────────────────────────────────────────────────────────────────────────────
# Meta API field → DataFrame column mapping
# ─────────────────────────────────────────────────────────────────────────────

ACTION_MAP = {
    "link_click":                               "Link Clicks",
    "outbound_click":                           "Outbound Clicks",
    "video_view":                               "3s Views",
    "video_thruplay_watched":                   "Thruplay",
    "video_p25_watched_actions":                "View at 25%",
    "video_p50_watched_actions":                "View at 50%",
    "video_p75_watched_actions":                "View at 75%",
    "video_p100_watched_actions":               "View at 100%",
    "post_reaction":                            "Reaction",
    "like":                                     "Like",
    "comment":                                  "Comment",
    "post":                                     "Share",
    "onsite_web_save":                          "Save",
    "post_save":                                "Save",
}


def flatten_row(row: dict) -> dict:
    """Flatten a single Meta API insights row into a flat dict."""
    flat = {
        "Ad Account ID":    row.get("account_id", ""),
        "Ad Account Name":  row.get("account_name", ""),
        "Campaign ID":      row.get("campaign_id", ""),
        "Campaign Name":    row.get("campaign_name", ""),
        "Ad Set ID":        row.get("adset_id", ""),
        "Ad Set Name":      row.get("adset_name", ""),
        "Ad ID":            row.get("ad_id", ""),
        "Ad Name":          row.get("ad_name", ""),
        "Page Name":        row.get("page_name", ""),
        "Campaign Start Date": row.get("campaign_start_time", ""),
        "Campaign End Date":   row.get("campaign_stop_time", ""),
        "Campaign Budget":     row.get("campaign_budget", ""),
        "Amount Spent (local currency)": float(row.get("spend", 0) or 0),
        "Impressions":         int(row.get("impressions", 0) or 0),
        "Day":                 row.get("date_start", ""),
        "Platform":            row.get("publisher_platform", ""),
        "Placement":           row.get("platform_position", ""),
    }

    # Zero-fill action columns
    for col in set(ACTION_MAP.values()):
        flat[col] = 0.0

    for item in row.get("actions", []):
        action_type = item.get("action_type", "")
        if action_type in ACTION_MAP:
            col = ACTION_MAP[action_type]
            try:
                # Save can appear twice (onsite_web_save + post_save) — accumulate
                flat[col] = flat.get(col, 0.0) + float(item.get("value", 0))
            except (ValueError, TypeError):
                pass

    return flat


# ─────────────────────────────────────────────────────────────────────────────
# Main transformer
# ─────────────────────────────────────────────────────────────────────────────

def transform(raw_rows: list[dict], fx_rates: dict[str, float] | None = None) -> pd.DataFrame:
    """
    Transform raw Meta API insight rows into the final KOL report DataFrame.

    Args:
        raw_rows:  List of dicts from MetaAPIClient.get_insights()
        fx_rates:  { "HK": 7.78, "TW": 32.5, ... }
                   Meta API returns spend in local currency.
                   Amount Spent (USD) = Amount Spent (local currency) ÷ FX Rate
                   If None, Amount Spent (USD) column is left blank.

    Returns:
        DataFrame with all required columns in final output order.
    """
    if not raw_rows:
        logger.warning("transform() received empty raw_rows")
        return _empty_dataframe()

    flat = [flatten_row(r) for r in raw_rows]
    df   = pd.DataFrame(flat)

    # ── Date fields ──────────────────────────────────────────────────────────
    df["Day"] = pd.to_datetime(df["Day"], errors="coerce")
    df["Market"]  = df["Ad Account Name"].apply(get_market_from_account)
    df["FY"]      = df["Day"].apply(get_fy)
    df["Year"]    = df["Day"].dt.year.astype("Int64").astype(str).replace("<NA>", "")
    df["Month"]   = df["Day"].dt.month.astype("Int64").astype(str).replace("<NA>", "")
    df["Date"]    = df["Day"].dt.strftime("%Y-%m-%d").fillna("")

    # ── Campaign Name derived ─────────────────────────────────────────────────
    df["Brand"]     = df["Campaign Name"].apply(get_an_value)
    df["Boutique"]  = df["Campaign Name"].apply(get_boutique)
    df["Objective"] = df["Campaign Name"].apply(get_objective).apply(map_objective)
    df["Campaign"]  = df["Campaign Name"].apply(get_campaign)

    # ── Ad Set Name derived ───────────────────────────────────────────────────
    df["TA"] = df["Ad Set Name"].apply(get_ta)

    # ── Ad Name / Creative derived ────────────────────────────────────────────
    df["Creative Name"]   = df["Ad Name"].apply(get_creative_name)
    df["Creative Tag"]    = df["Creative Name"].apply(get_creative_tag)
    df["P2P"]             = df["Creative Name"].apply(get_p2p)
    df["Creative Code"]   = df["Creative Tag"].apply(get_creative_code)
    df["Channel"]         = df["Creative Tag"].apply(get_channel_from_tag)
    df["Creative Format"] = df["Creative Tag"].apply(get_creative_format)

    # ── Category (from Brand mapping) ─────────────────────────────────────────
    cat_lookup          = df["Brand"].apply(get_category_type_and_category)
    df["Category Type"] = cat_lookup.apply(lambda x: x[0])
    df["Category"]      = cat_lookup.apply(lambda x: x[1])

    # ── Amount Spent (USD) — local currency ÷ FX Rate ───────────────────────
    if fx_rates:
        def to_usd(r):
            rate = fx_rates.get(r["Market"], 0)
            if rate and rate > 0:
                return round(r["Amount Spent (local currency)"] / rate, 2)
            return ""
        df["Amount Spent (USD)"] = df.apply(to_usd, axis=1)
    else:
        df["Amount Spent (USD)"] = ""

    # ── Final column order ────────────────────────────────────────────────────
    return df[OUTPUT_COLUMNS].reset_index(drop=True)


def _empty_dataframe() -> pd.DataFrame:
    return pd.DataFrame(columns=OUTPUT_COLUMNS)


# ─────────────────────────────────────────────────────────────────────────────
# Output column order
# ─────────────────────────────────────────────────────────────────────────────

OUTPUT_COLUMNS = [
    # ── Derived ───────────────────────────────────────────────────────────────
    "Market",
    "FY",
    "Year",
    "Month",
    "Date",
    "Category Type",
    "Category",
    "Brand",
    "Boutique",
    "Objective",
    "Campaign",
    "TA",
    "Creative Name",
    "Creative Tag",
    "Creative Code",
    "Creative Format",
    "P2P",
    "Channel",
    # ── Raw Meta fields ───────────────────────────────────────────────────────
    "Ad Account ID",
    "Ad Account Name",
    "Campaign ID",
    "Campaign Name",
    "Ad Set ID",
    "Ad Set Name",
    "Ad ID",
    "Ad Name",
    "Page Name",
    "Platform",
    "Placement",
    "Campaign Start Date",
    "Campaign End Date",
    "Campaign Budget",
    "Amount Spent (local currency)",
    "Amount Spent (USD)",
    "Impressions",
    "Link Clicks",
    "Outbound Clicks",
    "3s Views",
    "Thruplay",
    "View at 25%",
    "View at 50%",
    "View at 75%",
    "View at 100%",
    "Reaction",
    "Like",
    "Comment",
    "Share",
    "Save",
]
