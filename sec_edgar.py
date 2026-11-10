"""SEC EDGAR company facts connector for ORBITE.
Uses public SEC company tickers and XBRL companyfacts endpoints.
Set SEC_USER_AGENT to a real contact string before production use.
"""
from __future__ import annotations
import os, re, requests
import pandas as pd
from functools import lru_cache

SEC_HEADERS = {
    "User-Agent": os.getenv("SEC_USER_AGENT", "ORBITE Financial Research contact@example.com"),
    "Accept-Encoding": "gzip, deflate",
    "Host": "data.sec.gov",
}
TICKER_HEADERS = {"User-Agent": SEC_HEADERS["User-Agent"]}
BASE = "https://data.sec.gov"

# Common US-GAAP XBRL concepts. A company may use a different extension/tag.
TAG_MAP = {
    "Revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet", "SalesRevenueGoodsNet"],
    "Cost of Revenue": ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold"],
    "Gross Profit": ["GrossProfit"],
    "Operating Income": ["OperatingIncomeLoss"],
    "Net Income": ["NetIncomeLoss", "ProfitLoss"],
    "Depreciation & Amortization": ["DepreciationDepletionAndAmortization", "DepreciationDepletionAndAmortizationPropertyPlantAndEquipment", "DepreciationAmortizationAndAccretionNet"],
    "Cash & Cash Equivalents": ["CashAndCashEquivalentsAtCarryingValue"],
    "Current Assets": ["AssetsCurrent"],
    "Total Assets": ["Assets"],
    "Current Liabilities": ["LiabilitiesCurrent"],
    "Total Liabilities": ["Liabilities"],
    "Long-Term Debt": ["LongTermDebtCurrent", "LongTermDebtNoncurrent", "LongTermDebt"],
    "Stockholders Equity": ["StockholdersEquity"],
    "Operating Cash Flow": ["NetCashProvidedByUsedInOperatingActivities"],
    "Capital Expenditure": ["PaymentsToAcquirePropertyPlantAndEquipment"],
    "Investing Cash Flow": ["NetCashProvidedByUsedInInvestingActivities"],
    "Financing Cash Flow": ["NetCashProvidedByUsedInFinancingActivities"],
}

@lru_cache(maxsize=1)
def _ticker_index():
    url = "https://www.sec.gov/files/company_tickers.json"
    r = requests.get(url, headers=TICKER_HEADERS, timeout=30)
    r.raise_for_status()
    raw = r.json()
    rows = list(raw.values())
    df = pd.DataFrame(rows)
    df["ticker"] = df["ticker"].astype(str).str.upper()
    df["cik_str"] = df["cik_str"].astype(int)
    return df

def search_company(query: str, limit: int = 10) -> pd.DataFrame:
    """Search SEC registrants by ticker or company-name substring."""
    q = re.sub(r"\s+", " ", str(query or "")).strip().upper()
    if not q:
        return pd.DataFrame(columns=["ticker", "title", "cik_str"])
    df = _ticker_index()
    exact = df[df["ticker"] == q]
    matches = df[df["title"].str.upper().str.contains(re.escape(q), na=False)]
    out = pd.concat([exact, matches]).drop_duplicates("cik_str").head(limit)
    return out[["ticker", "title", "cik_str"]].reset_index(drop=True)

def get_company_facts(cik: int | str) -> dict:
    cik10 = str(int(cik)).zfill(10)
    url = f"{BASE}/api/xbrl/companyfacts/CIK{cik10}.json"
    r = requests.get(url, headers=SEC_HEADERS, timeout=45)
    r.raise_for_status()
    return r.json()

def _fact_rows(facts: dict, concept: str) -> list[dict]:
    units = facts.get("facts", {}).get("us-gaap", {}).get(concept, {}).get("units", {})
    # Prefer USD when available; otherwise take first reported unit.
    unit = "USD" if "USD" in units else (next(iter(units), None))
    if not unit:
        return []
    return units[unit]

def extract_statements(facts: dict, forms=("10-K", "10-Q")) -> dict[str, pd.DataFrame]:
    """Return annual and quarterly filing observations by fiscal period.

    SEC facts are reported as filed. Some Q2/Q3 cash-flow and income values
    represent year-to-date amounts; they are deliberately not mislabelled as
    standalone quarters.
    """
    records = []
    for label, concepts in TAG_MAP.items():
        for concept in concepts:
            rows = _fact_rows(facts, concept)
            if not rows:
                continue
            for row in rows:
                form = row.get("form")
                if form not in forms:
                    continue
                end = row.get("end")
                if not end:
                    continue
                start = row.get("start")
                # Keep annual 10-K observations and quarterly 10-Q observations separately.
                if form == "10-K":
                    period_type = "Annual"
                    if start and (pd.Timestamp(end) - pd.Timestamp(start)).days < 300:
                        continue
                else:
                    period_type = "Quarterly filing"
                    if start and (pd.Timestamp(end) - pd.Timestamp(start)).days > 200:
                        # YTD observations are retained but identified as such.
                        pass
                records.append({
                    "Metric": label, "Concept": concept, "Period End": end,
                    "Period Start": start, "Filed": row.get("filed"),
                    "Fiscal Year": row.get("fy"), "Fiscal Period": row.get("fp"),
                    "Form": form, "Value": row.get("val"),
                    "Unit": "USD" if "USD" in facts.get("facts", {}).get("us-gaap", {}).get(concept, {}).get("units", {}) else "reported unit",
                    "Period Type": period_type,
                })
            # First available matching concept wins to prevent duplicate metric variants.
            if any(r["Metric"] == label for r in records):
                break
    df = pd.DataFrame(records)
    if df.empty:
        empty = pd.DataFrame()
        return {"annual": empty, "quarterly": empty, "observations": empty}
    df["Period End"] = pd.to_datetime(df["Period End"], errors="coerce")
    df["Filed"] = pd.to_datetime(df["Filed"], errors="coerce")
    df = df.sort_values(["Period End", "Filed", "Metric"]).drop_duplicates(
        subset=["Metric", "Period End", "Form", "Filed"], keep="last"
    )
    annual = df[df["Period Type"] == "Annual"].copy()
    quarterly = df[df["Period Type"] == "Quarterly filing"].copy()
    return {"annual": annual, "quarterly": quarterly, "observations": df}

def fetch_company_statements(query: str) -> dict:
    """Resolve a ticker/name, fetch SEC facts, and return metadata + statements."""
    matches = search_company(query, limit=10)
    if matches.empty:
        raise ValueError(f"Aucune société trouvée dans le registre SEC pour : {query}")
    # Prefer exact ticker, otherwise first name match.
    exact = matches[matches["ticker"].str.upper() == str(query).strip().upper()]
    company = (exact.iloc[0] if not exact.empty else matches.iloc[0]).to_dict()
    facts = get_company_facts(company["cik_str"])
    statements = extract_statements(facts)
    return {"company": company, **statements}

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Test ORBITE SEC EDGAR connector")
    parser.add_argument("company", nargs="?", default="MSFT")
    args = parser.parse_args()
    result = fetch_company_statements(args.company)
    print(f"Société : {result['company']['title']} ({result['company']['ticker']})")
    for key in ("annual", "quarterly"):
        df = result[key]
        print(f"\n{key.upper()} : {len(df)} observations")
        if not df.empty:
            print("Périodes disponibles :", df["Period End"].dt.strftime("%Y-%m-%d").drop_duplicates().tail(8).tolist())
            print(df[["Metric", "Period End", "Filed", "Form", "Value"]].tail(12).to_string(index=False))
