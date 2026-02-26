import json
from datetime import datetime, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components
from streamlit_local_storage import LocalStorage
import FinanceDataReader as fdr

# =========================
# Helper
# =========================
def krw(x):
    if x is None:
        return "—"
    try:
        return f"{int(round(float(x), 0)):,}원"
    except:
        return "—"

def safe_ma(series, window):
    if len(series) < window:
        return None
    return float(series.rolling(window).mean().iloc[-1])

def calc_atr(df, period=14):
    if not {"High","Low","Close"}.issubset(df.columns):
        return None
    high = df["High"]
    low = df["Low"]
    close = df["Close"]
    prev_close = close.shift(1)

    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)

    atr = tr.rolling(period).mean()
    return float(atr.iloc[-1]) if not atr.dropna().empty else None

def decision_engine(lv, lookback, buy_drop_threshold, trend_ma_period, df2):
    P, H = lv["P"], lv["H"]

    close = df2["Close"]
    trend_ma = None
    if len(close) >= trend_ma_period:
        trend_ma = float(close.rolling(trend_ma_period).mean().iloc[-1])

    drop = (P / H) - 1.0 if H else 0

    verdict = "🟡 관망"
    guide = "추격보다 눌림 대기"
    tone = "warning"

    if trend_ma and P < trend_ma:
        verdict = "🔴 비중 축소 고려"
        guide = "추세선 이탈"
        tone = "error"
    elif drop <= -(buy_drop_threshold / 100):
        verdict = "🟢 분할 매수 고려"
        guide = "고점 대비 조정 구간"
        tone = "success"
    elif drop >= -0.03:
        verdict = "🟡 고점권 주의"
        guide = "추격 매수 위험"
        tone = "warning"

    return verdict, guide, tone, trend_ma

def copy_button(text):
    safe = json.dumps(text)
    html = f"""
    <button id="copyBtn" style="
        width:100%;
        height:45px;
        background:#111827;
        color:white;
        border-radius:10px;
        border:none;
        font-weight:bold;
        cursor:pointer;">
        📋 한 번에 복사
    </button>
    <script>
    const btn = document.getElementById("copyBtn");
    btn.onclick = async () => {{
        try {{
            await navigator.clipboard.writeText({safe});
            btn.innerText="✅ 복사됨!";
            setTimeout(()=>btn.innerText="📋 한 번에 복사",1200);
        }} catch {{
            btn.innerText="⚠️ 복사 실패";
        }}
    }};
    </script>
    """
    components.html(html, height=60)

# =========================
# 즐겨찾기 저장 (브라우저)
# =========================
LOCAL_KEY = "fav_codes_v2"
localS = LocalStorage()

def load_favs():
    try:
        raw = localS.getItem(LOCAL_KEY)
        if raw:
            return json.loads(raw)
    except:
        pass
    return ["000660","005930"]

def save_favs(codes):
    try:
        localS.setItem(LOCAL_KEY, json.dumps(codes))
    except:
        pass

if "favs" not in st.session_state:
    st.session_state.favs = load_favs()

# =========================
# UI 시작
# =========================
st.set_page_config(page_title="국장 범용 매수/매도 계산기", layout="centered")
st.title("국장 범용 매수/매도 계산기 (통합 안정판)")

listing = fdr.StockListing("KRX")
listing["Code"] = listing["Code"].astype(str).str.zfill(6)
listing["Display"] = listing["Name"] + " (" + listing["Code"] + ")"

# ⭐ 즐겨찾기
st.subheader("⭐ 즐겨찾기")
cols = st.columns(min(5,len(st.session_state.favs)))
for i,c in enumerate(st.session_state.favs):
    name = listing.loc[listing["Code"]==c,"Name"]
    label = name.iloc[0] if not name.empty else c
    with cols[i]:
        if st.button(label):
            st.session_state["picked"]=c

# 종목 선택
default_code = st.session_state.get("picked", st.session_state.favs[0])
default_display = listing.loc[listing["Code"]==default_code,"Display"]
default_display = default_display.iloc[0] if not default_display.empty else listing["Display"].iloc[0]

selected_display = st.selectbox("종목 선택", listing["Display"], index=listing["Display"].tolist().index(default_display))
row = listing[listing["Display"]==selected_display].iloc[0]
code = row["Code"]
name = row["Name"]

# 즐겨찾기 관리
c1,c2 = st.columns(2)
with c1:
    if st.button("➕ 즐겨찾기 추가"):
        if code not in st.session_state.favs:
            st.session_state.favs.append(code)
            save_favs(st.session_state.favs)
with c2:
    if st.button("🗑️ 즐겨찾기 제거"):
        if code in st.session_state.favs:
            st.session_state.favs.remove(code)
            save_favs(st.session_state.favs)

# 설정
lookback = st.slider("고점 기준 기간",20,120,60)
buy_drop_threshold = st.slider("매수 판단 기준(-%)",5,20,8)
trend_ma_period = st.selectbox("추세 기준 이평선",[200,120,60],index=0)

run = st.button("계산")

if run:
    df = fdr.DataReader(code)
    df = df[df.index >= datetime.now()-timedelta(days=365*2)]

    close = df["Close"]
    P = float(close.iloc[-1])
    H = float(close.tail(lookback).max())
    L = float(close.tail(lookback).min())

    lv = {"P":P,"H":H,"L":L}

    verdict, guide, tone, trend_ma = decision_engine(
        lv, lookback, buy_drop_threshold, trend_ma_period, df
    )

    st.subheader("📌 결론")
    if tone=="success": st.success(f"{verdict} - {guide}")
    elif tone=="error": st.error(f"{verdict} - {guide}")
    else: st.warning(f"{verdict} - {guide}")

    st.subheader("📊 주요 지표")
    c1,c2,c3,c4=st.columns(4)
    c1.metric("현재가",krw(P))
    c2.metric("최근 고점",krw(H))
    c3.metric("최근 저점",krw(L))
    c4.metric(f"{trend_ma_period}일선",krw(trend_ma))

    st.subheader("📈 매수 기준")
    st.write(f"1차: {krw(H*0.92)}")
    st.write(f"2차: {krw(H*0.90)}")
    st.write(f"3차: {krw(H*0.85)}")

    memo=f"""
[{name}({code})]
결론: {verdict}
현재가: {krw(P)}
고점({lookback}일): {krw(H)}
{trend_ma_period}일선: {krw(trend_ma)}
1차 매수: {krw(H*0.92)}
2차 매수: {krw(H*0.90)}
3차 매수: {krw(H*0.85)}
"""
    st.subheader("📋 알림 텍스트")
    st.text_area("",memo,height=200)
    copy_button(memo)

    st.subheader("📉 차트")
    fig=go.Figure()
    fig.add_trace(go.Scatter(x=df.index,y=close,name="종가"))
    if trend_ma:
        fig.add_trace(go.Scatter(
            x=df.index,
            y=close.rolling(trend_ma_period).mean(),
            name=f"{trend_ma_period}일선",
            line=dict(width=4)
        ))
    fig.update_layout(height=500)
    st.plotly_chart(fig,use_container_width=True)
