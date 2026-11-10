import io, json, sqlite3
from datetime import datetime
from pathlib import Path
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

APP_DIR = Path(__file__).parent
DB_PATH = APP_DIR / 'orbite.db'
ITEMS = ['Revenue','EBITDA','EBIT','Net Income','Cash & Equivalents','Total Debt',"Shareholders' Equity",'Total Assets','Current Assets','Current Liabilities','Operating Cash Flow','CAPEX','Shares Outstanding','Share Price']
NAV = ['Executive Dashboard','Company Search','Financial Statements','Financial Analysis','Valuation','Peer Comparison','Excel Center','Research Report','Data & Methodology']

st.set_page_config(page_title='ORBITE | Meridian Risk Advisory', page_icon='◈', layout='wide')
st.markdown('''<style>
.stApp{background:#081321;color:#e8edf5}.stApp p,.stApp label{color:#d6dfeb}
[data-testid="stSidebar"]{background:#101e30} h1,h2,h3{color:#f4f7fb}
[data-testid="stMetric"]{background:#13243a;border:1px solid #263b55;padding:13px;border-radius:9px}
.stButton>button,.stDownloadButton>button{background:#176b87;color:white;border:0;border-radius:7px;font-weight:600}
[data-testid="stDataFrame"]{border:1px solid #263b55;border-radius:8px}
</style>''', unsafe_allow_html=True)

# ---------- Persistence ----------
def db():
    con=sqlite3.connect(DB_PATH)
    con.execute('''CREATE TABLE IF NOT EXISTS companies(ticker TEXT PRIMARY KEY,name TEXT,sector TEXT,country TEXT,currency TEXT,updated_at TEXT,info_json TEXT)''')
    con.execute('''CREATE TABLE IF NOT EXISTS statements(ticker TEXT,year TEXT,item TEXT,value REAL,PRIMARY KEY(ticker,year,item))''')
    con.execute('''CREATE TABLE IF NOT EXISTS valuations(id INTEGER PRIMARY KEY AUTOINCREMENT,ticker TEXT,created_at TEXT,inputs_json TEXT,results_json TEXT)''')
    return con

def save_company(ticker, profile, fin):
    con=db(); con.execute('INSERT OR REPLACE INTO companies VALUES(?,?,?,?,?,?,?)',(ticker,profile.get('name',ticker),profile.get('sector',''),profile.get('country',''),profile.get('currency','USD'),datetime.now().isoformat(timespec='seconds'),json.dumps(profile,default=str)))
    con.execute('DELETE FROM statements WHERE ticker=?',(ticker,))
    for _,r in fin.iterrows():
        item=str(r['Financial Item'])
        for year in fin.columns:
            if year=='Financial Item': continue
            try: val=float(r[year]); val=None if not np.isfinite(val) else val
            except: val=None
            con.execute('INSERT OR REPLACE INTO statements VALUES(?,?,?,?)',(ticker,str(year),item,val))
    con.commit(); con.close()

def load_company(ticker):
    con=db(); c=con.execute('SELECT name,sector,country,currency,info_json FROM companies WHERE ticker=?',(ticker,)).fetchone()
    rows=con.execute('SELECT year,item,value FROM statements WHERE ticker=?',(ticker,)).fetchall(); con.close()
    if not c: return None
    profile=json.loads(c[4] or '{}')
    years=sorted({x[0] for x in rows})
    lookup={(y,i):v for y,i,v in rows}
    fin=pd.DataFrame([{'Financial Item':item,**{y:lookup.get((y,item),np.nan) for y in years}} for item in ITEMS])
    return profile,fin

def safe(v, default=np.nan):
    try:
        if v is None or pd.isna(v): return default
        return float(v)
    except: return default

def fmt(v,cur=''):
    return 'N/A' if pd.isna(safe(v)) else f'{safe(v):,.2f} {cur}'.strip()

def first_row(df, candidates):
    if df is None or df.empty:return None
    idx={str(x).lower():x for x in df.index}
    for c in candidates:
        if c.lower() in idx:return idx[c.lower()]
    for c in candidates:
        for k,v in idx.items():
            if c.lower() in k:return v
    return None

def val(df,candidates,date):
    r=first_row(df,candidates)
    if r is None or date not in df.columns:return np.nan
    return safe(df.loc[r,date])

def search_companies(query, max_results=12):
    """Search public companies by name or ticker through Yahoo Finance Search."""
    query = str(query or '').strip()
    if len(query) < 2:
        raise ValueError('Saisis au moins deux caractères pour lancer la recherche.')
    result = yf.Search(query, max_results=max_results, news_count=0)
    quotes = getattr(result, 'quotes', None) or []
    companies = []
    seen = set()
    for item in quotes:
        symbol = item.get('symbol')
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        companies.append({
            'Ticker': symbol,
            'Entreprise': item.get('longname') or item.get('shortname') or item.get('name') or symbol,
            'Marché': item.get('exchange') or item.get('exchDisp') or '',
            'Type': item.get('quoteType') or '',
            'Secteur': item.get('sector') or ''
        })
    return companies

def fetch_ticker(symbol):
    obj=yf.Ticker(symbol); info=obj.get_info() or {}
    income=obj.financials; balance=obj.balance_sheet; cash=obj.cashflow
    dates=sorted(set(pd.Timestamp(x) for frame in [income,balance,cash] if frame is not None and not frame.empty for x in frame.columns),reverse=True)[:10]
    dates=sorted(dates)
    if not dates: raise ValueError('Aucun état financier annuel exploitable retourné par Yahoo Finance.')
    data={item:[] for item in ITEMS}
    for d in dates:
        rev=val(income,['Total Revenue','Operating Revenue','Revenue'],d)
        ebit=val(income,['Operating Income','EBIT'],d)
        dep=val(cash,['Depreciation And Amortization','Depreciation Amortization Depletion'],d)
        ebitda=val(income,['EBITDA','Normalized EBITDA'],d)
        if pd.isna(ebitda) and pd.notna(ebit) and pd.notna(dep):ebitda=ebit+abs(dep)
        debt=val(balance,['Total Debt'],d)
        if pd.isna(debt):
            pieces=[val(balance,['Current Debt','Current Debt And Capital Lease Obligation'],d),val(balance,['Long Term Debt','Long Term Debt And Capital Lease Obligation'],d)]
            pieces=[x for x in pieces if pd.notna(x)]; debt=sum(pieces) if pieces else np.nan
        price=safe(info.get('currentPrice',info.get('regularMarketPrice')))
        if pd.isna(price):
            h=obj.history(period='5d'); price=safe(h['Close'].dropna().iloc[-1]) if not h.empty else np.nan
        vals={
          'Revenue':rev,'EBITDA':ebitda,'EBIT':ebit,'Net Income':val(income,['Net Income','Net Income Common Stockholders','Net Income From Continuing Operations'],d),
          'Cash & Equivalents':val(balance,['Cash And Cash Equivalents','Cash Cash Equivalents And Short Term Investments','Cash'],d),
          'Total Debt':debt,"Shareholders' Equity":val(balance,['Stockholders Equity','Common Stock Equity','Total Equity Gross Minority Interest'],d),
          'Total Assets':val(balance,['Total Assets'],d),'Current Assets':val(balance,['Current Assets'],d),'Current Liabilities':val(balance,['Current Liabilities'],d),
          'Operating Cash Flow':val(cash,['Operating Cash Flow','Cash Flow From Continuing Operating Activities','Total Cash From Operating Activities'],d),
          'CAPEX':abs(val(cash,['Capital Expenditure','Capital Expenditures'],d)),'Shares Outstanding':safe(info.get('sharesOutstanding')) if d==max(dates) else np.nan,
          'Share Price':price if d==max(dates) else np.nan}
        for k in ITEMS:data[k].append(vals[k])
    fin=pd.DataFrame(data,index=[str(d.year) for d in dates]).T.reset_index().rename(columns={'index':'Financial Item'})
    profile={'name':info.get('longName') or info.get('shortName') or symbol,'sector':info.get('sector') or info.get('industry') or 'Unspecified','country':info.get('country',''),'currency':info.get('currency','USD'),'exchange':info.get('exchange',''),'industry':info.get('industry',''),'employees':info.get('fullTimeEmployees'),'website':info.get('website',''),'beta':info.get('beta'),'market_cap':info.get('marketCap'),'source':'Yahoo Finance / yfinance'}
    history=obj.history(period='5y',auto_adjust=False)
    return profile,fin,history

def analysis(fin):
    if fin is None or fin.empty:return pd.DataFrame()
    f=fin.set_index('Financial Item').T.copy(); f.index=f.index.astype(str)
    for c in f:f[c]=pd.to_numeric(f[c],errors='coerce')
    f=f.sort_index()
    if 'Revenue' in f:f['Revenue Growth']=f.Revenue.pct_change()
    for name,num,den in [('EBITDA Margin','EBITDA','Revenue'),('EBIT Margin','EBIT','Revenue'),('Net Profit Margin','Net Income','Revenue'),('ROE','Net Income',"Shareholders' Equity"),('ROA','Net Income','Total Assets'),('Current Ratio','Current Assets','Current Liabilities')]:
        if num in f and den in f:f[name]=f[num]/f[den].replace(0,np.nan)
    if 'Operating Cash Flow' in f and 'CAPEX' in f:f['Free Cash Flow']=f['Operating Cash Flow']-f['CAPEX']
    if 'Total Debt' in f and 'Cash & Equivalents' in f:f['Net Debt']=f['Total Debt']-f['Cash & Equivalents']
    if 'Net Debt' in f and 'EBITDA' in f:f['Net Debt / EBITDA']=f['Net Debt']/f['EBITDA'].replace(0,np.nan)
    return f

def workbook_bytes(ticker,profile,fin,assumptions=None):
    a=analysis(fin); out=io.BytesIO()
    with pd.ExcelWriter(out,engine='openpyxl') as w:
        pd.DataFrame({'Field':['Company','Ticker','Sector','Country','Currency','Source','Generated'], 'Value':[profile.get('name',ticker),ticker,profile.get('sector',''),profile.get('country',''),profile.get('currency','USD'),profile.get('source','User / Yahoo Finance'),datetime.now().isoformat(timespec='minutes')]}).to_excel(w,sheet_name='Company Profile',index=False)
        fin.to_excel(w,sheet_name='Financial Statements',index=False)
        a.to_excel(w,sheet_name='Financial Analysis')
        ratios=[c for c in a.columns if c not in ITEMS]
        a[ratios].to_excel(w,sheet_name='Key Ratios')
        pd.DataFrame({'Assumption':['Risk-free rate','Beta','Equity risk premium','Cost of debt','Tax rate','FCF growth','Terminal growth','Forecast years'],'Value':[.03,1,.055,.05,.25,.05,.02,5]}).to_excel(w,sheet_name='Model Assumptions',index=False)
        ws=w.book.create_sheet('Excel Model'); ws.append(['ORBITE | FINANCIAL MODEL']); ws.append(['Metric','Value','Method'])
        # Statement sheet: row 2 is Revenue, row 3 EBITDA, row 7 cash, row 8 debt.
        last_col=get_column_letter(1+len([c for c in fin.columns if c!='Financial Item']))
        ws.append(['Latest Revenue',f'=IFERROR(LOOKUP(2,1/(\'Financial Statements\'!B2:{last_col}2<>""),\'Financial Statements\'!B2:{last_col}2),0)','Last populated annual period'])
        ws.append(['Latest EBITDA',f'=IFERROR(LOOKUP(2,1/(\'Financial Statements\'!B3:{last_col}3<>""),\'Financial Statements\'!B3:{last_col}3),0)','Last populated annual period'])
        ws.append(['EBITDA Margin','=IFERROR(B4/B3,0)','EBITDA / Revenue'])
        ws.append(['Net Debt',f'=IFERROR(LOOKUP(2,1/(\'Financial Statements\'!B7:{last_col}7<>""),\'Financial Statements\'!B7:{last_col}7)-LOOKUP(2,1/(\'Financial Statements\'!B6:{last_col}6<>""),\'Financial Statements\'!B6:{last_col}6),0)','Total debt less cash'])
        for sheet in w.book.worksheets:
            sheet.freeze_panes='B2'; sheet.sheet_view.showGridLines=False
            for cell in sheet[1]:cell.font=Font(bold=True,color='FFFFFF');cell.fill=PatternFill('solid',fgColor='10243A')
            for col in sheet.columns:
                letter=get_column_letter(col[0].column); width=min(max(max(len(str(c.value or '')) for c in col)+2,12),40);sheet.column_dimensions[letter].width=width
    out.seek(0);return out.getvalue()

# ---------- State ----------
if 'ticker' not in st.session_state:st.session_state.ticker=''
if 'profile' not in st.session_state:st.session_state.profile={}
if 'fin' not in st.session_state:st.session_state.fin=pd.DataFrame({'Financial Item':ITEMS})
if 'market' not in st.session_state:st.session_state.market=pd.DataFrame()
if 'dcf' not in st.session_state:st.session_state.dcf=None

st.sidebar.markdown('# ◈ ORBITE');st.sidebar.caption('MERIDIAN RISK ADVISORY');st.sidebar.divider()
page=st.sidebar.radio('WORKSPACE',NAV)
st.sidebar.divider();st.sidebar.caption('CORPORATE FINANCE · EQUITY RESEARCH · VALUATION')
st.markdown('# ◈ ORBITE');st.caption('CORPORATE FINANCE  |  EQUITY RESEARCH  |  VALUATION  |  FINANCIAL INTELLIGENCE')
ticker=st.session_state.ticker;profile=st.session_state.profile;fin=st.session_state.fin;cur=profile.get('currency','USD')

if page=='Executive Dashboard':
    st.subheader('Executive Dashboard');st.caption(f"{profile.get('name','No company selected')} · {ticker or '—'} · {profile.get('sector','')}")
    a=analysis(fin)
    if a.empty or a.dropna(how='all').empty:st.info('Importe une société dans Company Search ou charge un classeur dans Excel Center.')
    else:
        latest=a.dropna(how='all').iloc[-1];cols=st.columns(4)
        for c,k in zip(cols,['Revenue','EBITDA','Net Income','Free Cash Flow']):c.metric(k,fmt(latest.get(k),cur))
        left,right=st.columns(2)
        with left:
            fig=go.Figure()
            for k in ['Revenue','EBITDA','EBIT','Net Income']:
                if k in a:fig.add_trace(go.Scatter(x=a.index,y=a[k],mode='lines+markers',name=k))
            fig.update_layout(template='plotly_dark',paper_bgcolor='#081321',plot_bgcolor='#081321',title='Historical performance');st.plotly_chart(fig,width='stretch')
        with right:
            fig=go.Figure()
            for k in ['EBITDA Margin','Net Profit Margin','ROE']:
                if k in a:fig.add_trace(go.Scatter(x=a.index,y=a[k]*100,mode='lines+markers',name=k))
            fig.update_layout(template='plotly_dark',paper_bgcolor='#081321',plot_bgcolor='#081321',title='Margins & returns (%)');st.plotly_chart(fig,width='stretch')
        st.caption('Source and refresh date must be verified before external use.')

elif page=='Company Search':
    st.subheader('Company Search & Data Import')
    st.caption('Recherche une entreprise par son nom, son ticker ou un symbole boursier.')
    q=st.text_input('Nom de l’entreprise ou ticker',value=ticker,placeholder='Microsoft, Apple, TotalEnergies, MSFT, TTE.PA')
    search_col, direct_col = st.columns([2,1])
    if search_col.button('SEARCH COMPANY',type='primary',width='stretch'):
        try:
            with st.spinner('Recherche des entreprises dans Yahoo Finance...'):
                st.session_state.company_search_results=search_companies(q)
                st.session_state.company_search_query=q
            if not st.session_state.company_search_results:
                st.warning('Aucune entreprise trouvée. Essaie un ticker ou une autre orthographe.')
        except Exception as e:
            st.error(f'La recherche a échoué : {e}')
    if 'company_search_results' in st.session_state and st.session_state.company_search_results:
        results=st.session_state.company_search_results
        st.markdown('#### Résultats de recherche')
        st.dataframe(pd.DataFrame(results),hide_index=True,width='stretch')
        labels=[f"{r['Entreprise']} — {r['Ticker']} ({r['Marché'] or 'Marché non précisé'})" for r in results]
        selected=st.selectbox('Sélectionne l’entreprise à importer',labels,key='company_search_selection')
        selected_row=results[labels.index(selected)]
        st.info(f"Entreprise sélectionnée : **{selected_row['Entreprise']}** · Ticker : **{selected_row['Ticker']}**")
        if st.button('IMPORT SELECTED COMPANY',type='primary'):
            try:
                with st.spinner(f"Récupération des états financiers de {selected_row['Entreprise']}..."):
                    sym=selected_row['Ticker']
                    p,f,h=fetch_ticker(sym)
                    st.session_state.ticker=sym
                    st.session_state.profile=p
                    st.session_state.fin=f
                    st.session_state.market=h
                    save_company(sym,p,f)
                st.success('Entreprise importée et sauvegardée dans la base ORBITE.')
                st.rerun()
            except Exception as e:
                st.error(f"Import impossible pour {selected_row['Ticker']} : {e}")
    with st.expander('Import direct si tu connais déjà le ticker'):
        direct=st.text_input('Ticker boursier',placeholder='MSFT ou MC.PA',key='direct_ticker')
        if st.button('IMPORT TICKER DIRECT'):
            try:
                with st.spinner('Récupération des données financières...'):
                    sym=direct.strip().upper()
                    if not sym: raise ValueError('Saisis un ticker.')
                    p,f,h=fetch_ticker(sym)
                    st.session_state.ticker=sym;st.session_state.profile=p;st.session_state.fin=f;st.session_state.market=h;save_company(sym,p,f)
                st.success('Entreprise importée et sauvegardée localement.');st.rerun()
            except Exception as e:st.error(f'Import impossible : {e}')
    saved=[]
    try:
        con=db();saved=con.execute('SELECT ticker,name FROM companies ORDER BY updated_at DESC').fetchall();con.close()
    except Exception as e:st.warning(str(e))
    if saved:
        st.markdown('#### Entreprises sauvegardées')
        choice=st.selectbox('Charger depuis la base de données locale',[f'{x[0]} — {x[1]}' for x in saved])
        if st.button('LOAD SAVED COMPANY'):
            sym=choice.split(' — ')[0];loaded=load_company(sym)
            if loaded:st.session_state.ticker=sym;st.session_state.profile=loaded[0];st.session_state.fin=loaded[1];st.rerun()
    st.info('La recherche et la couverture dépendent de Yahoo Finance. Les sociétés privées et plusieurs marchés africains peuvent être absents. Vérifie les dates, devises et définitions comptables avant toute utilisation professionnelle.')

elif page=='Financial Statements':
    st.subheader('Financial Statements');st.caption(f'{profile.get("name","Manual company")} · {ticker or "No ticker"} · {cur}')
    years=[str(y) for y in range(datetime.now().year-9,datetime.now().year+1)]
    if fin.empty or len(fin.columns)==1:st.session_state.fin=pd.DataFrame({'Financial Item':ITEMS,**{y:[np.nan]*len(ITEMS) for y in years}})
    edited=st.data_editor(st.session_state.fin,num_rows='fixed',hide_index=True,width='stretch',key='fin_editor')
    if st.button('SAVE STATEMENTS',type='primary'):
        st.session_state.fin=edited.copy()
        if ticker:save_company(ticker,profile,edited)
        st.success('États financiers sauvegardés localement.');st.rerun()
    if not st.session_state.market.empty:
        with st.expander('Market price history'):st.dataframe(st.session_state.market.tail(30),width='stretch')

elif page=='Financial Analysis':
    st.subheader('Financial Performance & Ratios');a=analysis(fin)
    if a.empty:st.warning('Aucune donnée disponible.')
    else:
        st.dataframe(a,width='stretch');st.divider()
        for title,metrics,mult in [('Revenue & earnings',['Revenue','EBITDA','EBIT','Net Income'],1),('Margins & returns',['EBITDA Margin','EBIT Margin','Net Profit Margin','ROE','ROA'],100),('Cash flow',['Operating Cash Flow','CAPEX','Free Cash Flow'],1),('Leverage & liquidity',['Net Debt','Net Debt / EBITDA','Current Ratio'],1)]:
            chosen=[m for m in metrics if m in a]
            if chosen:
                fig=go.Figure()
                for m in chosen:fig.add_trace(go.Scatter(x=a.index,y=a[m]*mult,mode='lines+markers',name=m))
                fig.update_layout(template='plotly_dark',paper_bgcolor='#081321',plot_bgcolor='#081321',title=title);st.plotly_chart(fig,width='stretch')

elif page=='Valuation':
    st.subheader('DCF Valuation & Market Multiples');a=analysis(fin)
    if a.empty or a.dropna(how='all').empty:st.warning('Importe ou saisis des données financières.')
    else:
        latest=a.dropna(how='all').iloc[-1];info=profile
        shares=safe(latest.get('Shares Outstanding'));price=safe(latest.get('Share Price'));debt=safe(latest.get('Total Debt'),0);cash=safe(latest.get('Cash & Equivalents'),0);ebitda=safe(latest.get('EBITDA'));ni=safe(latest.get('Net Income'));fcf=safe(latest.get('Free Cash Flow'));nd=debt-cash
        mc=shares*price if pd.notna(shares) and pd.notna(price) else safe(info.get('market_cap'));ev=mc+nd if pd.notna(mc) else np.nan
        m=st.columns(4);m[0].metric('Market Cap',fmt(mc,cur));m[1].metric('Enterprise Value',fmt(ev,cur));m[2].metric('EV / EBITDA',f'{ev/ebitda:.2f}x' if pd.notna(ev) and pd.notna(ebitda) and ebitda>0 else 'N/A');m[3].metric('P/E',f'{mc/ni:.2f}x' if pd.notna(mc) and pd.notna(ni) and ni>0 else 'N/A')
        st.markdown('#### WACC assumptions');x,y,z=st.columns(3);rf=x.number_input('Risk-free rate (%)',0.,30.,3.)/100;beta=y.number_input('Beta',0.,5.,safe(info.get('beta'),1.));erp=z.number_input('Equity risk premium (%)',0.,30.,5.5)/100
        x,y=st.columns(2);kd=x.number_input('Pre-tax cost of debt (%)',0.,30.,5.)/100;tax=y.number_input('Tax rate (%)',0.,60.,25.)/100;ke=rf+beta*erp
        capital=(mc if pd.notna(mc) and mc>0 else 0)+max(debt,0);wacc=((mc/capital)*ke+(max(debt,0)/capital)*kd*(1-tax)) if capital>0 and pd.notna(mc) else np.nan
        st.metric('WACC',f'{wacc:.2%}' if pd.notna(wacc) else 'N/A — enter market capitalization')
        st.markdown('#### DCF assumptions');x,y,z=st.columns(3);growth=x.number_input('Annual FCF growth (%)',-50.,100.,5.)/100;tg=y.number_input('Terminal growth (%)',0.,15.,2.)/100;n=z.selectbox('Forecast years',[3,5,7,10],index=1)
        st.metric('Latest FCF',fmt(fcf,cur))
        if st.button('RUN DCF',type='primary'):
            if pd.isna(wacc) or wacc<=tg:st.error('WACC must be greater than terminal growth. Check market cap and assumptions.')
            elif pd.isna(fcf) or fcf<=0:st.error('This simplified DCF requires positive FCF. Use a tailored model for negative FCF.')
            elif pd.isna(shares) or shares<=0:st.error('Shares outstanding are missing. Enter them in Financial Statements.')
            else:
                rows=[{'Year':i,'FCF':fcf*(1+growth)**i,'Discount Factor':1/(1+wacc)**i,'PV':fcf*(1+growth)**i/(1+wacc)**i} for i in range(1,n+1)]
                tv=fcf*(1+growth)**n*(1+tg)/(wacc-tg);pv=sum(r['PV'] for r in rows)+tv/(1+wacc)**n;equity=pv-nd;intrinsic=equity/shares
                st.session_state.dcf={'EV':pv,'Equity Value':equity,'Implied Share Price':intrinsic,'WACC':wacc,'Terminal Value':tv,'forecast':rows,'growth':growth,'terminal_growth':tg,'years':n,'fcf':fcf,'net_debt':nd,'shares':shares}
                con=db();con.execute('INSERT INTO valuations(ticker,created_at,inputs_json,results_json) VALUES(?,?,?,?)',(ticker,datetime.now().isoformat(),json.dumps({'wacc':wacc,'growth':growth,'terminal_growth':tg,'years':n}),json.dumps({k:v for k,v in st.session_state.dcf.items() if k!='forecast'})));con.commit();con.close()
        r=st.session_state.dcf
        if r:
            cols=st.columns(3);cols[0].metric('DCF Enterprise Value',fmt(r['EV'],cur));cols[1].metric('Equity Value',fmt(r['Equity Value'],cur));cols[2].metric('Implied Share Price',fmt(r['Implied Share Price'],cur))
            st.dataframe(pd.DataFrame(r['forecast']),hide_index=True,width='stretch')
            st.markdown('#### Sensitivity — implied share price');matrix=[]
            for sw in [r['WACC']+v for v in [-.02,-.01,0,.01,.02]]:
                row={'WACC':f'{sw:.2%}'}
                for sg in [max(0,r['terminal_growth']+v) for v in [-.01,-.005,0,.005,.01]]:
                    pv=sum(r['fcf']*(1+r['growth'])**i/(1+sw)**i for i in range(1,r['years']+1));tv=r['fcf']*(1+r['growth'])**r['years']*(1+sg)/(sw-sg) if sw>sg else np.nan
                    row[f'g={sg:.2%}']=(pv+tv/(1+sw)**r['years']-r['net_debt'])/r['shares'] if pd.notna(tv) else np.nan
                matrix.append(row)
            st.dataframe(pd.DataFrame(matrix).style.format(precision=2,na_rep='N/A'),hide_index=True,width='stretch')
        st.caption('Illustrative valuation only. Verify inputs, accounting definitions, capital structure and market data before investment decisions.')

elif page=='Peer Comparison':
    st.subheader('Peer Comparison');st.write('Ajoute les tickers de sociétés cotées comparables, séparés par des virgules.')
    peers=st.text_input('Peer tickers',placeholder='MSFT, ORCL, SAP')
    if st.button('FETCH PEERS'):
        rows=[]
        for sym in [x.strip().upper() for x in peers.split(',') if x.strip()]:
            try:
                p,f,h=fetch_ticker(sym);a=analysis(f);last=a.dropna(how='all').iloc[-1];shares=safe(last.get('Shares Outstanding'));price=safe(last.get('Share Price'));mc=shares*price if pd.notna(shares) and pd.notna(price) else safe(p.get('market_cap'));debt=safe(last.get('Total Debt'),0);cash=safe(last.get('Cash & Equivalents'),0);ebitda=safe(last.get('EBITDA'));ni=safe(last.get('Net Income'));ev=mc+debt-cash if pd.notna(mc) else np.nan
                rows.append({'Ticker':sym,'Company':p.get('name'),'Sector':p.get('sector'),'Market Cap':mc,'EV':ev,'Revenue':safe(last.get('Revenue')),'EBITDA':ebitda,'EV/EBITDA':ev/ebitda if pd.notna(ev) and pd.notna(ebitda) and ebitda>0 else np.nan,'P/E':mc/ni if pd.notna(mc) and pd.notna(ni) and ni>0 else np.nan})
            except Exception as e:rows.append({'Ticker':sym,'Error':str(e)})
        st.session_state.peer_rows=rows
    if st.session_state.get('peer_rows'):st.dataframe(pd.DataFrame(st.session_state.peer_rows),hide_index=True,width='stretch')
    st.caption('Comparables are indicative; normalize fiscal periods, accounting standards, currencies and non-recurring items before drawing conclusions.')

elif page=='Excel Center':
    st.subheader('Excel 365 Automation Center');st.write('Export du modèle ORBITE vers Excel et réimport des états financiers corrigés.')
    if st.session_state.ticker or not st.session_state.fin.empty:
        xlsx=workbook_bytes(ticker or 'MANUAL',profile,fin)
        st.download_button('DOWNLOAD ORBITE FINANCIAL MODEL (.XLSX)',xlsx,file_name=f'ORBITE_{ticker or "Financial_Model"}.xlsx',mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',type='primary')
    uploaded=st.file_uploader('Import ORBITE workbook',type=['xlsx'])
    if uploaded and st.button('IMPORT EXCEL INTO ORBITE'):
        try:
            book=pd.ExcelFile(uploaded);sheet='Financial Statements' if 'Financial Statements' in book.sheet_names else book.sheet_names[0];new=pd.read_excel(book,sheet_name=sheet)
            if 'Financial Item' not in new or not set(ITEMS).issubset(set(new['Financial Item'].astype(str))):raise ValueError('La feuille doit contenir toutes les lignes financières ORBITE.')
            st.session_state.fin=new
            if 'Company Profile' in book.sheet_names:
                p=pd.read_excel(book,sheet_name='Company Profile');d=dict(zip(p['Field'].astype(str),p['Value'])) if {'Field','Value'}.issubset(p.columns) else {}
                st.session_state.profile={**profile,'name':d.get('Company',profile.get('name','')),'sector':d.get('Sector',profile.get('sector','')),'country':d.get('Country',profile.get('country','')),'currency':d.get('Currency',profile.get('currency','USD'))}
            if ticker:save_company(ticker,st.session_state.profile,new)
            st.success('Classeur importé et données mises à jour.');st.rerun()
        except Exception as e:st.error(f'Import impossible: {e}')
    st.info('La synchronisation est actuellement par import/export de fichiers. Pour une synchronisation cloud automatisée, il faudra ensuite configurer OneDrive/SharePoint, Power Query ou Office Scripts.')

elif page=='Research Report':
    st.subheader('Equity Research — Company Snapshot');a=analysis(fin)
    if a.empty or a.dropna(how='all').empty:st.warning('Aucune donnée disponible.')
    else:
        latest=a.dropna(how='all').iloc[-1];st.markdown(f"### {profile.get('name',ticker)}");st.caption(f"{ticker} · {profile.get('sector','')} · {profile.get('country','')} · {cur}")
        metrics=['Revenue','EBITDA','EBIT','Net Income','Free Cash Flow','Net Debt','EBITDA Margin','Net Profit Margin','Net Debt / EBITDA','ROE','ROA','Current Ratio']
        report=pd.DataFrame([{'Indicator':k,'Latest Value':latest.get(k,np.nan)} for k in metrics if k in latest.index]);st.dataframe(report,hide_index=True,width='stretch')
        st.download_button('DOWNLOAD RESEARCH SNAPSHOT CSV',report.to_csv(index=False).encode('utf-8-sig'),file_name=f'ORBITE_Research_{ticker or "Company"}.csv',mime='text/csv')
        st.download_button('DOWNLOAD RESEARCH SNAPSHOT EXCEL',workbook_bytes(ticker or 'MANUAL',profile,fin),file_name=f'ORBITE_Research_{ticker or "Company"}.xlsx',mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

elif page=='Data & Methodology':
    st.subheader('Data Governance & Methodology')
    st.markdown('''**Sources**  
- Yahoo Finance through `yfinance` for public-company profile, annual statements and market history.  
- User-provided Excel data for manual inputs and adjustments.  
- Local SQLite database for persistence on this computer.

**Methodology**  
- Revenue growth = current-period revenue / prior-period revenue − 1.  
- EBITDA margin = EBITDA / Revenue.  
- Free cash flow (simplified) = Operating Cash Flow − CAPEX.  
- Net debt = Total Debt − Cash & Equivalents.  
- ROE = Net Income / Shareholders' Equity; ROA = Net Income / Total Assets.  
- WACC = weighted cost of equity and after-tax cost of debt.  
- DCF = discounted explicit FCF forecast + discounted Gordon Growth terminal value.

**Controls and limitations**  
- Yahoo data may be missing, delayed, restated or inconsistently classified.  
- IFRS, US GAAP, PCG and SYSCOHADA are not automatically harmonized.  
- CAPEX sign and debt definitions must be checked.  
- Private companies and several African exchanges may not be covered.  
- ORBITE is a decision-support and portfolio tool, not an audited data provider, regulated rating agency or investment recommendation.''')

st.divider();st.caption('ORBITE | MERIDIAN RISK ADVISORY | Financial Intelligence & Decision Support')
