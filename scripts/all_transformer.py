"""
HKTW Meta Auto Report - All Accounts Data Transformer
"""
import logging
import pandas as pd

from scripts.kol_transformer import (
    get_market_from_account, get_fy, get_an_value, get_boutique, get_campaign,
    get_objective_kol, get_objective, get_ta, get_creative_name, get_creative_tag,
    get_p2p, get_creative_code, get_channel_from_tag, get_creative_format,
    get_content_type, get_kol_name_from_tag, get_category_type_and_category,
)
from scripts.cpas_transformer import (
    get_optimization, get_ta_name, get_creative_seq, get_creative_type,
    get_channel as get_cpas_channel,
    CATALOG_ACTION_MAP, CATALOG_VALUE_MAP, ROAS_MAP,
)

logger = logging.getLogger(__name__)

ACTION_MAP = {
    "link_click":                    "Link Clicks",
    "outbound_click":                "Outbound Clicks",
    "video_view":                    "3s Views",
    "video_thruplay_watched":        "Thruplay",
    "video_p25_watched_actions":     "View at 25%",
    "video_p50_watched_actions":     "View at 50%",
    "video_p75_watched_actions":     "View at 75%",
    "video_p100_watched_actions":    "View at 100%",
    "post_reaction":                 "Reaction",
    "like":                          "Like",
    "comment":                       "Comment",
    "post":                          "Share",
    "onsite_conversion.post_save":   "Save",
    "post_engagement":               "Post Engagements",
}

def flatten_row(row):
    flat = {
        "Ad Account ID":    row.get("account_id", ""),
        "Ad Account Name":  row.get("account_name", ""),
        "Campaign ID":      row.get("campaign_id", ""),
        "Campaign name":    row.get("campaign_name", ""),
        "Ad Set ID":        row.get("adset_id", ""),
        "Ad Set Name":      row.get("adset_name", ""),
        "Ad ID":            row.get("ad_id", ""),
        "Ad name":          row.get("ad_name", ""),
        "Amount spent":     float(row.get("spend", 0) or 0),
        "Reach":            int(row.get("reach", 0) or 0),
        "Frequency":        float(row.get("frequency", 0) or 0),
        "Impressions":      int(row.get("impressions", 0) or 0),
        "CPM":              float(row.get("cpm", 0) or 0),
        "CPC":              float(row.get("cpc", 0) or 0),
        "CTR":              float(row.get("ctr", 0) or 0),
        "Platform":         row.get("publisher_platform", ""),
        "Placement":        row.get("platform_position", ""),
        "Reporting starts": row.get("date_start", ""),
        "Reporting ends":   row.get("date_stop", ""),
        "Day":              row.get("date_start", ""),
        "Page Name":        "",
        "Campaign Start Date": "",
        "Campaign End Date":   "",
        "Campaign Budget":     "",
    }
    for col in set(ACTION_MAP.values()):
        flat[col] = 0.0
    for item in row.get("actions", []):
        atype = item.get("action_type", "")
        if atype in ACTION_MAP:
            try: flat[ACTION_MAP[atype]] = flat.get(ACTION_MAP[atype], 0.0) + float(item.get("value", 0))
            except (ValueError, TypeError): pass
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
                try: flat[col] = flat.get(col, 0.0) + float(item.get("value", 0))
                except (ValueError, TypeError): pass
    for col in set(CATALOG_ACTION_MAP.values()):
        flat[col] = 0.0
    for item in row.get("catalog_segment_actions", []):
        atype = item.get("action_type", "")
        if atype in CATALOG_ACTION_MAP:
            try: flat[CATALOG_ACTION_MAP[atype]] = flat.get(CATALOG_ACTION_MAP[atype], 0.0) + float(item.get("value", 0))
            except (ValueError, TypeError): pass
    for col in set(CATALOG_VALUE_MAP.values()):
        flat[col] = 0.0
    for item in row.get("catalog_segment_value", []):
        atype = item.get("action_type", "")
        if atype in CATALOG_VALUE_MAP:
            try: flat[CATALOG_VALUE_MAP[atype]] = flat.get(CATALOG_VALUE_MAP[atype], 0.0) + float(item.get("value", 0))
            except (ValueError, TypeError): pass
    for col in set(ROAS_MAP.values()):
        flat[col] = 0.0
    for item in row.get("purchase_roas", []):
        atype = item.get("action_type", "")
        if atype in ROAS_MAP:
            try: flat[ROAS_MAP[atype]] = float(item.get("value", 0))
            except (ValueError, TypeError): pass
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

    df["Brand"]         = df["Campaign name"].apply(get_an_value)
    df["Boutique"]      = df["Campaign name"].apply(get_boutique)
    df["Campaign"]      = df["Campaign name"].apply(get_campaign)

    raw_ob = df["Campaign name"].apply(get_objective)
    df["Objective"] = df.apply(
        lambda r: get_objective_kol(raw_ob[r.name], r["Ad Account Name"]), axis=1
    )

    df["TA"]              = df["Ad Set Name"].apply(get_ta)
    df["Creative Name"]   = df["Ad name"].apply(get_creative_name)
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

    df["Optimization"]  = df["Campaign name"].apply(get_optimization)
    df["TA#"]           = ""
    df["TA Name"]       = df["Ad Set Name"].apply(get_ta_name)
    df["Creative Seq."] = df["Ad name"].apply(get_creative_seq)
    df["Creative Type"] = df["Creative Name"].apply(get_creative_type)
    df["OB~"]           = df.apply(
        lambda r: "SALES-PCS" if "CPAS" in str(r["Ad Account Name"]) else "", axis=1
    )

    if fx_rates:
        def to_usd(r):
            rate = fx_rates.get(r["Market"], 0)
            return round(r["Amount spent"] / rate, 2) if rate else ""
        df["Amount Spent (USD)"] = df.apply(to_usd, axis=1)
    else:
        df["Amount Spent (USD)"] = ""

    return df[OUTPUT_COLUMNS].reset_index(drop=True)


def _empty_dataframe():
    return pd.DataFrame(columns=OUTPUT_COLUMNS)


OUTPUT_COLUMNS = [
    "Market", "FY", "Year", "Month", "Date",
    "Category Type", "Category",
    "Brand", "Boutique", "Campaign", "Optimization",
    "Objective", "Channel",
    "TA", "TA#", "TA Name",
    "Creative Name", "Creative Tag", "Creative Code", "Creative Format",
    "Creative Seq.", "Creative Type",
    "P2P", "Content Type", "OB~",
    "Ad Account ID", "Ad Account Name",
    "Campaign ID", "Campaign name",
    "Ad Set ID", "Ad Set Name",
    "Ad ID", "Ad name",
    "Page Name", "Post URL", "Creative Image URL", "Creative Video URL",
    "Platform", "Placement",
    "Campaign Start Date", "Campaign End Date", "Campaign Budget",
    "Amount spent", "Amount Spent (USD)",
    "Reach", "Frequency", "Impressions",
    "CPM", "CPC", "CTR",
    "Link Clicks", "Outbound Clicks",
    "3s Views", "Thruplay",
    "View at 25%", "View at 50%", "View at 75%", "View at 100%",
    "Reaction", "Like", "Comment", "Share", "Save",
    "Post Engagements",
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
    "Reporting starts", "Reporting ends",
]
