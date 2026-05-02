"""
HKTW Meta Auto Report - CPAS Data Transformer
"""
import re
import logging
import pandas as pd

logger = logging.getLogger(__name__)

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

def parse_token(text, key):
    if not isinstance(text, str): return ""
    import re
    pattern = rf"(?:^|_){re.escape(key)}~([^_]+)"
    m = re.search(pattern, text)
    return m.group(1).strip() if m else ""

def get_an_value(campaign_name):
    if not isinstance(campaign_name, str): return ""
    m = re.search(r"_AN~(.+?)_CN~", campaign_name)
    return m.group(1).strip() if m else ""

def get_market_from_account(account_name):
    if not isinstance(account_name, str): return ""
    if "HKD" in account_name: return "HK"
    if "TWD" in account_name: return "TW"
    return ""

def get_fy(date):
    if pd.isna(date): return ""
    year, month = date.year, date.month
    if month >= 7: fy_start, fy_end = year, year + 1
    else: fy_start, fy_end = year - 1, year
    return f"FY{str(fy_start)[2:]}{str(fy_end)[2:]}"

def get_brand(campaign_name):
    if not isinstance(campaign_name, str): return ""
    m = re.search(r"_CN~([^@_]+)@", campaign_name)
    return m.group(1).strip() if m else ""

def get_campaign(campaign_name):
    if not isinstance(campaign_name, str): return ""
    m = re.search(r"_CN~(.+?)_YR~", campaign_name)
    return m.group(1).strip() if m else ""

def get_optimization(campaign_name):
    if not isinstance(campaign_name, str): return ""
    m = re.search(r":\((.+?)\)_YR~", campaign_name)
    return m.group(1).strip() if m else ""

def get_ta_name(adset_name):
    if not isinstance(adset_name, str): return ""
    m = re.search(r"\[([^\]]+)\]", adset_name)
    return m.group(1).strip() if m else ""

def get_creative_name(ad_name):
    if not isinstance(ad_name, str): return ""
    m = re.search(r"_AS~[^:]+:(.+)$", ad_name)
    return m.group(1).strip() if m else ""

def get_creative_seq(ad_name):
    if not isinstance(ad_name, str): return ""
    m = re.search(r"_AS~([^:]+):", ad_name)
    return m.group(1).strip() if m else ""

def get_creative_type(creative_name):
    if not isinstance(creative_name, str) or not creative_name: return ""
    return creative_name.rsplit("-", 1)[-1].strip()

def get_channel(account_name):
    if not isinstance(account_name, str): return ""
    for keyword, channel in CHANNEL_KEYWORDS.items():
        if keyword in account_name:
            return channel
    return ""

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

CATALOG_ACTION_MAP = {
    "omni_view_content":   "Content views with shared items",
    "omni_add_to_cart":    "Adds to cart with shared items",
    "omni_purchase":       "Purchases with Shared Items",
    "converted_promoted_product_omni_purchase": "Purchases with Shared Items",
    "offsite_conversion.fb_pixel_view_content":  "Website content views with shared items",
    "app_custom_event.fb_mobile_content_view":   "In-app content views with shared items",
    "offsite_conversion.fb_pixel_add_to_cart":   "Website adds to cart with shared items",
    "app_custom_event.fb_mobile_add_to_cart":    "In-app adds to cart with shared items",
    "offsite_conversion.fb_pixel_purchase":      "Website purchases with shared items",
    "app_custom_event.fb_mobile_purchase":       "In-app purchases with shared items",
}

CATALOG_VALUE_MAP = {
    "omni_purchase":       "Purchases conversion value for shared items only",
    "converted_promoted_product_omni_purchase": "Purchases conversion value for shared items only",
    "offsite_conversion.fb_pixel_add_to_cart":  "Website adds to cart conversion value for shared items only",
    "app_custom_event.fb_mobile_add_to_cart":   "In-app adds to cart conversion value for shared items only",
    "offsite_conversion.fb_pixel_purchase":     "Website purchases conversion value for shared items only",
    "app_custom_event.fb_mobile_purchase":      "In-app purchases conversion value for shared items only",
}

ROAS_MAP = {
    "omni_purchase":                        "Purchase ROAS for shared items only",
    "offsite_conversion.fb_pixel_purchase": "Website purchase ROAS for shared items only",
    "app_custom_event.fb_mobile_purchase":  "Mobile app purchase ROAS for shared items only",
}

def _extract_actions(row, field, mapping):
    result = {}
    for item in row.get(field, []):
        action_type = item.get("action_type", "")
        if action_type in mapping:
            try: result[mapping[action_type]] = float(item.get("value", 0))
            except (ValueError, TypeError): result[mapping[action_type]] = 0.0
    return result

def flatten_row(row):
    flat = {
        "Ad ID":            row.get("ad_id", ""),
        "Account name":     row.get("account_name", ""),
        "Campaign name":    row.get("campaign_name", ""),
        "Campaign ID":      row.get("campaign_id", ""),
        "Ad Set Name":      row.get("adset_name", ""),
        "Ad name":          row.get("ad_name", ""),
        "Amount spent":     float(row.get("spend", 0) or 0),
        "Reach":            int(row.get("reach", 0) or 0),
        "Impressions":      int(row.get("impressions", 0) or 0),
        "CPM (cost per 1,000 impressions)": float(row.get("cpm", 0) or 0),
        "CPC (cost per link click)":        float(row.get("cpc", 0) or 0),
        "CTR (link click-through rate)":    float(row.get("ctr", 0) or 0),
        "Frequency":        float(row.get("frequency", 0) or 0),
        "Campaign Start Date": "",
        "Campaign End Date":   "",
        "Campaign Budget":     "",
        "Reporting starts": row.get("date_start", ""),
        "Reporting ends":   row.get("date_stop", ""),
        "Day":              row.get("date_start", ""),
    }
    all_cols = (
        list(ACTION_MAP.values()) +
        list(CATALOG_ACTION_MAP.values()) +
        list(CATALOG_VALUE_MAP.values()) +
        list(ROAS_MAP.values())
    )
    for col in set(all_cols):
        flat[col] = 0.0
    flat.update(_extract_actions(row, "actions", ACTION_MAP))
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
                try: flat[col] = flat.get(col, 0.0) + float(item.get("value", 0))
                except (ValueError, TypeError): pass
    for item in row.get("catalog_segment_actions", []):
        action_type = item.get("action_type", "")
        if action_type in CATALOG_ACTION_MAP:
            col = CATALOG_ACTION_MAP[action_type]
            try: flat[col] = flat.get(col, 0.0) + float(item.get("value", 0))
            except (ValueError, TypeError): pass
    for item in row.get("catalog_segment_value", []):
        action_type = item.get("action_type", "")
        if action_type in CATALOG_VALUE_MAP:
            col = CATALOG_VALUE_MAP[action_type]
            try: flat[col] = flat.get(col, 0.0) + float(item.get("value", 0))
            except (ValueError, TypeError): pass
    flat.update(_extract_actions(row, "purchase_roas", ROAS_MAP))
    return flat

def transform(raw_rows, creative_info_map=None, video_url_map=None, story_id_map=None, campaign_map=None):
    if not raw_rows:
        logger.warning("transform() received empty raw_rows")
        return _empty_dataframe()
    flat = [flatten_row(r) for r in raw_rows]
    df = pd.DataFrame(flat)
    df["Day"] = pd.to_datetime(df["Day"], errors="coerce")
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

    def build_post_url(ad_id):
        if not story_id_map: return ""
        sid = story_id_map.get(str(ad_id), "")
        if sid and "_" in str(sid):
            parts = str(sid).split("_", 1)
            if len(parts) == 2 and parts[1] != "0":
                return f"https://www.facebook.com/{parts[0]}/posts/{parts[1]}"
        return ""

    def get_image_url(ad_id):
        if not creative_info_map: return ""
        return creative_info_map.get(str(ad_id), {}).get("image_url", "")

    def get_video_url(ad_id):
        if not creative_info_map or not video_url_map: return ""
        vid = creative_info_map.get(str(ad_id), {}).get("video_id", "")
        return video_url_map.get(vid, "") if vid else ""

    df["Post URL"]            = df["Ad ID"].astype(str).apply(build_post_url)
    df["Creative Image URL"]  = df["Ad ID"].astype(str).apply(get_image_url)
    df["Creative Video URL"]  = df["Ad ID"].astype(str).apply(get_video_url)

    # Campaign info from campaign_map
    if campaign_map:
        df["Campaign Start Date"] = df["Campaign ID"].astype(str).map(
            lambda cid: campaign_map.get(cid, {}).get("start", "")
        )
        df["Campaign End Date"] = df["Campaign ID"].astype(str).map(
            lambda cid: campaign_map.get(cid, {}).get("stop", "")
        )
        df["Campaign Budget"] = df["Campaign ID"].astype(str).map(
            lambda cid: campaign_map.get(cid, {}).get("budget", "")
        )

    df = df[OUTPUT_COLUMNS]
    logger.info(f"transform() complete: {len(df)} rows, {len(df.columns)} columns")
    return df

def _empty_dataframe():
    return pd.DataFrame(columns=OUTPUT_COLUMNS)

OUTPUT_COLUMNS = [
    "Market", "FY", "Year", "Month", "Date",
    "Category", "Funding Source", "Brand", "Campaign", "Optimization",
    "TA#", "TA Name", "Creative Seq.", "Creative Name", "Creative Type",
    "OB~", "Objective", "Channel",
    "Account name", "Campaign name", "Ad Set Name", "Ad name",
    "Post URL", "Creative Image URL", "Creative Video URL",
    "Campaign Start Date", "Campaign End Date", "Campaign Budget",
    "Amount spent", "Reach", "Frequency", "Impressions",
    "Link clicks", "Outbound clicks",
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
    "CPC (cost per link click)", "CPM (cost per 1,000 impressions)",
    "CTR (link click-through rate)",
    "Post engagements", "Post reactions", "Post comments", "Post shares",
    "3-second video plays", "ThruPlays",
    "Video plays at 25%", "Video plays at 50%",
    "Video plays at 75%", "Video plays at 100%",
    "Reporting starts", "Reporting ends",
]
