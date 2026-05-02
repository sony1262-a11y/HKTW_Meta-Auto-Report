"""Unit tests for kol_transformer.py"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.kol_transformer import (
    get_market_from_account, get_fy, get_an_value, get_boutique, get_objective, get_campaign,
    get_ta, get_creative_name, get_creative_tag, get_p2p, get_creative_code, get_channel_from_tag,
    get_creative_format, map_objective, get_category_type_and_category, get_kol_name_from_tag,
    get_content_type, get_objective_kol,
)
import pandas as pd

CAMP = "CP~SCTWFBA259097[SOC]_AN~EC Ariel_CN~Ariel@FabricCareKOLJun'25:崇崇(Post1)#6/11-6/18_YR~2025_MK~TW_OB~CW-LC_RT~Auction_CY~TWD_101482"
ADSET = "CP~SCTWFBA259097SOC_DT~CROSS_CH~Digital Social_IT~FB/IG-NF/S_FM~SOCIAL_MK~TW_ST~INT[P25-54 & [Home Appliances (consumer electronics) / Dehumidifier / Clothes dryer / Washing machine]]_AG~[...]_DA~SOCIAL_AS~Ad 1"
AD = "CP~SCTWFBA259097SOC_DT~CROSS_CH~Digital Social_IT~FB/IG-NF/S_FM~Link Post_MK~TW_ST~INT[P25-54 & [Home Appliances...]]_AG~[...]_DA~SOCIAL_AS~Ad1-MO-LIQ:CLTPR#Chung-Chungalwayson-MO-0611-display"
ACCT_TW = "EC Ariel TW KOL CY~TWD"; ACCT_HK = "EC Brand HK KOL CY~HKD"
CREATIVE_NAME = "Ad1-MO-LIQ:CLTPR#Chung-Chungalwayson-MO-0611-display"
CREATIVE_TAG  = "CLTPR#Chung-Chungalwayson-MO-0611-display"

def test(name, got, expected):
    status = "PASS" if got == expected else "FAIL"
    if status == "FAIL": print(f"  [FAIL] {name}\n         got: {repr(got)}\n         expected: {repr(expected)}")
    else: print(f"  [PASS] {name}")
    return status == "PASS"

def run_all():
    results = []
    print("\n-- Market --")
    results += [test("TW", get_market_from_account(ACCT_TW), "TW"), test("HK", get_market_from_account(ACCT_HK), "HK"), test("empty", get_market_from_account("no currency"), "")]
    print("\n-- FY --")
    results += [test("Jun25->FY2425", get_fy(pd.Timestamp("2025-06-11")), "FY2425"), test("Jul25->FY2526", get_fy(pd.Timestamp("2025-07-01")), "FY2526"), test("Jan25->FY2425", get_fy(pd.Timestamp("2025-01-01")), "FY2425")]
    print("\n-- Brand (AN) --")
    results += [test("EC Ariel", get_an_value(CAMP), "EC Ariel"), test("None", get_an_value(None), "")]
    print("\n-- Boutique --")
    results += [test("Ariel", get_boutique(CAMP), "Ariel"), test("no @", get_boutique("CP~X_CN~NoBoutique_YR~2025"), ""), test("None", get_boutique(None), "")]
    print("\n-- Objective --")
    results += [test("CW-LC", get_objective(CAMP), "CW-LC"), test("None", get_objective(None), ""), test("no OB~", get_objective("CP~X_CN~Y_YR~2025"), "")]
    print("\n-- Campaign --")
    results += [test("campaign", get_campaign(CAMP), "Ariel@FabricCareKOLJun'25:崇崇(Post1)#6/11-6/18"), test("None", get_campaign(None), "")]
    print("\n-- TA --")
    results += [test("nested brackets", get_ta(ADSET), "P25-54 & [Home Appliances (consumer electronics) / Dehumidifier / Clothes dryer / Washing machine]"), test("None", get_ta(None), "")]
    print("\n-- Creative Name --")
    results += [test("after _AS~", get_creative_name(AD), CREATIVE_NAME), test("None", get_creative_name(None), "")]
    print("\n-- Creative Tag --")
    results += [test("after :", get_creative_tag(CREATIVE_NAME), CREATIVE_TAG), test("no colon", get_creative_tag("Ad1-MO-LIQ"), ""), test("None", get_creative_tag(None), "")]
    print("\n-- P2P --")
    results += [test("CLTPR", get_p2p(CREATIVE_NAME), "CLTPR"), test("no #", get_p2p("Ad1:CLTPR"), ""), test("None", get_p2p(None), "")]
    print("\n-- Creative Code --")
    results += [test("2nd segment", get_creative_code(CREATIVE_TAG), "Chungalwayson"), test("None", get_creative_code(None), "")]
    print("\n-- Channel --")
    results += [test("MO", get_channel_from_tag(CREATIVE_TAG), "MO"), test("None", get_channel_from_tag(None), "")]
    print("\n-- Creative Format --")
    results += [test("display", get_creative_format(CREATIVE_TAG), "display"), test("None", get_creative_format(None), "")]
    print("\n-- Objective mapping --")
    results += [test("CW-LC->Traffic", map_objective("CW-LC"), "Traffic"), test("BA-RH->Awareness", map_objective("BA-RH"), "Awareness"), test("EN-TP->Video Views", map_objective("EN-TP"), "Video Views"), test("unknown passthrough", map_objective("XY-ZZ"), "XY-ZZ"), test("empty", map_objective(""), ""), test("None", map_objective(None), "")]
    print("\n-- Category --")
    results += [test("Whisper", get_category_type_and_category("Whisper"), ("Brand","Fem Care")), test("Ariel", get_category_type_and_category("Ariel"), ("Brand","Fabric Care")), test("EC Ariel", get_category_type_and_category("EC Ariel"), ("EC","EC Fabric Care")), test("First Aid Beauty", get_category_type_and_category("First Aid Beauty"), ("","Skin Care")), test("unknown", get_category_type_and_category("Unknown"), ("",""))]
    print("\n-- Content Type --")
    results += [test("KOL account", get_content_type("EC Ariel TW KOL CY~TWD", CREATIVE_TAG), "KOL Boosting"), test("non-KOL + KOL name", get_content_type("EC Ariel TW Brand CY~TWD", "CLTPR#Chung-display"), "Buyout"), test("non-KOL + no name", get_content_type("EC Ariel TW Brand CY~TWD", "CLTPR#-WATRdpKylie-display"), ""), test("non-KOL + no tag", get_content_type("EC Ariel TW Brand CY~TWD", ""), "")]
    print("\n-- KOL name --")
    results += [test("has name", get_kol_name_from_tag("CLTPR#Chung-Chungalwayson-MO-0611-display"), "Chung"), test("empty name", get_kol_name_from_tag("CLTPR#-WATRdpKylie-WA-0409-display"), ""), test("no #", get_kol_name_from_tag("CLTPR-display"), ""), test("None", get_kol_name_from_tag(None), "")]
    print("\n-- Objective KOL --")
    results += [test("CPAS -> PCS", get_objective_kol("CW-LC", "EC Whisper HKTVMall CPAS HKD"), "PRODUCT_CATALOG_SALES"), test("non-CPAS -> mapped", get_objective_kol("CW-LC", "EC Ariel TW KOL CY~TWD"), "Traffic"), test("non-CPAS unknown", get_objective_kol("XY-ZZ", "EC Ariel TW Brand CY~TWD"), "XY-ZZ")]
    passed = sum(results); total = len(results)
    print(f"\n====================================================")
    print(f"Results: {passed}/{total} passed")
    if passed < total: print("Some tests failed"); sys.exit(1)
    else: print("All tests passed ✓")
    print("====================================================")

if __name__ == "__main__":
    run_all()
