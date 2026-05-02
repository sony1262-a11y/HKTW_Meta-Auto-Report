"""Unit tests for cpas_transformer.py"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.cpas_transformer import (
    get_market_from_account, get_fy, get_brand, get_campaign, get_optimization,
    get_ta_name, get_creative_name, get_creative_seq, get_creative_type, get_channel, get_an_value,
)
import pandas as pd

CAMP_HK = "CP~PG007787_AN~EC Whisper_CN~Whisper@HKTVMall x Fem Infinity TPR (Mega Sale)Nov'23_YR~2023_MK~HK_OB~SALES-PCS_RT~Auction_CY~HKD"
CAMP_TW = "CP~PG007467_AN~EC Whisper_CN~Whisper@WHP momo CPAS FY2324:(ViewContent)_YR~2023_MK~TW_OB~SALES-PCS_RT~Auction_CY~TWD"
ADSET_HK = "CP~PG007787_DT~MB_CH~Digital Social_IT~AUTO_FM~SOCIAL_MK~HK_ST~CA[P 18-65+,(Purchase) Viewed+ATC+Repeated Purhcase]_AG~[...]_DA~SOCIAL_AS~Ad 3"
ADSET_TW = "CP~PG007467_DT~CROSS_CH~Digital Social_IT~AUTO_FM~SOCIAL_MK~TW_ST~CA[P 18-65+,Automated LaL View Content/Add2Cart(WHS products)P30d]_AG~[...]_DA~SOCIAL_AS~Ad 1"
AD_HK = "CP~PG007787_DT~MB_CH~Digital Social_IT~AUTO_FM~Collection_MK~HK_ST~CA[P 18-65+,(Purchase) Viewed+ATC+Repeated Purhcase]_AG~[...]_DA~SOCIAL_AS~Ad 3:CL-INFTPRv2-HT-1103-display"
AD_TW  = "CP~PG007467_DT~CROSS_CH~Digital Social_IT~AUTO_FM~Collection_MK~TW_ST~CA[P 18-65+,Automated LaL View Content/Add2Cart(WHS products)P30d]_AG~[...]_DA~SOCIAL_AS~Ad Jul23-07160718-TA3-01-WHP-Collection10801080:CL-CPASTestingTA3-MO-0716-display"
ACCT_HK = "EC Whisper HKTVMall CPAS CY~HKD"
ACCT_TW = "EC Whisper Momo CPAS CY~TWD"

def test(name, got, expected):
    status = "PASS" if got == expected else "FAIL"
    if status == "FAIL": print(f"  [FAIL] {name}\n         got: {repr(got)}\n         expected: {repr(expected)}")
    else: print(f"  [PASS] {name}")
    return status == "PASS"

def run_all():
    results = []
    print("\n-- Market --")
    results += [test("HK", get_market_from_account(ACCT_HK), "HK"), test("TW", get_market_from_account(ACCT_TW), "TW"), test("empty", get_market_from_account("EC"), "")]
    print("\n-- FY --")
    results += [test("Aug23->FY2324", get_fy(pd.Timestamp("2023-08-01")), "FY2324"), test("Jan24->FY2324", get_fy(pd.Timestamp("2024-01-15")), "FY2324"), test("Jul24->FY2425", get_fy(pd.Timestamp("2024-07-01")), "FY2425")]
    print("\n-- Brand --")
    results += [test("HK Whisper", get_brand(CAMP_HK), "Whisper"), test("TW Whisper", get_brand(CAMP_TW), "Whisper"), test("no @", get_brand("CP~X_CN~NoBrand_YR~2023"), ""), test("None", get_brand(None), "")]
    print("\n-- Campaign --")
    results += [test("HK campaign", get_campaign(CAMP_HK), "Whisper@HKTVMall x Fem Infinity TPR (Mega Sale)Nov'23"), test("TW campaign", get_campaign(CAMP_TW), "Whisper@WHP momo CPAS FY2324:(ViewContent)")]
    print("\n-- Optimization --")
    results += [test("TW opt", get_optimization(CAMP_TW), "ViewContent"), test("HK no opt", get_optimization(CAMP_HK), ""), test("None", get_optimization(None), "")]
    print("\n-- TA Name --")
    results += [test("HK TA", get_ta_name(ADSET_HK), "P 18-65+,(Purchase) Viewed+ATC+Repeated Purhcase"), test("TW TA", get_ta_name(ADSET_TW), "P 18-65+,Automated LaL View Content/Add2Cart(WHS products)P30d")]
    print("\n-- Creative Name --")
    results += [test("HK creative", get_creative_name(AD_HK), "CL-INFTPRv2-HT-1103-display"), test("TW creative", get_creative_name(AD_TW), "CL-CPASTestingTA3-MO-0716-display")]
    print("\n-- Creative Seq --")
    results += [test("HK seq", get_creative_seq(AD_HK), "Ad 3"), test("TW seq", get_creative_seq(AD_TW), "Ad Jul23-07160718-TA3-01-WHP-Collection10801080")]
    print("\n-- Creative Type --")
    results += [test("display HK", get_creative_type("CL-INFTPRv2-HT-1103-display"), "display"), test("display TW", get_creative_type("CL-CPASTestingTA3-MO-0716-display"), "display"), test("empty", get_creative_type(""), "")]
    print("\n-- AN value --")
    results += [test("HK AN", get_an_value(CAMP_HK), "EC Whisper"), test("TW AN", get_an_value(CAMP_TW), "EC Whisper"), test("no AN", get_an_value("CP~X_CN~Brand@Channel_YR~2023"), ""), test("None", get_an_value(None), "")]
    print("\n-- Channel --")
    results += [test("HKTVMall", get_channel("EC Whisper HKTVMall CPAS HKD"), "HKTVMall"), test("Momo", get_channel("EC Whisper Momo CPAS TWD"), "Momo"), test("momo lower", get_channel("EC Brand momo CPAS TWD"), "Momo"), test("iWAT->Watsons", get_channel("EC Brand iWAT CPAS HKD"), "Watsons"), test("Shopee", get_channel("EC Brand Shopee CPAS TWD"), "Shopee"), test("no match", get_channel("EC Brand Unknown CPAS HKD"), "")]
    passed = sum(results); total = len(results)
    print(f"\n====================================================")
    print(f"Results: {passed}/{total} passed")
    if passed < total: print("Some tests failed"); sys.exit(1)
    else: print("All tests passed ✓")
    print("====================================================")

if __name__ == "__main__":
    run_all()
