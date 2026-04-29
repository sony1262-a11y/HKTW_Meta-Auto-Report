"""
HKTW Meta Auto Report - CPAS Data Transformer
Parses Meta naming conventions and derives all required report columns.
"""
import re
import logging
import pandas as pd
from datetime import datetime

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




# ─────────────────────────────────────────────────────────────────────────────
# Individual field parsers
# ─────────────────────────────────────────────────────────────────────────────

def parse_token(text: str, key: str) -> str:
    """
    Extract value for a `KEY~value` token from a naming string.
    Stops at the next `_` or end of string.

    e.g. parse_token("CP~PG007787_MK~HK_OB~SALES", "MK") → "HK"
    """
    if not isinstance(text, str):
        return ""
    pattern = rf"(?:^|_){re.escape(key)}~([^_]+)"
    m = re.search(pattern, text)
    return m.group(1).strip() if m else ""


def get_an_value(campaign_name: str) -> str:
    """
    Extract value between _AN~ and _CN~ in Campaign Name.
    Used for both Category and Funding Source (same value).

    e.g. "CP~PG007787_AN~EC Whisper_CN~Whisper@..." → "EC Whisper"
    """
    if not isinstance(campaign_name, str):
        return ""
    m = re.search(r"_AN~(.+?)_CN~", campaign_name)
    return m.group(1).strip() if m else ""


def get_market_from_account(account_name: str) -> str:
    """
    Derive Market from the Account Name currency token.
    HKD → HK, TWD → TW.
    Falls back to MK~ token in account name if CY~ not present.
    """
    if not isinstance(account_name, str):
        return ""
    if "HKD" in account_name:
        return "HK"
    if "TWD" in account_name:
        return "TW"
    return ""


def get_fy(date: pd.Timestamp) -> str:
    """
    FY runs July–June.
    e.g. 2023-08 → FY2324, 2024-01 → FY2324, 2024-07 → FY2425
    """
    if pd.isna(date):
        return ""
    year  = date.year
    month = date.month
    if month >= 7:
        fy_start = year
        fy_end   = year + 1
    else:
        fy_start = year - 1
        fy_end   = year
    return f"FY{str(fy_start)[2:]}{str(fy_end)[2:]}"


def get_brand(campaign_name: str) -> str:
    """
    Brand = value between _CN~ and the first @ in CN~ segment.
    Returns "" if @ not found.

    e.g. "...CN~Whisper@HKTVMall..." → "Whisper"
    """
    if not isinstance(campaign_name, str):
        return ""
    m = re.search(r"_CN~([^@_]+)@", campaign_name)
    return m.group(1).strip() if m else ""


def get_campaign(campaign_name: str) -> str:
    """
    Campaign = value between _CN~ and _YR~.

    e.g. "...CN~Whisper@HKTVMall x Fem..._YR~2023..." → "Whisper@HKTVMall x Fem..."
    """
    if not isinstance(campaign_name, str):
        return ""
    m = re.search(r"_CN~(.+?)_YR~", campaign_name)
    return m.group(1).strip() if m else ""


def get_optimization(campaign_name: str) -> str:
    """
    Optimization = value between :( and )_YR~.
    Only matches the pattern :(value)_YR~ — ignores plain (value) without colon prefix.
    Returns "" if pattern not found.

    e.g. "...CPAS FY2324:(ViewContent)_YR~..." → "ViewContent"
    e.g. "...TPR (Mega Sale)Nov'23_YR~..."     → ""  (no colon prefix)
    """
    if not isinstance(campaign_name, str):
        return ""
    m = re.search(r":\((.+?)\)_YR~", campaign_name)
    return m.group(1).strip() if m else ""


def get_ta_name(adset_name: str) -> str:
    """
    TA Name = contents of the FIRST [...] in the Ad Set Name.

    e.g. "...ST~CA[P 18-65+,(Purchase) Viewed+ATC...]_AG~[...]..." → "P 18-65+,(Purchase) Viewed+ATC..."
    """
    if not isinstance(adset_name, str):
        return ""
    m = re.search(r"\[([^\]]+)\]", adset_name)
    return m.group(1).strip() if m else ""


def get_creative_name(ad_name: str) -> str:
    """
    Creative Name = everything after _AS~....: in the Ad Name.
    The Ad Name format is: {full adset naming}_AS~{seq}:{creative string}

    e.g. "..._AS~Ad 3:CL-INFTPRv2-HT-1103-display" → "CL-INFTPRv2-HT-1103-display"
    """
    if not isinstance(ad_name, str):
        return ""
    # Find _AS~ then take everything after the first colon
    m = re.search(r"_AS~[^:]+:(.+)$", ad_name)
    return m.group(1).strip() if m else ""


def get_creative_seq(ad_name: str) -> str:
    """
    Creative Seq. = value between _AS~ and : in the Ad Name.

    e.g. "..._AS~Ad 3:CL-..." → "Ad 3"
    e.g. "..._AS~Ad Jul23-07160718-TA3-01-WHP-Collection10801080:CL-..." → "Ad Jul23-07160718-TA3-01-WHP-Collection10801080"
    """
    if not isinstance(ad_name, str):
        return ""
    m = re.search(r"_AS~([^:]+):", ad_name)
    return m.group(1).strip() if m else ""


def get_creative_type(creative_name: str) -> str:
    """
    Creative Type = value after the last '-' in Creative Name.

    e.g. "CL-INFTPRv2-HT-1103-display" → "display"
    """
    if not isinstance(creative_name, str) or not creative_name:
        return ""
    return creative_name.rsplit("-", 1)[-1].strip()


def get_channel(account_name: str) -> str:
    """
    Channel = first matching keyword found in Account Name.
    Checks in the order defined in CHANNEL_KEYWORDS.
    Returns "" if no match.
    """
    if not isinstance(account_name, str):
        return ""
    for keyword, channel in CHANNEL_KEYWORDS.items():
        if keyword in account_name:
            return channel
    return ""





# ─────────────────────────────────────────────────────────────────────────────
# Meta API field → DataFrame column mapping
# ─────────────────────────────────────────────────────────────────────────────

# Standard actions (non-CPAS metrics)
ACTION_MAP = {
    "link_click":                "Link clicks",
    "outbound_click":            "Outbound clicks",
    "video_view":                "3-second video plays",
    "video_thruplay_watched":    "ThruPlays",
    "video_p25_watched_actions": "Video plays at 25%",
    "video_p50_watched_actions": "Video plays at 50%",
    "video_p75_watched_actions": "Video plays at 75%",
    "video_p100_watched_actions":"Video plays at 100%",
    "post_engagement":           "Post engagements",
    "post_reaction":             "Post reactions",
    "comment":                   "Post comments",
    "post":                      "Post shares",
}

# CPAS conversion metrics come from catalog_segment_actions
CATALOG_ACTION_MAP = {
    "omni_view_content":   "Content views with shared items",
    "omni_add_to_cart":    "Adds to cart with shared items",
    "omni_purchase":       "Purchases with Shared Items",
    "converted_promoted_product_omni_purchase": "Purchases with Shared Items",
    # website / in-app breakdown
    "offsite_conversion.fb_pixel_view_content":  "Website content views with shared items",
    "app_custom_event.fb_mobile_content_view":   "In-app content views with shared items",
    "offsite_conversion.fb_pixel_add_to_cart":   "Website adds to cart with shared items",
    "app_custom_event.fb_mobile_add_to_cart":    "In-app adds to cart with shared items",
    "offsite_conversion.fb_pixel_purchase":      "Website purchases with shared items",
    "app_custom_event.fb_mobile_purchase":       "In-app purchases with shared items",
}

# CPAS conversion values come from catalog_segment_value
CATALOG_VALUE_MAP = {
    "omni_purchase":       "Purchases conversion value for shared items only",
    "converted_promoted_product_omni_purchase": "Purchases conversion value for shared items only",
    "offsite_conversion.fb_pixel_add_to_cart":  "Website adds to cart conversion value for shared items only",
    "app_custom_event.fb_mobile_add_to_cart":   "In-app adds to cart conversion value for shared items only",
    "offsite_conversion.fb_pixel_purchase":     "Website purchases conversion value for shared items only",
    "app_custom_event.fb_mobile_purchase":      "In-app purchases conversion value for shared items only",
}

# ROAS from purchase_roas field
ROAS_MAP = {
    "omni_purchase":                        "Purchase ROAS for shared items only",
    "offsite_conversion.fb_pixel_purchase": "Website purchase ROAS for shared items only",
    "app_custom_event.fb_mobile_purchase":  "Mobile app purchase ROAS for shared items only",
}


# ─────────────────────────────────────────────────────────────────────────────
# Row flattener: expand actions / action_values / purchase_roas arrays
# ─────────────────────────────────────────────────────────────────────────────

def _extract_actions(row: dict, field: str, mapping: dict) -> dict:
    result = {}
    for item in row.get(field, []):
        action_type = item.get("action_type", "")
        if action_type in mapping:
            try:
                result[mapping[action_type]] = float(item.get("value", 0))
            except (ValueError, TypeError):
                result[mapping[action_type]] = 0.0
    return result


def flatten_row(row: dict) -> dict:
    """Flatten a single Meta API insights row into a flat dict."""
    flat = {
        "Ad ID":            row.get("ad_id", ""),
        "Account name":     row.get("account_name", ""),
        "Campaign name":    row.get("campaign_name", ""),
        "Ad Set Name":      row.get("adset_name", ""),
        "Ad name":          row.get("ad_name", ""),
        "Amount spent":     float(row.get("spend", 0) or 0),
        "Reach":            int(row.get("reach", 0) or 0),
        "Impressions":      int(row.get("impressions", 0) or 0),
        "CPM (cost per 1,000 impressions)": float(row.get("cpm", 0) or 0),
        "CPC (cost per link click)":        float(row.get("cpc", 0) or 0),
        "CTR (link click-through rate)":    float(row.get("ctr", 0) or 0),
        "Frequency":        float(row.get("frequency", 0) or 0),
        "Reporting starts": row.get("date_start", ""),
        "Reporting ends":   row.get("date_stop", ""),
        "Day":              row.get("date_start", ""),
    }

    # Zero-fill all columns
    all_cols = (
        list(ACTION_MAP.values()) +
        list(CATALOG_ACTION_MAP.values()) +
        list(CATALOG_VALUE_MAP.values()) +
        list(ROAS_MAP.values())
    )
    for col in set(all_cols):
        flat[col] = 0.0

    # Standard actions (video, engagement, link clicks)
    flat.update(_extract_actions(row, "actions", ACTION_MAP))

    # Video quartile + Thruplay metrics are top-level fields, not inside actions array
    _VIDEO_QUARTILE = {
        "video_thruplay_watched_actions": "ThruPlays",
        "video_p25_watched_actions":      "Video plays at 25%",
        "video_p50_watched_actions":      "Video plays at 50%",
        "video_p75_watched_actions":      "Video plays at 75%",
        "video_p100_watched_actions":     "Video plays at 100%",
    }
    for field, col in _VIDEO_QUARTILE.items():
        items = row.get(field, [])
        if isinstance(items, list):
            for item in items:
                try:
                    flat[col] = flat.get(col, 0.0) + float(item.get("value", 0))
                except (ValueError, TypeError):
                    pass

    # CPAS conversions from catalog_segment_actions / catalog_segment_value
    # Note: accumulate because multiple action_types can map to same column
    for item in row.get("catalog_segment_actions", []):
        action_type = item.get("action_type", "")
        if action_type in CATALOG_ACTION_MAP:
            col = CATALOG_ACTION_MAP[action_type]
            try:
                flat[col] = flat.get(col, 0.0) + float(item.get("value", 0))
            except (ValueError, TypeError):
                pass

    for item in row.get("catalog_segment_value", []):
        action_type = item.get("action_type", "")
        if action_type in CATALOG_VALUE_MAP:
            col = CATALOG_VALUE_MAP[action_type]
            try:
                flat[col] = flat.get(col, 0.0) + float(item.get("value", 0))
            except (ValueError, TypeError):
                pass

    # ROAS from purchase_roas
    flat.update(_extract_actions(row, "purchase_roas", ROAS_MAP))

    return flat


# ─────────────────────────────────────────────────────────────────────────────
# Main transformer
# ─────────────────────────────────────────────────────────────────────────────

def transform(
    raw_rows: list[dict],
    creative_info_map: dict[str, dict] | None = None,
    video_url_map: dict[str, str] | None = None,
    story_id_map: dict[str, str] | None = None,
) -> pd.DataFrame:
    """
    Transform raw Meta API insight rows into the final CPAS report DataFrame.

    Args:
        raw_rows:          List of dicts from MetaAPIClient.get_insights()
        creative_info_map: { ad_id: { "page_id", "object_story_id", "image_url", "video_id" } }
        video_url_map:     { video_id: permalink_url }
        story_id_map:      { ad_id: effective_object_story_id or object_story_id }

    Returns:
        DataFrame with all required columns in final output order.
    """
    if not raw_rows:
        logger.warning("transform() received empty raw_rows")
        return _empty_dataframe()

    # 1. Flatten rows
    flat = [flatten_row(r) for r in raw_rows]
    df = pd.DataFrame(flat)

    # 2. Parse Day column
    df["Day"] = pd.to_datetime(df["Day"], errors="coerce")

    # 3. Derived columns
    df["Market"]        = df["Account name"].apply(get_market_from_account)
    df["FY"]            = df["Day"].apply(get_fy)
    df["Year"]          = df["Day"].dt.year.astype("Int64").astype(str).replace("<NA>", "")
    df["Month"]         = df["Day"].dt.month.astype("Int64").astype(str).replace("<NA>", "")
    df["Date"]          = df["Day"].dt.strftime("%Y-%m-%d").fillna("")

    df["Brand"]         = df["Campaign name"].apply(get_brand)
    df["Campaign"]      = df["Campaign name"].apply(get_campaign)
    df["Optimization"]  = df["Campaign name"].apply(get_optimization)

    df["TA#"]           = ""
    df["TA Name"]       = df["Ad Set Name"].apply(get_ta_name)

    df["Creative Name"] = df["Ad name"].apply(get_creative_name)
    df["Creative Seq."] = df["Ad name"].apply(get_creative_seq)
    df["Creative Type"] = df["Creative Name"].apply(get_creative_type)

    df["OB~"]           = "SALES-PCS"
    df["Objective"]     = "PRODUCT_CATALOG_SALES"
    df["Channel"]       = df["Account name"].apply(get_channel)

    an_value            = df["Campaign name"].apply(get_an_value)
    df["Category"]      = an_value
    df["Funding Source"]= an_value

    # 4. Creative link columns
    def build_post_url(ad_id: str) -> str:
        if not story_id_map:
            return ""
        sid = story_id_map.get(str(ad_id), "")
        if sid and "_" in str(sid):
            parts = str(sid).split("_", 1)
            if len(parts) == 2 and parts[1] != "0":
                return f"https://www.facebook.com/{parts[0]}/posts/{parts[1]}"
        return ""

    def get_image_url(ad_id: str) -> str:
        if not creative_info_map:
            return ""
        return creative_info_map.get(str(ad_id), {}).get("image_url", "")

    def get_video_url(ad_id: str) -> str:
        if not creative_info_map or not video_url_map:
            return ""
        vid = creative_info_map.get(str(ad_id), {}).get("video_id", "")
        return video_url_map.get(vid, "") if vid else ""

    df["Post URL"]            = df["Ad ID"].astype(str).apply(build_post_url)
    df["Creative Image URL"]  = df["Ad ID"].astype(str).apply(get_image_url)
    df["Creative Video URL"]  = df["Ad ID"].astype(str).apply(get_video_url)

    # 5. Final column order
    df = df[OUTPUT_COLUMNS]

    logger.info(f"transform() complete: {len(df)} rows, {len(df.columns)} columns")
    return df


def _empty_dataframe() -> pd.DataFrame:
    return pd.DataFrame(columns=OUTPUT_COLUMNS)


# ─────────────────────────────────────────────────────────────────────────────
# Output column order
# ─────────────────────────────────────────────────────────────────────────────

OUTPUT_COLUMNS = [
    # ── Derived / parsed ──────────────────────────────────────────────
    "Market",
    "FY",
    "Year",
    "Month",
    "Date",
    "Category",
    "Funding Source",
    "Brand",
    "Campaign",
    "Optimization",
    "TA#",
    "TA Name",
    "Creative Seq.",
    "Creative Name",
    "Creative Type",
    "OB~",
    "Objective",
    "Channel",
    # ── Raw Meta fields ───────────────────────────────────────────────
    "Account name",
    "Campaign name",
    "Ad Set Name",
    "Ad name",
    "Post URL",
    "Creative Image URL",
    "Creative Video URL",
    "Amount spent",
    "Reach",
    "Frequency",
    "Impressions",
    "Link clicks",
    "Outbound clicks",
    "Content views with shared items",
    "Adds to cart with shared items",
    "Purchases with Shared Items",
    "Purchases conversion value for shared items only",
    "Purchase ROAS for shared items only",
    "Website content views with shared items",
    "In-app content views with shared items",
    "Website adds to cart with shared items",
    "In-app adds to cart with shared items",
    "Website adds to cart conversion value for shared items only",
    "In-app adds to cart conversion value for shared items only",
    "Website purchases with shared items",
    "In-app purchases with shared items",
    "Website purchases conversion value for shared items only",
    "In-app purchases conversion value for shared items only",
    "Website purchase ROAS for shared items only",
    "Mobile app purchase ROAS for shared items only",
    "CPC (cost per link click)",
    "CPM (cost per 1,000 impressions)",
    "CTR (link click-through rate)",
    "Post engagements",
    "Post reactions",
    "Post comments",
    "Post shares",
    "3-second video plays",
    "ThruPlays",
    "Video plays at 25%",
    "Video plays at 50%",
    "Video plays at 75%",
    "Video plays at 100%",
    "Reporting starts",
    "Reporting ends",
]
