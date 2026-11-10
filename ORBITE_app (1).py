import io
from datetime import datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

# ============================================================
# ORBITE | MERIDIAN RISK ADVISORY
# Integrated Corporate Finance, Equity Research & Excel engine
# ============================================================

st.set_page_config(
    page_title="ORBITE | Financial Intelligence",
    page_icon="◈",
    layout="wide",
)

st.markdown(
    """
    <style>
    .stApp {background:#081321;color:#E8EDF5;}
    [data-testid="stSidebar"] {background:#101E30;}
    h1,h2,h3 {color:#E8EDF5;}
    [data-testid="stMetric"] {background:#13243A;border:1px solid #263B55;padding:14px;border-radius:10px;}
    div.stButton > button {background:#176B87;color:white;border-radius:7px;}
    </style>
    """,
    unsafe_allow_html=True,
)

# ----------------------------
# Constants and session state
# ----------------------------
FINANCIAL_ITEMS = [
    "Revenue", "EBITDA", "EBIT", "Net Income", "Cash & Equivalents",
    "Total Debt", "Shareholders' Equity", "Total Assets", "Current Assets",
    "Current Liabilities", "Operating Cash Flow", "CAPEX",
    "Shares Outstanding", "Share Price",
]
YEARS = 10

DEFAULTS = {
    "company": "",
    "ticker": "",
    "sector": "",
    "currency": "USD",
    "country": "",
    "historical_financials": pd.DataFrame(
        {"Financial Item": FINANCIAL_ITEMS, **{str(y): [np.nan] * len(FINANCIAL_ITEMS) for y in range(datetime.now().year - 9, datetime.now().year + 1)}}
    ),
    "market_history": pd.DataFrame(),
    "company_info": {},
    "last_refresh": "",
    "dcf_results": None,
    "dcf_forecast": pd.DataFrame(),
}

for key, value in DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = value.copy() if isinstance(value, (dict, pd.DataFrame)) else value


def safe_float(value, default=np.nan):
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def format_number(value, currency=""):
    value = safe_float(value)
    if pd.isna(value):
        return "N/A"
    return f"{value:,.2f}" + (f" {currency}" if currency else "")


def first_matching_row(frame, candidates):
    if frame is None or frame.empty:
        return None
    normalized = {str(idx).strip().lower(): idx for idx in frame.index}
    for candidate in candidates:
        key = candidate.strip().lower()
        if key in normalized:
            return normalized[key]
    for candidate in candidates:
        key = candidate.strip().lower()
        for normalized_key, original in normalized.items():
            if key in normalized_key or normalized_key in key:
                return original
    return None


def statement_value(frame, candidates, date_col):
    row = first_matching_row(frame, candidates)
    if row is None or date_col not in frame.columns:
        return np.nan
    return safe_float(frame.loc[row, date_col])


def get_annual_columns(frame):
    if frame is None or frame.empty:
        return []
    cols = []
    for col in frame.columns:
        try:
            cols.append(pd.Timestamp(col))
        except Exception:
            continue
    return sorted(cols, reverse=True)


def build_financial_history(ticker_obj, info):
    income = ticker_obj.financials
    balance = ticker_obj.balance_sheet
    cashflow = ticker_obj.cashflow

    dates = sorted(
        set(get_annual_columns(income) + get_annual_columns(balance) + get_annual_columns(cashflow)),
        reverse=True,
    )[:10]
    dates = sorted(dates)
    if not dates:
        raise ValueError("Aucun état financier annuel exploitable n'a été retourné par la source.")

    rows = {item: [] for item in FINANCIAL_ITEMS}
    year_labels = [str(d.year) for d in dates]

    for date in dates:
        revenue = statement_value(income, ["Total Revenue", "Operating Revenue", "Revenue"], date)
        ebit = statement_value(income, ["Operating Income", "EBIT"], date)
        net_income = statement_value(income, ["Net Income", "Net Income Common Stockholders", "Net Income From Continuing Operations"], date)
        ebitda = statement_value(income, ["EBITDA", "Normalized EBITDA"], date)
        depreciation = statement_value(cashflow, ["Depreciation And Amortization", "Depreciation Amortization Depletion"], date)
        if pd.isna(ebitda) and pd.notna(ebit) and pd.notna(depreciation):
            ebitda = ebit + abs(depreciation)

        cash = statement_value(balance, ["Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments", "Cash"], date)
        short_debt = statement_value(balance, ["Current Debt And Capital Lease Obligation", "Current Debt"], date)
        long_debt = statement_value(balance, ["Long Term Debt And Capital Lease Obligation", "Long Term Debt"], date)
        total_debt = statement_value(balance, ["Total Debt"], date)
        if pd.isna(total_debt):
            pieces = [v for v in [short_debt, long_debt] if pd.notna(v)]
            total_debt = sum(pieces) if pieces else np.nan

        equity = statement_value(balance, ["Stockholders Equity", "Common Stock Equity", "Total Equity Gross Minority Interest"], date)
        assets = statement_value(balance, ["Total Assets"], date)
        current_assets = statement_value(balance, ["Current Assets"], date)
        current_liabilities = statement_value(balance, ["Current Liabilities"], date)
        operating_cf = statement_value(cashflow, ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities", "Total Cash From Operating Activities"], date)
        capex_raw = statement_value(cashflow, ["Capital Expenditure", "Capital Expenditures"], date)
        capex = abs(capex_raw) if pd.notna(capex_raw) else np.nan

        is_latest_period = date == max(dates)
        latest_price = safe_float(info.get("currentPrice", info.get("regularMarketPrice")))
        values = {
            "Revenue": revenue,
            "EBITDA": ebitda,
            "EBIT": ebit,
            "Net Income": net_income,
            "Cash & Equivalents": cash,
            "Total Debt": total_debt,
            "Shareholders' Equity": equity,
            "Total Assets": assets,
            "Current Assets": current_assets,
            "Current Liabilities": current_liabilities,
            "Operating Cash Flow": operating_cf,
            "CAPEX": capex,
            "Shares Outstanding": safe_float(info.get("sharesOutstanding")) if is_latest_period else np.nan,
            "Share Price": latest_price if is_latest_period else np.nan,
        }
        for item in FINANCIAL_ITEMS:
            rows[item].append(values[item])

    result = pd.DataFrame(rows, index=year_labels).T
    result.insert(0, "Financial Item", result.index)
    result = result.reset_index(drop=True)
    return result


def search_companies(query):
    """Search public ticker listings through yfinance's Yahoo Finance search wrapper."""
    search = yf.Search(query, max_results=10)
    quotes = getattr(search, "quotes", []) or []
    results = []
    for quote in quotes:
        symbol = quote.get("symbol")
        if not symbol:
            continue
        results.append({
            "symbol": symbol,
            "name": quote.get("longname") or quote.get("shortname") or symbol,
            "exchange": quote.get("exchange", ""),
            "type": quote.get("quoteType", ""),
        })
    return results


def refresh_company(ticker_symbol):
    ticker_symbol = ticker_symbol.strip().upper()
    if not ticker_symbol:
        raise ValueError("Saisis un ticker valide.")
    obj = yf.Ticker(ticker_symbol)
    info = obj.get_info()
    if not info or (not info.get("longName") and not info.get("shortName")):
        # Some Yahoo instruments return limited profile data; statements may still work.
        info = info or {}
    history = obj.history(period="5y", auto_adjust=False)
    if (not info.get("currentPrice") and not info.get("regularMarketPrice")
            and history is not None and not history.empty):
        info["currentPrice"] = safe_float(history["Close"].dropna().iloc[-1])
    financials = build_financial_history(obj, info)

    st.session_state["ticker"] = ticker_symbol
    st.session_state["company"] = info.get("longName") or info.get("shortName") or ticker_symbol
    st.session_state["sector"] = info.get("sector") or info.get("industry") or "Non renseigné"
    st.session_state["country"] = info.get("country") or "Non renseigné"
    st.session_state["currency"] = info.get("currency") or "USD"
    st.session_state["company_info"] = info
    st.session_state["historical_financials"] = financials
    st.session_state["market_history"] = history
    st.session_state["last_refresh"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Populate legacy fields from latest available year for compatibility.
    year_cols = [c for c in financials.columns if str(c).isdigit()]
    latest = max(year_cols, key=lambda x: int(x))
    mapping = {
        "Revenue": "revenue", "EBITDA": "ebitda", "EBIT": "ebit",
        "Net Income": "net_income", "Cash & Equivalents": "cash",
        "Total Debt": "debt", "Shareholders' Equity": "equity",
        "Total Assets": "assets", "Current Assets": "current_assets",
        "Current Liabilities": "current_liabilities",
        "Operating Cash Flow": "operating_cashflow", "CAPEX": "capex",
        "Shares Outstanding": "shares", "Share Price": "share_price",
    }
    indexed = financials.set_index("Financial Item")
    for label, key in mapping.items():
        st.session_state[key] = safe_float(indexed.loc[label, latest], 0.0)


def calculate_analysis(financials):
    if financials is None or financials.empty:
        return pd.DataFrame()
    frame = financials.set_index("Financial Item").T.copy()
    frame.index = frame.index.astype(str)
    for col in frame.columns:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    if "Revenue" in frame:
        frame["Revenue Growth"] = frame["Revenue"].pct_change()
    if "EBITDA" in frame and "Revenue" in frame:
        frame["EBITDA Margin"] = frame["EBITDA"] / frame["Revenue"].replace(0, np.nan)
    if "EBIT" in frame and "Revenue" in frame:
        frame["EBIT Margin"] = frame["EBIT"] / frame["Revenue"].replace(0, np.nan)
    if "Net Income" in frame and "Revenue" in frame:
        frame["Net Profit Margin"] = frame["Net Income"] / frame["Revenue"].replace(0, np.nan)
    if "Operating Cash Flow" in frame and "CAPEX" in frame:
        frame["Free Cash Flow"] = frame["Operating Cash Flow"] - frame["CAPEX"]
    if "Total Debt" in frame and "Cash & Equivalents" in frame:
        frame["Net Debt"] = frame["Total Debt"] - frame["Cash & Equivalents"]
    if "Net Debt" in frame and "EBITDA" in frame:
        frame["Net Debt / EBITDA"] = frame["Net Debt"] / frame["EBITDA"].replace(0, np.nan)
    if "Net Income" in frame and "Shareholders' Equity" in frame:
        frame["ROE"] = frame["Net Income"] / frame["Shareholders' Equity"].replace(0, np.nan)
    if "Net Income" in frame and "Total Assets" in frame:
        frame["ROA"] = frame["Net Income"] / frame["Total Assets"].replace(0, np.nan)
    if "Current Assets" in frame and "Current Liabilities" in frame:
        frame["Current Ratio"] = frame["Current Assets"] / frame["Current Liabilities"].replace(0, np.nan)
    return frame


def build_excel_workbook():
    financials = st.session_state["historical_financials"].copy()
    analysis = calculate_analysis(financials)
    info = st.session_state.get("company_info", {})
    profile = pd.DataFrame({
        "Field": ["Company", "Ticker", "Sector", "Country", "Currency", "Last refresh", "Data source"],
        "Value": [st.session_state["company"], st.session_state["ticker"], st.session_state["sector"], st.session_state["country"], st.session_state["currency"], st.session_state["last_refresh"], "Yahoo Finance via yfinance"],
    })
    ratios = analysis[[c for c in ["Revenue Growth", "EBITDA Margin", "EBIT Margin", "Net Profit Margin", "Free Cash Flow", "Net Debt", "Net Debt / EBITDA", "ROE", "ROA", "Current Ratio"] if c in analysis.columns]].copy()
    ratios.index.name = "Fiscal Year"

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        profile.to_excel(writer, sheet_name="Company Profile", index=False)
        financials.to_excel(writer, sheet_name="Financial Statements", index=False)
        analysis.to_excel(writer, sheet_name="Financial Analysis")
        ratios.to_excel(writer, sheet_name="Key Ratios")
        assumptions = pd.DataFrame({
            "Assumption": ["Risk-free rate", "Beta", "Equity risk premium", "Cost of debt", "Tax rate", "FCF growth", "Terminal growth", "Forecast years"],
            "Value": [0.03, 1.0, 0.055, 0.05, 0.25, 0.05, 0.02, 5],
        })
        assumptions.to_excel(writer, sheet_name="Model Assumptions", index=False)

        # Add native Excel formulas to a dedicated model sheet.
        ws = writer.book.create_sheet("Excel Model")
        ws.append(["ORBITE | Excel Financial Model"])
        ws.append(["Metric", "Value", "Formula / Notes"])
        rows = [
            ["Latest Revenue", "=IFERROR(LOOKUP(2,1/('Financial Statements'!B2:K2<>""),'Financial Statements'!B2:K2),0)", "Latest populated Revenue value"],
            ["Latest EBITDA", "=IFERROR(LOOKUP(2,1/('Financial Statements'!B3:K3<>""),'Financial Statements'!B3:K3),0)", "Latest populated EBITDA value"],
            ["EBITDA Margin", "=IFERROR(B4/B3,0)", "EBITDA / Revenue"],
            ["Net Debt", "=IFERROR(LOOKUP(2,1/('Financial Statements'!B7:K7<>""),'Financial Statements'!B7:K7)-LOOKUP(2,1/('Financial Statements'!B6:K6<>""),'Financial Statements'!B6:K6),0)", "Latest available Total Debt less Cash"],
        ]
        for row in rows:
            ws.append(row)
        ws.column_dimensions["A"].width = 25
        ws.column_dimensions["B"].width = 24
        ws.column_dimensions["C"].width = 55
        for sheet in writer.book.worksheets:
            sheet.freeze_panes = "B2"
            sheet.auto_filter.ref = sheet.dimensions
            for col_cells in sheet.columns:
                max_len = max((len(str(cell.value)) if cell.value is not None else 0) for cell in col_cells)
                sheet.column_dimensions[col_cells[0].column_letter].width = min(max(max_len + 2, 12), 38)
    output.seek(0)
    return output.getvalue()


def import_excel_workbook(uploaded_file):
    workbook = pd.ExcelFile(uploaded_file)
    sheet_name = "Financial Statements" if "Financial Statements" in workbook.sheet_names else workbook.sheet_names[0]
    imported = pd.read_excel(workbook, sheet_name=sheet_name)
    if "Financial Item" not in imported.columns:
        raise ValueError("La feuille doit contenir une colonne 'Financial Item'.")
    missing = [item for item in FINANCIAL_ITEMS if item not in imported["Financial Item"].astype(str).tolist()]
    if missing:
        raise ValueError("Lignes financières manquantes : " + ", ".join(missing))
    st.session_state["historical_financials"] = imported
    if "Company Profile" in workbook.sheet_names:
        profile = pd.read_excel(workbook, sheet_name="Company Profile")
        if {"Field", "Value"}.issubset(profile.columns):
            values = dict(zip(profile["Field"].astype(str), profile["Value"]))
            for field, key in [("Company", "company"), ("Ticker", "ticker"), ("Sector", "sector"), ("Country", "country"), ("Currency", "currency")]:
                if field in values and pd.notna(values[field]):
                    st.session_state[key] = str(values[field])

# ----------------------------
# Header and navigation
# ----------------------------
st.sidebar.markdown("# ◈ ORBITE")
st.sidebar.caption("MERIDIAN RISK ADVISORY")
st.sidebar.divider()
page = st.sidebar.radio(
    "WORKSPACE",
    ["Executive Dashboard", "Company Search", "Financial Statements", "Financial Analysis", "Valuation", "Excel Center", "Research Report"],
)
st.sidebar.divider()
st.sidebar.caption("CORPORATE FINANCE · EQUITY RESEARCH")
st.sidebar.caption("Integrated workspace | 2026")

st.markdown("<h1>◈ ORBITE</h1>", unsafe_allow_html=True)
st.caption("CORPORATE FINANCE  |  EQUITY RESEARCH  |  VALUATION  |  FINANCIAL INTELLIGENCE")

company = st.session_state["company"] or "No company selected"
ticker = st.session_state["ticker"] or "—"
currency = st.session_state["currency"] or "USD"

# ----------------------------
# Page 1: Dashboard
# ----------------------------
if page == "Executive Dashboard":
    st.subheader("Executive Dashboard")
    st.caption(f"{company} · {ticker} · {st.session_state['sector'] or 'Sector not specified'}")
    fin = st.session_state["historical_financials"]
    analysis = calculate_analysis(fin)
    if fin.empty or analysis.empty or analysis.dropna(how="all").empty:
        st.info("Commence par rechercher une entreprise dans Company Search, ou importe un classeur Excel dans Excel Center.")
    else:
        latest = analysis.dropna(how="all").iloc[-1]
        cols = st.columns(4)
        for col, label in zip(cols, ["Revenue", "EBITDA", "Net Income", "Free Cash Flow"]):
            col.metric(label, format_number(latest.get(label), currency))
        st.divider()
        left, right = st.columns(2)
        with left:
            chart_cols = [c for c in ["Revenue", "EBITDA", "EBIT", "Net Income"] if c in analysis.columns]
            fig = go.Figure()
            for metric in chart_cols:
                fig.add_trace(go.Scatter(x=analysis.index, y=analysis[metric], mode="lines+markers", name=metric))
            fig.update_layout(template="plotly_dark", paper_bgcolor="#081321", plot_bgcolor="#081321", title="Historical financial performance", height=380)
            st.plotly_chart(fig, width="stretch")
        with right:
            chart_cols = [c for c in ["EBITDA Margin", "Net Profit Margin", "ROE"] if c in analysis.columns]
            fig = go.Figure()
            for metric in chart_cols:
                fig.add_trace(go.Scatter(x=analysis.index, y=analysis[metric] * 100, mode="lines+markers", name=metric))
            fig.update_layout(template="plotly_dark", paper_bgcolor="#081321", plot_bgcolor="#081321", title="Profitability and return ratios (%)", height=380)
            st.plotly_chart(fig, width="stretch")
        st.caption(f"Last refresh: {st.session_state['last_refresh'] or 'Not available'} · Source: Yahoo Finance / user-provided Excel")

# ----------------------------
# Page 2: Company search / auto-fetch
# ----------------------------
elif page == "Company Search":
    st.subheader("Company Search & Automatic Data Retrieval")
    st.write("Recherche par nom d'entreprise ou ticker. Les données disponibles sont récupérées auprès de Yahoo Finance.")
    query = st.text_input("Company name or ticker", value=st.session_state["ticker"] or st.session_state["company"], placeholder="Microsoft, MSFT, LVMH, MC.PA, Airbus, AIR.PA")
    if st.button("SEARCH COMPANIES", type="primary"):
        if not query.strip():
            st.warning("Saisis un nom ou un ticker.")
        else:
            try:
                results = search_companies(query.strip())
                st.session_state["search_results"] = results
                if not results:
                    st.warning("Aucun résultat. Essaie directement le ticker boursier.")
            except Exception as exc:
                st.error(f"Recherche impossible : {exc}")
    results = st.session_state.get("search_results", [])
    if results:
        labels = [f"{r['name']} — {r['symbol']} ({r['exchange']})" for r in results]
        selected_label = st.selectbox("Select the company", labels)
        selected = results[labels.index(selected_label)]
        if st.button("IMPORT COMPANY PROFILE & FINANCIALS", type="primary"):
            with st.spinner(f"Récupération des données de {selected['symbol']}..."):
                try:
                    refresh_company(selected["symbol"])
                    st.success(f"Données importées : {st.session_state['company']} ({st.session_state['ticker']}).")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Import incomplet ou indisponible : {exc}")
    st.divider()
    st.markdown("#### Direct ticker import")
    direct_ticker = st.text_input("Enter ticker directly", key="direct_ticker", placeholder="MSFT, AAPL, MC.PA, TTE.PA")
    if st.button("FETCH DIRECT TICKER"):
        try:
            with st.spinner("Récupération du profil, des états financiers et des cours..."):
                refresh_company(direct_ticker)
            st.success(f"Import terminé pour {st.session_state['company']}.")
            st.rerun()
        except Exception as exc:
            st.error(f"Impossible de récupérer les données : {exc}")
    st.info("Limite importante : la couverture dépend de Yahoo Finance. Les sociétés privées et certains marchés africains peuvent ne pas être couverts. Les champs indisponibles restent vides et ne doivent pas être interprétés comme des zéros.")

# ----------------------------
# Page 3: Statements
# ----------------------------
elif page == "Financial Statements":
    st.subheader("Financial Statements Database")
    st.caption(f"{company} · {ticker} · Reporting currency: {currency}")
    st.write("Les données importées automatiquement peuvent être corrigées ou complétées manuellement.")
    edited = st.data_editor(st.session_state["historical_financials"], num_rows="fixed", hide_index=True, width="stretch", key="statements_editor")
    if st.button("SAVE FINANCIAL STATEMENTS", type="primary"):
        st.session_state["historical_financials"] = edited.copy()
        st.success("États financiers enregistrés dans la session ORBITE.")
        st.rerun()
    if not st.session_state["market_history"].empty:
        with st.expander("Market price history"):
            st.dataframe(st.session_state["market_history"].tail(20), width="stretch")

# ----------------------------
# Page 4: Analysis
# ----------------------------
elif page == "Financial Analysis":
    st.subheader("Financial Performance & Ratio Analysis")
    analysis = calculate_analysis(st.session_state["historical_financials"])
    if analysis.empty:
        st.warning("Aucune donnée disponible. Importe une entreprise ou un fichier Excel.")
    else:
        st.markdown("### Historical financial indicators")
        st.dataframe(analysis, width="stretch")
        st.divider()
        for chart_title, metrics, multiplier in [
            ("Revenue and earnings", ["Revenue", "EBITDA", "EBIT", "Net Income"], 1),
            ("Margins and returns (%)", ["EBITDA Margin", "EBIT Margin", "Net Profit Margin", "ROE", "ROA"], 100),
            ("Cash flow", ["Operating Cash Flow", "CAPEX", "Free Cash Flow"], 1),
            ("Debt and liquidity", ["Net Debt", "Net Debt / EBITDA", "Current Ratio"], 1),
        ]:
            selected_metrics = [m for m in metrics if m in analysis.columns]
            if selected_metrics:
                fig = go.Figure()
                for metric in selected_metrics:
                    fig.add_trace(go.Scatter(x=analysis.index, y=analysis[metric] * multiplier, mode="lines+markers", name=metric))
                fig.update_layout(template="plotly_dark", paper_bgcolor="#081321", plot_bgcolor="#081321", title=chart_title, height=350)
                st.plotly_chart(fig, width="stretch")

# ----------------------------
# Page 5: Valuation
# ----------------------------
elif page == "Valuation":
    st.subheader("Corporate Valuation & DCF Engine")
    analysis = calculate_analysis(st.session_state["historical_financials"])
    if analysis.empty or analysis.dropna(how="all").empty:
        st.warning("Importe d'abord les données financières de l'entreprise.")
    else:
        latest = analysis.dropna(how="all").iloc[-1]
        info = st.session_state.get("company_info", {})
        shares = safe_float(latest.get("Shares Outstanding"), safe_float(info.get("sharesOutstanding"), np.nan))
        share_price = safe_float(latest.get("Share Price"), safe_float(info.get("currentPrice", info.get("regularMarketPrice")), np.nan))
        debt = safe_float(latest.get("Total Debt"), 0.0)
        cash = safe_float(latest.get("Cash & Equivalents"), 0.0)
        ebitda = safe_float(latest.get("EBITDA"))
        net_income = safe_float(latest.get("Net Income"))
        revenue = safe_float(latest.get("Revenue"))
        net_debt = debt - cash
        market_cap = shares * share_price if pd.notna(shares) and pd.notna(share_price) else np.nan
        ev = market_cap + net_debt if pd.notna(market_cap) else np.nan
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Market Capitalization", format_number(market_cap, currency))
        c2.metric("Enterprise Value", format_number(ev, currency))
        c3.metric("EV / EBITDA", f"{ev / ebitda:.2f}x" if pd.notna(ev) and pd.notna(ebitda) and ebitda > 0 else "N/A")
        c4.metric("P/E", f"{market_cap / net_income:.2f}x" if pd.notna(market_cap) and pd.notna(net_income) and net_income > 0 else "N/A")

        st.divider()
        st.markdown("### WACC assumptions")
        a, b, c = st.columns(3)
        rf = a.number_input("Risk-free rate (%)", 0.0, 30.0, 3.0, 0.1) / 100
        beta = b.number_input("Levered beta", 0.0, 5.0, safe_float(info.get("beta"), 1.0), 0.1)
        erp = c.number_input("Equity risk premium (%)", 0.0, 30.0, 5.5, 0.1) / 100
        a, b = st.columns(2)
        cost_debt = a.number_input("Pre-tax cost of debt (%)", 0.0, 30.0, 5.0, 0.1) / 100
        tax = b.number_input("Tax rate (%)", 0.0, 60.0, 25.0, 0.5) / 100
        cost_equity = rf + beta * erp
        capital = (market_cap if pd.notna(market_cap) and market_cap > 0 else 0) + max(debt, 0)
        wacc = ((market_cap / capital) * cost_equity + (max(debt, 0) / capital) * cost_debt * (1 - tax)) if capital > 0 else np.nan
        st.metric("Calculated WACC", f"{wacc:.2%}" if pd.notna(wacc) else "N/A")

        st.divider()
        st.markdown("### DCF assumptions")
        fcf = safe_float(latest.get("Free Cash Flow"))
        a, b, c = st.columns(3)
        fcf_growth = a.number_input("Annual FCF growth (%)", -50.0, 100.0, 5.0, 0.5) / 100
        terminal_growth = b.number_input("Terminal growth (%)", 0.0, 15.0, 2.0, 0.5) / 100
        forecast_years = c.selectbox("Forecast period", [3, 5, 7, 10], index=1)
        st.metric("Latest available Free Cash Flow", format_number(fcf, currency))
        if st.button("CALCULATE DCF", type="primary"):
            if pd.isna(wacc) or wacc <= terminal_growth:
                st.error("WACC doit être supérieur au taux de croissance terminale.")
            elif pd.isna(fcf) or fcf <= 0:
                st.error("Ce DCF simplifié nécessite un Free Cash Flow positif. Un FCF négatif doit être traité avec un modèle adapté.")
            elif pd.isna(shares) or shares <= 0:
                st.error("Le nombre d'actions disponibles est insuffisant pour calculer le prix théorique.")
            else:
                forecast_rows = []
                for year in range(1, forecast_years + 1):
                    projected = fcf * (1 + fcf_growth) ** year
                    discount = 1 / (1 + wacc) ** year
                    forecast_rows.append({"Year": year, "Projected FCF": projected, "Discount Factor": discount, "Present Value": projected * discount})
                forecast = pd.DataFrame(forecast_rows)
                terminal_fcf = fcf * (1 + fcf_growth) ** forecast_years * (1 + terminal_growth)
                terminal_value = terminal_fcf / (wacc - terminal_growth)
                pv_terminal = terminal_value / (1 + wacc) ** forecast_years
                dcf_ev = forecast["Present Value"].sum() + pv_terminal
                dcf_equity = dcf_ev - net_debt
                implied_price = dcf_equity / shares
                st.session_state["dcf_forecast"] = forecast
                st.session_state["dcf_results"] = {"DCF Enterprise Value": dcf_ev, "DCF Equity Value": dcf_equity, "Implied Share Price": implied_price, "WACC": wacc, "Terminal Value": terminal_value, "PV of Terminal Value": pv_terminal}
        results = st.session_state.get("dcf_results")
        if results:
            a, b, c = st.columns(3)
            a.metric("DCF Enterprise Value", format_number(results["DCF Enterprise Value"], currency))
            b.metric("DCF Equity Value", format_number(results["DCF Equity Value"], currency))
            c.metric("Implied Share Price", format_number(results["Implied Share Price"], currency))
            st.dataframe(st.session_state["dcf_forecast"], width="stretch", hide_index=True)
            st.markdown("### Sensitivity analysis — implied share price")
            wacc_values = [max(0.001, results["WACC"] + shift) for shift in [-0.02, -0.01, 0, 0.01, 0.02]]
            growth_values = [max(0, terminal_growth + shift) for shift in [-0.01, -0.005, 0, 0.005, 0.01]]
            matrix = []
            for scenario_wacc in wacc_values:
                row = {"WACC": f"{scenario_wacc:.2%}"}
                for scenario_growth in growth_values:
                    if scenario_wacc <= scenario_growth:
                        row[f"g={scenario_growth:.2%}"] = np.nan
                    else:
                        pv_flows = sum(fcf * (1 + fcf_growth) ** y / (1 + scenario_wacc) ** y for y in range(1, forecast_years + 1))
                        tv = fcf * (1 + fcf_growth) ** forecast_years * (1 + scenario_growth) / (scenario_wacc - scenario_growth)
                        price = (pv_flows + tv / (1 + scenario_wacc) ** forecast_years - net_debt) / shares
                        row[f"g={scenario_growth:.2%}"] = price
                matrix.append(row)
            st.dataframe(pd.DataFrame(matrix).style.format(precision=2, na_rep="N/A"), width="stretch", hide_index=True)
    st.caption("Modèle indicatif : les hypothèses doivent être documentées et les données vérifiées avant toute décision d'investissement. Les conventions comptables et retraitements ne sont pas harmonisés automatiquement.")

# ----------------------------
# Page 6: Excel Center
# ----------------------------
elif page == "Excel Center":
    st.subheader("Excel 365 Automation Center")
    st.write("ORBITE génère un classeur structuré et accepte le retour d'un classeur modifié. Cette version réalise une synchronisation par import/export de fichiers, pas une connexion cloud permanente en arrière-plan.")
    st.markdown("### 1. Export ORBITE → Excel")
    st.write("Le classeur contient le profil, les états financiers, les indicateurs calculés, les ratios et les hypothèses du modèle.")
    excel_bytes = build_excel_workbook()
    st.download_button("DOWNLOAD ORBITE EXCEL WORKBOOK", data=excel_bytes, file_name=f"ORBITE_{st.session_state['ticker'] or 'Financial_Model'}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")
    st.divider()
    st.markdown("### 2. Import Excel → ORBITE")
    uploaded = st.file_uploader("Upload an ORBITE workbook (.xlsx)", type=["xlsx"])
    if uploaded is not None and st.button("IMPORT AND UPDATE ORBITE", type="primary"):
        try:
            import_excel_workbook(uploaded)
            st.success("Classeur importé. Les états financiers et le profil ont été actualisés dans ORBITE.")
            st.rerun()
        except Exception as exc:
            st.error(f"Import Excel impossible : {exc}")
    st.info("Pour une automatisation Excel 365 plus poussée (actualisation en un clic, Power Query et Office Scripts), nous ajouterons ensuite un modèle .xlsx dédié et des scripts Office. La synchronisation actuelle est contrôlée par l'utilisateur via import/export.")

# ----------------------------
# Page 7: Research Report
# ----------------------------
elif page == "Research Report":
    st.subheader("Equity Research — Company Snapshot")
    st.markdown(f"### {company}")
    st.caption(f"{ticker} · {st.session_state['sector']} · {st.session_state['country']} · {currency}")
    analysis = calculate_analysis(st.session_state["historical_financials"])
    if analysis.empty or analysis.dropna(how="all").empty:
        st.warning("Aucune donnée financière disponible pour produire le rapport.")
    else:
        latest = analysis.dropna(how="all").iloc[-1]
        report_rows = []
        for metric in ["Revenue", "EBITDA", "EBIT", "Net Income", "Free Cash Flow", "Net Debt", "EBITDA Margin", "Net Profit Margin", "Net Debt / EBITDA", "ROE", "ROA", "Current Ratio"]:
            if metric in latest.index:
                report_rows.append({"Financial Indicator": metric, "Latest Value": latest[metric]})
        report = pd.DataFrame(report_rows)
        st.dataframe(report, width="stretch", hide_index=True)
        st.markdown("### Company profile")
        info = st.session_state.get("company_info", {})
        profile_cols = st.columns(3)
        profile_cols[0].metric("Market", info.get("exchange", "N/A"))
        profile_cols[1].metric("Industry", info.get("industry", "N/A"))
        profile_cols[2].metric("Employees", f"{info.get('fullTimeEmployees'):,}" if info.get("fullTimeEmployees") else "N/A")
        csv_bytes = report.to_csv(index=False).encode("utf-8")
        st.download_button("DOWNLOAD RESEARCH SNAPSHOT (CSV)", data=csv_bytes, file_name=f"ORBITE_Research_{ticker or 'Company'}.csv", mime="text/csv")

st.divider()
st.caption("ORBITE | MERIDIAN RISK ADVISORY | Financial Intelligence & Decision Support")
