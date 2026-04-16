"""
Unit tests for kol_transformer.py parsing logic.
Run: python scripts/test_kol_transformer.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.kol_transformer import (
    get_market_from_account,
    get_fy,
    get_an_value,
    get_boutique,
    get_objective,
    get_campaign,
    get_ta,
    get_creative_name,
    get_creative_tag,
    get_p2p,
    get_creative_code,
    get_channel_from_tag,
    get_creative_format,
    map_objective,
    get_category_type_and_category,
    get_kol_name_from_tag,
    get_content_type,
    get_objective_kol,
)
import pandas as pd

# ── Real naming samples ───────────────────────────────────────────────────────

CAMP = "CP~SCTWFBA259097[SOC]_AN~EC Ariel_CN~Ariel@FabricCareKOLJun'25:崇崇(Post1)#6/11-6/18_YR~2025_MK~TW_OB~CW-LC_RT~Auction_CY~TWD_101482"
ADSET = "CP~SCTWFBA259097SOC_DT~CROSS_CH~Digital Social_IT~FB/IG-NF/S_FM~SOCIAL_MK~TW_ST~INT[P25-54 & [Home Appliances (consumer electronics) / Dehumidifier / Clothes dryer / Washing machine]]_AG~[DS>Social,DP>Social,DT>3PD,TT>Others,Cross>N,TM>N,ID>NA,DF>0]_DA~SOCIAL_AS~Ad 1"
AD = "CP~SCTWFBA259097SOC_DT~CROSS_CH~Digital Social_IT~FB/IG-NF/S_FM~Link Post_MK~TW_ST~INT[P25-54 & [Home Appliances (consumer electronics) / Dehumidifier / Clothes dryer / Washing machine]]_AG~[DS>Social,DP>Social,DT>3PD,TT>Others,Cross>N,TM>N,ID>NA,DF>0]_DA~SOCIAL_AS~Ad1-MO-LIQ:CLTPR#Chung-Chungalwayson-MO-0611-display"

ACCT_TW = "EC Ariel TW KOL CY~TWD"
ACCT_HK = "EC Brand HK KOL CY~HKD"

# Derived from AD name
CREATIVE_NAME = "Ad1-MO-LIQ:CLTPR#Chung-Chungalwayson-MO-0611-display"
CREATIVE_TAG  = "CLTPR#Chung-Chungalwayson-MO-0611-display"


def test(name, got, expected):
    status = "PASS" if got == expected else "FAIL"
    if status == "FAIL":
        print(f"  [FAIL] {name}")
        print(f"         got:      {repr(got)}")
        print(f"         expected: {repr(expected)}")
    else:
        print(f"  [PASS] {name}")
    return status == "PASS"


def run_all():
    results = []

    print("\n── Market ──────────────────────────────────────────")
    results += [
        test("TW from TWD", get_market_from_account(ACCT_TW), "TW"),
        test("HK from HKD", get_market_from_account(ACCT_HK), "HK"),
        test("empty",       get_market_from_account("no currency"), ""),
    ]

    print("\n── FY ──────────────────────────────────────────────")
    results += [
        test("Jun 2025 → FY2425", get_fy(pd.Timestamp("2025-06-11")), "FY2425"),
        test("Jul 2025 → FY2526", get_fy(pd.Timestamp("2025-07-01")), "FY2526"),
        test("Jan 2025 → FY2425", get_fy(pd.Timestamp("2025-01-01")), "FY2425"),
    ]

    print("\n── Brand (AN value) ────────────────────────────────")
    results += [
        test("Brand from campaign", get_an_value(CAMP), "EC Ariel"),
        test("None → empty",        get_an_value(None), ""),
    ]

    print("\n── Boutique ────────────────────────────────────────")
    results += [
        test("Boutique from campaign", get_boutique(CAMP), "Ariel"),
        test("no @ → empty",           get_boutique("CP~X_CN~NoBoutique_YR~2025"), ""),
        test("None → empty",           get_boutique(None), ""),
    ]

    print("\n── Objective ───────────────────────────────────────")
    results += [
        test("Objective CW-LC",  get_objective(CAMP), "CW-LC"),
        test("None → empty",     get_objective(None), ""),
        test("no OB~ → empty",   get_objective("CP~X_CN~Y_YR~2025"), ""),
    ]

    print("\n── Campaign ────────────────────────────────────────")
    results += [
        test("Campaign full CN~..._YR~",
             get_campaign(CAMP),
             "Ariel@FabricCareKOLJun'25:崇崇(Post1)#6/11-6/18"),
        test("None → empty", get_campaign(None), ""),
    ]

    print("\n── TA ──────────────────────────────────────────────")
    results += [
        test("TA from nested brackets",
             get_ta(ADSET),
             "P25-54 & [Home Appliances (consumer electronics) / Dehumidifier / Clothes dryer / Washing machine]"),
        test("None → empty", get_ta(None), ""),
    ]

    print("\n── Creative Name ───────────────────────────────────")
    results += [
        test("Creative Name after _AS~",
             get_creative_name(AD),
             CREATIVE_NAME),
        test("None → empty", get_creative_name(None), ""),
    ]

    print("\n── Creative Tag ────────────────────────────────────")
    results += [
        test("Creative Tag after :",
             get_creative_tag(CREATIVE_NAME),
             CREATIVE_TAG),
        test("no colon → empty",
             get_creative_tag("Ad1-MO-LIQ"),
             ""),
        test("None → empty", get_creative_tag(None), ""),
    ]

    print("\n── P2P ─────────────────────────────────────────────")
    results += [
        test("P2P between : and #",
             get_p2p(CREATIVE_NAME),
             "CLTPR"),
        test("no # → empty",  get_p2p("Ad1:CLTPR"), ""),
        test("None → empty",  get_p2p(None), ""),
    ]

    print("\n── Creative Code ───────────────────────────────────")
    results += [
        test("Code = 2nd segment after #",
             get_creative_code(CREATIVE_TAG),
             "Chungalwayson"),
        test("None → empty", get_creative_code(None), ""),
    ]

    print("\n── Channel (from tag) ──────────────────────────────")
    results += [
        test("Channel = 3rd segment after #",
             get_channel_from_tag(CREATIVE_TAG),
             "MO"),
        test("None → empty", get_channel_from_tag(None), ""),
    ]

    print("\n── Creative Format ─────────────────────────────────")
    results += [
        test("Format = last segment after #",
             get_creative_format(CREATIVE_TAG),
             "display"),
        test("None → empty", get_creative_format(None), ""),
    ]

    print("\n── Objective mapping ───────────────────────────────")
    results += [
        test("CW-LC → Traffic",       map_objective("CW-LC"),  "Traffic"),
        test("BA-RH → Awareness",     map_objective("BA-RH"),  "Awareness"),
        test("BA-ARL → Awareness",    map_objective("BA-ARL"), "Awareness"),
        test("EN-TP → Video Views",   map_objective("EN-TP"),  "Video Views"),
        test("BA-TP → Video Views",   map_objective("BA-TP"),  "Video Views"),
        test("unknown passthrough",   map_objective("XY-ZZ"),  "XY-ZZ"),
        test("empty → empty",         map_objective(""),       ""),
        test("None → empty",          map_objective(None),     ""),
    ]

    print("\n── Category mapping (Brand → Type + Category) ──────")
    results += [
        test("Whisper",         get_category_type_and_category("Whisper"),         ("Brand", "Fem Care")),
        test("Ariel",           get_category_type_and_category("Ariel"),           ("Brand", "Fabric Care")),
        test("EC Ariel",        get_category_type_and_category("EC Ariel"),        ("EC",    "EC Fabric Care")),
        test("EC Hair Recipe",  get_category_type_and_category("EC Hair Recipe"),  ("EC",    "EC Hair Care")),
        test("Oral-B",          get_category_type_and_category("Oral-B"),          ("Brand", "Oral Care")),
        test("OralB",           get_category_type_and_category("OralB"),           ("Brand", "Oral Care")),
        test("First Aid Beauty",get_category_type_and_category("First Aid Beauty"),("",      "Skin Care")),
        test("unknown brand",   get_category_type_and_category("Unknown"),         ("",      "")),
    ]

    print("\n── Content Type ────────────────────────────────────")
    results += [
        # KOL Boosting: account contains KOL
        test("KOL account → KOL Boosting",
             get_content_type("EC Ariel TW KOL CY~TWD", CREATIVE_TAG),
             "KOL Boosting"),
        # Buyout: non-KOL account, KOL name present after #
        test("non-KOL + KOL name → Buyout",
             get_content_type("EC Ariel TW Brand CY~TWD", "CLTPR#Chung-Chungalwayson-MO-0611-display"),
             "Buyout"),
        # Empty: non-KOL account, no KOL name (# followed by -)
        test("non-KOL + no KOL name → empty",
             get_content_type("EC Ariel TW Brand CY~TWD", "CLTPR#-WATRdpKylie-WA-0409-display"),
             ""),
        # Empty: non-KOL, no creative tag
        test("non-KOL + no tag → empty",
             get_content_type("EC Ariel TW Brand CY~TWD", ""),
             ""),
    ]

    print("\n── KOL name from tag ───────────────────────────────")
    results += [
        test("has KOL name",    get_kol_name_from_tag("CLTPR#Chung-Chungalwayson-MO-0611-display"), "Chung"),
        test("empty KOL name",  get_kol_name_from_tag("CLTPR#-WATRdpKylie-WA-0409-display"), ""),
        test("no # → empty",    get_kol_name_from_tag("CLTPR-display"), ""),
        test("None → empty",    get_kol_name_from_tag(None), ""),
    ]

    print("\n── Objective KOL (with CPAS override) ─────────────")
    results += [
        test("CPAS account → PRODUCT_CATALOG_SALES",
             get_objective_kol("CW-LC", "EC Whisper HKTVMall CPAS HKD"),
             "PRODUCT_CATALOG_SALES"),
        test("non-CPAS account → mapped OB",
             get_objective_kol("CW-LC", "EC Ariel TW KOL CY~TWD"),
             "Traffic"),
        test("non-CPAS unknown OB → passthrough",
             get_objective_kol("XY-ZZ", "EC Ariel TW Brand CY~TWD"),
             "XY-ZZ"),
        test("CPAS account overrides even known OB",
             get_objective_kol("BA-RH", "EC Whisper CPAS TWD"),
             "PRODUCT_CATALOG_SALES"),
    ]

    passed = sum(results)
    total  = len(results)
    print(f"\n{'='*52}")
    print(f"Results: {passed}/{total} passed")
    if passed < total:
        print("⚠️  Some tests failed — review parsing rules above")
        sys.exit(1)
    else:
        print("All tests passed ✓")


if __name__ == "__main__":
    run_all()
