"""
HKTW Meta Auto Report - KOL Data Transformer
"""
import re
import logging
import pandas as pd

logger = logging.getLogger(__name__)

BRAND_CATEGORY_MAPPING = {
    # ── Hair Care ────────────────────────────────
    "Pantene":         ("Brand", "Hair Care"),
    "Hair Recipe":     ("Brand", "Hair Care"),
    "Herbal Essences": ("Brand", "Hair Care"),
    "H&S":             ("Brand", "Hair Care"),
    "Head & Shoulders":("Brand", "Hair Care"),
    "Head & Shoulder": ("Brand", "Hair Care"),   # variant (no trailing s)
    "Pert":            ("Brand", "Hair Care"),
    "VS":              ("Brand", "Hair Care"),
    "Rejoice":         ("Brand", "Hair Care"),
    # ── Skin Care ───────────────────────────────
    "Olay":            ("Brand", "Skin Care"),
    "First Aid Beauty":("",      "Skin Care"),
    # ── Oral Care ───────────────────────────────
    "Oral-B":          ("Brand", "Oral Care"),
    "OralB":           ("Brand", "Oral Care"),   # variant (no dash)
    "Oral B":          ("Brand", "Oral Care"),   # variant (space)
    "Crest":           ("Brand", "Oral Care"),
    # ── Fabric Care ─────────────────────────────
    "Ariel":           ("Brand", "Fabric Care"),
    "Lenor":           ("Brand", "Fabric Care"),
    # ── Fem Care ────────────────────────────────
    "Whisper":         ("Brand", "Fem Care"),
    # ── Baby Care ───────────────────────────────
    "Pampers":         ("Brand", "Baby Care"),
    # ── Home Care ───────────────────────────────
    "Febreze":         ("Brand", "Home Care"),
    # ── Grooming ────────────────────────────────
    "Gillette":        ("Brand", "Grooming"),
    "Braun":           ("Brand", "Grooming"),
    # ── CBD ─────────────────────────────────────
    "CBD":             ("Brand", "CBD"),
    # ── EC brands ───────────────────────────────
    "EC PTN":          ("EC",    "EC Hair Care"),
    "EC HR":           ("EC",    "EC Hair Care"),
    "EC H&S":          ("EC",    "EC Hair Care"),
    "EC Hair Recipe":  ("EC",    "EC Hair Care"),
    "EC Pantene":      ("EC",    "EC Hair Care"),
    "EC Olay":         ("EC",    "EC Skin Care"),
    "EC Oral-B":       ("EC",    "EC Oral Care"),
    "EC Ariel":        ("EC",    "EC Fabric Care"),
    "EC Lenor":        ("EC",    "EC Fabric Care"),
    "EC Whisper":      ("EC",    "EC Fem Care"),
    "EC Pampers":      ("EC",    "EC Baby Care"),
    "EC Gillette":     ("EC",    "EC Grooming"),
    "EC Braun":        ("EC",    "EC Grooming"),
    "EC Crest":        ("EC",    "EC Oral Care"),
}

# Brands where Category depends on Boutique, not Brand itself.
# These are looked up via get_category_by_boutique() below.
BOUTIQUE_DEPENDENT_BRANDS = {"EC Fabric Care", "EC Total Brand", "Shopper Marketing"}

# Lookup table: normalised key → (Category Type, Category)
# Built once at import time for case-insensitive matching.
_BRAND_CATEGORY_LOOKUP = {k.lower(): v for k, v in BRAND_CATEGORY_MAPPING.items()}

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

_QUARTER_LABELS = {1: "JFM", 2: "JFM", 3: "JFM",
                   4: "AMJ", 5: "AMJ", 6: "AMJ",
                   7: "JAS", 8: "JAS", 9: "JAS",
                   10: "OND", 11: "OND", 12: "OND"}

def get_quarter(date):
    """Return quarter label e.g. JFM'26 from a datetime."""
    if pd.isna(date): return ""
    label = _QUARTER_LABELS.get(date.month, "")
    year2 = str(date.year)[2:]
    return f"{label}'{year2}"

def get_duration_group(creative_type: str) -> str:
    """
    Map Creative Type to Duration Group bucket.
    Numeric value (seconds) → ≤15s / 16-30s / 31-45s / 46-60s / >60s
    Non-numeric or 0 → Display
    display/DISPLAY/static/similar → Display
    """
    if not isinstance(creative_type, str) or not creative_type.strip():
        return ""
    ct = creative_type.strip()
    # Check for display-like values first (case-insensitive, may have surrounding chars)
    ct_lower = ct.lower()
    if "display" in ct_lower or ct_lower == "static":
        return "Display"
    # Try to parse as a number
    try:
        secs = float(ct)
    except ValueError:
        # Contains letters / colons etc. → not a duration
        return ""
    if secs <= 0:
        return "Display"
    elif secs <= 15:
        return "≤15s"
    elif secs <= 30:
        return "16-30s"
    elif secs <= 45:
        return "31-45s"
    elif secs <= 60:
        return "46-60s"
    else:
        return ">60s"

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
    """Case-insensitive brand -> (Category Type, Category).
    For boutique-dependent brands call get_category_by_boutique() instead."""
    if not isinstance(brand, str) or not brand:
        return ("", "")
    return _BRAND_CATEGORY_LOOKUP.get(brand.lower(), ("", ""))


def get_category_by_boutique(brand, boutique):
    """Brands where Category is driven by Boutique, not Brand.

    - Boutique == 'AllBrand'       -> ("EC", "EC Total Brand")
    - Any other Boutique           -> look up boutique as a brand name,
                                      force Category Type = "EC"
    """
    if not isinstance(brand, str) or brand not in BOUTIQUE_DEPENDENT_BRANDS:
        return get_category_type_and_category(brand)
    if not isinstance(boutique, str) or boutique.strip() == "":
        return ("EC", "")
    b = boutique.strip()
    if b.lower() == "allbrand":
        return ("EC", "EC Total Brand")
    _, category = _BRAND_CATEGORY_LOOKUP.get(b.lower(), ("", ""))
    # Prepend "EC " if not already present
    if category and not category.startswith("EC "):
        category = f"EC {category}"
    return ("EC", category)

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
    buying_raw = row.get("buying_type", "")
    buying = "Reach & Frequency" if buying_raw == "RESERVED" else ("Auction" if buying_raw == "AUCTION" else buying_raw)
    flat = {
        "Ad Account ID":               row.get("account_id", ""),
        "Ad Account Name":             row.get("account_name", ""),
        "Campaign ID":                 row.get("campaign_id", ""),
        "Campaign Name":               row.get("campaign_name", ""),
        "Ad Set ID":                   row.get("adset_id", ""),
        "Ad Set Name":                 row.get("adset_name", ""),
        "Ad ID":                       row.get("ad_id", ""),
        "Ad Name":                     row.get("ad_name", ""),
        "Media Buying":                buying,
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

    def get_video_permalink(ad_id):
        if not creative_info_map or not video_url_map: return ""
        vid = creative_info_map.get(str(ad_id), {}).get("video_id", "")
        if not vid: return ""
        entry = video_url_map.get(vid, {})
        # __post__ entries store a plain URL string (from get_post_media fallback)
        if isinstance(entry, str): return entry
        return entry.get("permalink", "")

    def get_video_source(ad_id):
        if not creative_info_map or not video_url_map: return ""
        vid = creative_info_map.get(str(ad_id), {}).get("video_id", "")
        if not vid: return ""
        entry = video_url_map.get(vid, {})
        if isinstance(entry, str): return ""   # __post__ fallback has no source URL
        return entry.get("source", "")

    df["Post URL"]                       = df["Ad ID"].astype(str).apply(build_post_url)
    df["Creative Image URL"]             = df["Ad ID"].astype(str).apply(get_image_url)
    df["Creative Video URL (Permalink)"] = df["Ad ID"].astype(str).apply(get_video_permalink)
    df["Creative Video URL (Source)"]    = df["Ad ID"].astype(str).apply(get_video_source)

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
    df["Quarter"] = df["Day"].apply(get_quarter)
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
    df["Duration Group"]  = df["Creative Format"].apply(get_duration_group)
    df["Content Type"]    = df.apply(
        lambda r: get_content_type(r["Ad Account Name"], r["Creative Tag"]), axis=1
    )

    cat_lookup = df.apply(
        lambda r: get_category_by_boutique(r["Brand"], r["Boutique"])
        if r["Brand"] in BOUTIQUE_DEPENDENT_BRANDS
        else get_category_type_and_category(r["Brand"]),
        axis=1,
    )
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
    "Market", "FY", "Year", "Quarter", "Month", "Date",
    "Category Type", "Category",
    "Brand", "Boutique", "Objective", "Campaign", "TA",
    "Creative Name", "Creative Tag", "Creative Code", "Creative Format",
    "P2P", "Channel", "Content Type", "Duration Group",
    "Media Buying",
    "Ad Account ID", "Ad Account Name",
    "Campaign ID", "Campaign Name",
    "Ad Set ID", "Ad Set Name",
    "Ad ID", "Ad Name",
    "Page Name", "Post URL", "Creative Image URL",
    "Creative Video URL (Permalink)", "Creative Video URL (Source)",
    "Platform", "Placement",
    "Campaign Start Date", "Campaign End Date", "Campaign Budget",
    "Amount Spent (local currency)", "Amount Spent (USD)",
    "Impressions", "Link Clicks", "Outbound Clicks",
    "3s Views", "Thruplay",
    "View at 25%", "View at 50%", "View at 75%", "View at 100%",
    "Reaction", "Like", "Comment", "Share", "Save",
]
