"""
HKTW Meta Auto Report - KOL Data Transformer
"""
import re
import logging
import pandas as pd

logger = logging.getLogger(__name__)

BRAND_CATEGORY_MAPPING = {
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

OBJECTIVE_MAPPING = {
    "BA-RH":  "Awareness",
    "BA-ARL": "Awareness",
    "CW-LC":  "Traffic",
    "EN-TP":  "Video Views",
    "BA-TP":  "Video Views",
}

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

def get_an_value(campaign_name):
    if not isinstance(campaign_name, str): return ""
    m = re.search(r"_AN~(.+?)_CN~", campaign_name)
    return m.group(1).strip() if m else ""

def get_boutique(campaign_name):
    if not isinstance(campaign_name, str): return ""
    m = re.search(r"_CN~([^@_]+)@", campaign_name)
    return m.group(1).strip() if m else ""

def get_objective(campaign_name):
    if not isinstance(campaign_name, str): return ""
    m = re.search(r"_OB~(.+?)_RT~", campaign_name)
    return m.group(1).strip() if m else ""

def get_campaign(campaign_name):
    if not isinstance(campaign_name, str): return ""
    m = re.search(r"_CN~(.+?)_YR~", campaign_name)
    return m.group(1).strip() if m else ""

def get_ta(adset_name):
    if not isinstance(adset_name, str): return ""
    m = re.search(r"\[(.+)\](?=_AG~)", adset_name)
    if m: return m.group(1).strip()
    m = re.search(r"\[([^\]]+)\]", adset_name)
    return m.group(1).strip() if m else ""

def get_creative_name(ad_name):
    if not isinstance(ad_name, str): return ""
    m = re.search(r"_AS~(.+)$", ad_name)
    return m.group(1).strip() if m else ""

def get_creative_tag(creative_name):
    if not isinstance(creative_name, str) or ":" not in creative_name: return ""
    return creative_name.split(":", 1)[1].strip()

def get_p2p(creative_name):
    if not isinstance(creative_name, str): return ""
    m = re.search(r":([^#]+)#", creative_name)
    return m.group(1).strip() if m else ""

def get_creative_code(creative_tag):
    if not isinstance(creative_tag, str): return ""
    tag = creative_tag.split("#", 1)[-1] if "#" in creative_tag else creative_tag
    parts = tag.split("-")
    return parts[1].strip() if len(parts) > 1 else ""

def get_channel_from_tag(creative_tag):
    if not isinstance(creative_tag, str): return ""
    tag = creative_tag.split("#", 1)[-1] if "#" in creative_tag else creative_tag
    parts = tag.split("-")
    return parts[2].strip() if len(parts) > 2 else ""

def get_creative_format(creative_tag):
    if not isinstance(creative_tag, str) or not creative_tag: return ""
    tag = creative_tag.split("#", 1)[-1] if "#" in creative_tag else creative_tag
    return tag.rsplit("-", 1)[-1].strip()

def get_kol_name_from_tag(creative_tag):
    if not isinstance(creative_tag, str) or "#" not in creative_tag: return ""
    after_hash = creative_tag.split("#", 1)[1]
    return after_hash.split("-", 1)[0].strip()

def get_content_type(account_name, creative_tag):
    if not isinstance(account_name, str): return ""
    if "KOL" in account_name: return "KOL Boosting"
    if get_kol_name_from_tag(creative_tag): return "Buyout"
    return ""

def map_objective(raw_ob):
    if not isinstance(raw_ob, str) or not raw_ob: return ""
    return OBJECTIVE_MAPPING.get(raw_ob, raw_ob)

def get_objective_kol(raw_ob, account_name):
    if isinstance(account_name, str) and "CPAS" in account_name:
        return "PRODUCT_CATALOG_SALES"
    return map_objective(raw_ob)

def get_category_type_and_category(brand):
    return BRAND_CATEGORY_MAPPING.get(brand, ("", ""))

ACTION_MAP = {
    "link_click":                 "Link Clicks",
    "outbound_click":             "Outbound Clicks",
    "video_view":                 "3s Views",
    "video_thruplay_watched":     "Thruplay",
    "video_p25_watched_actions":  "View at 25%",
    "video_p50_watched_actions":  "View at 50%",
    "video_p75_watched_actions":  "View at 75%",
    "video_p100_watched_actions": "View at 100%",
    "post_reaction":              "Reaction",
    "like":                       "Like",
    "comment":                    "Comment",
    "post":                       "Share",
    "onsite_web_save":            "Save",
    "post_save":                  "Save",
}

def flatten_row(row):
    flat = {
        "Ad Account ID":               row.get("account_id", ""),
        "Ad Account Name":             row.get("account_name", ""),
        "Campaign ID":                 row.get("campaign_id", ""),
        "Campaign Name":               row.get("campaign_name", ""),
        "Ad Set ID":                   row.get("adset_id", ""),
        "Ad Set Name":                 row.get("adset_name", ""),
        "Ad ID":                       row.get("ad_id", ""),
        "Ad Name":                     row.get("ad_name", ""),
        "Page Name":                   "",
        "Campaign Start Date":         "",
        "Campaign End Date":           "",
        "Campaign Budget":             "",
        "Amount Spent (local currency)": float(row.get("spend", 0) or 0),
        "Impressions":                 int(row.get("impressions", 0) or 0),
        "Day":                         row.get("date_start", ""),
        "Platform":                    row.get("publisher_platform", ""),
        "Placement":                   row.get("platform_position", ""),
    }
    for col in set(ACTION_MAP.values()):
        flat[col] = 0.0
    for item in row.get("actions", []):
        action_type = item.get("action_type", "")
        if action_type in ACTION_MAP:
            col = ACTION_MAP[action_type]
            try:
                flat[col] = flat.get(col, 0.0) + float(item.get("value", 0))
            except (ValueError, TypeError):
                pass
    VIDEO_QUARTILE_MAP = {
        "video_thruplay_watched_actions": "Thruplay",
        "video_p25_watched_actions":      "View at 25%",
        "video_p50_watched_actions":      "View at 50%",
        "video_p75_watched_actions":      "View at 75%",
        "video_p100_watched_actions":     "View at 100%",
    }
    for field, col in VIDEO_QUARTILE_MAP.items():
        items = row.get(field, [])
        if isinstance(items, list):
            for item in items:
                try:
                    flat[col] = flat.get(col, 0.0) + float(item.get("value", 0))
                except (ValueError, TypeError):
                    pass
    return flat


def transform(
    raw_rows,
    fx_rates=None,
    page_name_map=None,
    creative_info_map=None,
    video_url_map=None,
    story_id_map=None,
    campaign_map=None,
):
    if not raw_rows:
        logger.warning("transform() received empty raw_rows")
        return _empty_dataframe()

    df = pd.DataFrame([flatten_row(r) for r in raw_rows])

    if page_name_map:
        df["Page Name"] = df["Ad ID"].astype(str).map(page_name_map).fillna("")

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

    df["Post URL"]           = df["Ad ID"].astype(str).apply(build_post_url)
    df["Creative Image URL"] = df["Ad ID"].astype(str).apply(get_image_url)
    df["Creative Video URL"] = df["Ad ID"].astype(str).apply(get_video_url)

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

    df["Day"]    = pd.to_datetime(df["Day"], errors="coerce")
    df["Market"] = df["Ad Account Name"].apply(get_market_from_account)
    df["FY"]     = df["Day"].apply(get_fy)
    df["Year"]   = df["Day"].dt.year.astype("Int64").astype(str).replace("<NA>", "")
    df["Month"]  = df["Day"].dt.month.astype("Int64").astype(str).replace("<NA>", "")
    df["Date"]   = df["Day"].dt.strftime("%Y-%m-%d").fillna("")

    df["Brand"]    = df["Campaign Name"].apply(get_an_value)
    df["Boutique"] = df["Campaign Name"].apply(get_boutique)
    df["Campaign"] = df["Campaign Name"].apply(get_campaign)

    raw_ob = df["Campaign Name"].apply(get_objective)
    df["Objective"] = df.apply(
        lambda r: get_objective_kol(raw_ob[r.name], r["Ad Account Name"]), axis=1
    )

    df["TA"]              = df["Ad Set Name"].apply(get_ta)
    df["Creative Name"]   = df["Ad Name"].apply(get_creative_name)
    df["Creative Tag"]    = df["Creative Name"].apply(get_creative_tag)
    df["P2P"]             = df["Creative Name"].apply(get_p2p)
    df["Creative Code"]   = df["Creative Tag"].apply(get_creative_code)
    df["Channel"]         = df["Creative Tag"].apply(get_channel_from_tag)
    df["Creative Format"] = df["Creative Tag"].apply(get_creative_format)
    df["Content Type"]    = df.apply(
        lambda r: get_content_type(r["Ad Account Name"], r["Creative Tag"]), axis=1
    )

    cat_lookup          = df["Brand"].apply(get_category_type_and_category)
    df["Category Type"] = cat_lookup.apply(lambda x: x[0])
    df["Category"]      = cat_lookup.apply(lambda x: x[1])

    if fx_rates:
        def to_usd(r):
            rate = fx_rates.get(r["Market"], 0)
            return round(r["Amount Spent (local currency)"] / rate, 2) if rate else ""
        df["Amount Spent (USD)"] = df.apply(to_usd, axis=1)
    else:
        df["Amount Spent (USD)"] = ""

    return df[OUTPUT_COLUMNS].reset_index(drop=True)


def _empty_dataframe():
    return pd.DataFrame(columns=OUTPUT_COLUMNS)


OUTPUT_COLUMNS = [
    "Market", "FY", "Year", "Month", "Date",
    "Category Type", "Category",
    "Brand", "Boutique", "Objective", "Campaign", "TA",
    "Creative Name", "Creative Tag", "Creative Code", "Creative Format",
    "P2P", "Channel", "Content Type",
    "Ad Account ID", "Ad Account Name",
    "Campaign ID", "Campaign Name",
    "Ad Set ID", "Ad Set Name",
    "Ad ID", "Ad Name",
    "Page Name", "Post URL", "Creative Image URL", "Creative Video URL",
    "Platform", "Placement",
    "Campaign Start Date", "Campaign End Date", "Campaign Budget",
    "Amount Spent (local currency)", "Amount Spent (USD)",
    "Impressions", "Link Clicks", "Outbound Clicks",
    "3s Views", "Thruplay",
    "View at 25%", "View at 50%", "View at 75%", "View at 100%",
    "Reaction", "Like", "Comment", "Share", "Save",
]
