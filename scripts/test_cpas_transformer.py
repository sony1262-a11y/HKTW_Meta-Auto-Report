"""
Unit tests for cpas_transformer.py parsing logic.
Run: python -m pytest scripts/test_cpas_transformer.py -v
  or: python scripts/test_cpas_transformer.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.cpas_transformer import (
    get_market_from_account,
    get_fy,
    get_brand,
    get_campaign,
    get_optimization,
    get_ta_name,
    get_creative_name,
    get_creative_seq,
    get_creative_type,
    get_channel,
    get_an_value,
)
import pandas as pd

# ── Real naming samples from briefing ────────────────────────────────────────

CAMP_HK = "CP~PG007787_AN~EC Whisper_CN~Whisper@HKTVMall x Fem Infinity TPR (Mega Sale)Nov'23_YR~2023_MK~HK_OB~SALES-PCS_RT~Auction_CY~HKD"
CAMP_TW = "CP~PG007467_AN~EC Whisper_CN~Whisper@WHP momo CPAS FY2324:(ViewContent)_YR~2023_MK~TW_OB~SALES-PCS_RT~Auction_CY~TWD"

ADSET_HK = "CP~PG007787_DT~MB_CH~Digital Social_IT~AUTO_FM~SOCIAL_MK~HK_ST~CA[P 18-65+,(Purchase) Viewed+ATC+Repeated Purhcase]_AG~[DS>Social,DP>Social,DT>1PD,TT>Site Tracker,Cross>N,TM>N,ID>NA,DF>0]_DA~SOCIAL_AS~Ad 3"
ADSET_TW = "CP~PG007467_DT~CROSS_CH~Digital Social_IT~AUTO_FM~SOCIAL_MK~TW_ST~CA[P 18-65+,Automated LaL View Content/Add2Cart(WHS products)P30d]_AG~[DS>Social,DP>Social,DT>1PD+LAL,TT>Others,Cross>N,TM>N,ID>NA,DF>0]_DA~SOCIAL_AS~Ad 1"

AD_HK = "CP~PG007787_DT~MB_CH~Digital Social_IT~AUTO_FM~Collection_MK~HK_ST~CA[P 18-65+,(Purchase) Viewed+ATC+Repeated Purhcase]_AG~[DS>Social,DP>Social,DT>1PD,TT>Site Tracker,Cross>N,TM>N,ID>NA,DF>0]_DA~SOCIAL_AS~Ad 3:CL-INFTPRv2-HT-1103-display"
AD_TW  = "CP~PG007467_DT~CROSS_CH~Digital Social_IT~AUTO_FM~Collection_MK~TW_ST~CA[P 18-65+,Automated LaL View Content/Add2Cart(WHS products)P30d]_AG~[DS>Social,DP>Social,DT>1PD+LAL,TT>Others,Cross>N,TM>N,ID>NA,DF>0]_DA~SOCIAL_AS~Ad Jul23-07160718-TA3-01-WHP-Collection10801080:CL-CPASTestingTA3-MO-0716-display"

ACCT_HK = "EC Whisper HKTVMall CPAS CY~HKD"
ACCT_TW = "EC Whisper Momo CPAS CY~TWD"


def test(name, got, expected):
    status = "PASS" if got == expected else "FAIL"
    if status == "FAIL":
        print(f"  [{status}] {name}")
        print(f"         got:      {repr(got)}")
        print(f"         expected: {repr(expected)}")
    else:
        print(f"  [{status}] {name}")
    return status == "PASS"


def run_all():
    results = []

    print("\n── Market ──────────────────────────────────────────")
    results += [
        test("HK from HKD account",  get_market_from_account(ACCT_HK), "HK"),
        test("TW from TWD account",  get_market_from_account(ACCT_TW), "TW"),
        test("empty on no currency", get_market_from_account("EC Brand CPAS"), ""),
    ]

    print("\n── FY ──────────────────────────────────────────────")
    results += [
        test("Aug 2023 → FY2324",  get_fy(pd.Timestamp("2023-08-01")), "FY2324"),
        test("Jan 2024 → FY2324",  get_fy(pd.Timestamp("2024-01-15")), "FY2324"),
        test("Jun 2024 → FY2324",  get_fy(pd.Timestamp("2024-06-30")), "FY2324"),
        test("Jul 2024 → FY2425",  get_fy(pd.Timestamp("2024-07-01")), "FY2425"),
        test("Mar 2025 → FY2425",  get_fy(pd.Timestamp("2025-03-10")), "FY2425"),
    ]

    print("\n── Brand ───────────────────────────────────────────")
    results += [
        test("HK Whisper",                get_brand(CAMP_HK), "Whisper"),
        test("TW Whisper",                get_brand(CAMP_TW), "Whisper"),
        test("no @ → empty",              get_brand("CP~X_CN~NoBrand_YR~2023"), ""),
        test("None input → empty",        get_brand(None), ""),
    ]

    print("\n── Campaign ────────────────────────────────────────")
    results += [
        test("HK campaign",
             get_campaign(CAMP_HK),
             "Whisper@HKTVMall x Fem Infinity TPR (Mega Sale)Nov'23"),
        test("TW campaign",
             get_campaign(CAMP_TW),
             "Whisper@WHP momo CPAS FY2324:(ViewContent)"),
    ]

    print("\n── Optimization ────────────────────────────────────")
    results += [
        test("TW has optimization",  get_optimization(CAMP_TW), "ViewContent"),
        test("HK no :() → empty",    get_optimization(CAMP_HK), ""),
        test("None → empty",         get_optimization(None), ""),
    ]

    print("\n── TA Name ─────────────────────────────────────────")
    results += [
        test("HK first []",
             get_ta_name(ADSET_HK),
             "P 18-65+,(Purchase) Viewed+ATC+Repeated Purhcase"),
        test("TW first []",
             get_ta_name(ADSET_TW),
             "P 18-65+,Automated LaL View Content/Add2Cart(WHS products)P30d"),
    ]

    print("\n── Creative Name ───────────────────────────────────")
    results += [
        test("HK creative name", get_creative_name(AD_HK), "CL-INFTPRv2-HT-1103-display"),
        test("TW creative name", get_creative_name(AD_TW), "CL-CPASTestingTA3-MO-0716-display"),
    ]

    print("\n── Creative Seq. ───────────────────────────────────")
    results += [
        test("HK seq",  get_creative_seq(AD_HK), "Ad 3"),
        test("TW seq",  get_creative_seq(AD_TW), "Ad Jul23-07160718-TA3-01-WHP-Collection10801080"),
    ]

    print("\n── Creative Type ───────────────────────────────────")
    results += [
        test("display type HK", get_creative_type("CL-INFTPRv2-HT-1103-display"), "display"),
        test("display type TW", get_creative_type("CL-CPASTestingTA3-MO-0716-display"), "display"),
        test("empty input",     get_creative_type(""), ""),
    ]

    print("\n── Category & Funding Source (AN value) ────────────")
    results += [
        test("HK AN value",
             get_an_value(CAMP_HK),
             "EC Whisper"),
        test("TW AN value",
             get_an_value(CAMP_TW),
             "EC Whisper"),
        test("no AN token → empty",
             get_an_value("CP~X_CN~Brand@Channel_YR~2023"),
             ""),
        test("None → empty",
             get_an_value(None),
             ""),
    ]

    print("\n── Channel ─────────────────────────────────────────")
    results += [
        test("HKTVMall",   get_channel("EC Whisper HKTVMall CPAS HKD"), "HKTVMall"),
        test("Momo",       get_channel("EC Whisper Momo CPAS TWD"),     "Momo"),
        test("momo lower", get_channel("EC Brand momo CPAS TWD"),       "Momo"),
        test("iWAT→Watsons", get_channel("EC Brand iWAT CPAS HKD"),     "Watsons"),
        test("Watsons",    get_channel("EC Brand Watsons CPAS HKD"),    "Watsons"),
        test("Shopee",     get_channel("EC Brand Shopee CPAS TWD"),     "Shopee"),
        test("no match",   get_channel("EC Brand Unknown CPAS HKD"),    ""),
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
