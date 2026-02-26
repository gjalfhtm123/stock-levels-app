# ==============================
# 국장 범용 매수/매도 계산기 2.0
# ==============================

import json
from datetime import datetime, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components
from streamlit_local_storage import LocalStorage
import FinanceDataReader as fdr


# ------------------------------
# 공통 유틸
# ------------------------------
def krw(x):
    if x is None:
        return "—"
    try:
        return f"{int(round(float(x), 0)):,}원"
    except:
        return "—"


def pct(x):
    if x is None:
        return "—"
    try:
        return f"{float(x) * 100:.1f}%"
    except:
        return "—"


def card(title, value, subtitle="", tone="neutral"):
    styles = {
        "neutral": ("#f3f4f6", "#111827"),
        "success": ("#ecfdf5", "#065f46"),
        "warning": ("#fffbeb", "#92400e"),
        "error": ("#fef2f2", "#991b1b"),
    }
    bg, fg = styles.get(tone, styles["neutral"])

    st.markdown(
        f"""
        <div style="
            background:{bg};
            padding:18px;
            border-radius:16px;
            border:1px solid rgba(0,0,0,0.08);
            margin-bottom:12px;">
          <div style="font-size:14px; color:{fg}; margin-bottom:6px;">
            <b>{title}</b>
          </div>
          <div style="font-size:26px; font-weight:800; color:{fg};">
            {value}
          </div>
          <div style="font-size:12px; color:{fg}; opacity:0.8;">
            {subtitle}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


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


def safe_ma(series, window):
    if len(series) < window:
        return None
    return float(series.rolling(window).mean().iloc[-1])


def calc_atr(df, period=14):
    if not {"High", "Low", "Close"}.issubset(df.columns):
        return None

    high = df["High"]
    low = df["Low"]
    close = df["Close"]
    prev_close = close.shift(1)

    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    atr = tr.rolling(period).mean()
    return float(atr.iloc[-1]) if not atr.dropna().empty else None


# ------------------------------
# Decision Engine
# ------------------------------
def decision_engine(P, H, trend_ma, buy_drop_threshold):
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
        guide = "조정 구간"
        tone = "success"
    elif drop >= -0.03:
        verdict = "🟡 고점권 주의"
        guide = "추격 매수 위험"
        tone = "warning"

    return verdict, guide, tone


# ------------------------------
# Streamlit 시작
# ------------------------------
st.set_page_config(page_title="국장 범용 매수/매도 계산기", layout="centered")
st.title("📊 국장 범용 매수/매도 계산기 2.0")

# 종목 로드
listing = fdr.StockListing("KRX")
listing["Code"] = listing["Code"].astype(str).str.zfill(6)
listing["Display"] = listing["Name"] + " (" + listing["Code"] + ")"

# ------------------------------
# 즐겨찾기
# ------------------------------
LOCAL_KEY = "fav_codes_v3"
localS = LocalStorage()

def load_favs():
    try:
        raw = localS.getItem(LOCAL_KEY)
        if raw:
            return json.loads(raw)
    except:
        pass
    return ["000660", "005930"]

def save_favs(codes):
    try:
        localS.setItem(LOCAL_KEY, json.dumps(codes))
    except:
        pass

if "favs" not in st.session_state:
    st.session_state.favs = load_favs()

st.subheader("⭐ 즐겨찾기")
cols = st.columns(min(5, len(st.session_state.favs)))
for i, c in enumerate(st.session_state.favs):
    name = listing.loc[listing["Code"] == c, "Name"]
    label = name.iloc[0] if not name.empty else c
    with cols[i]:
        if st.button(label):
            st.session_state["picked"] = c

# ------------------------------
# 종목 선택
# ------------------------------
default_code = st.session_state.get("picked", st.session_state.favs[0])
default_display = listing.loc[listing["Code"] == default_code, "Display"]
default_display = default_display.iloc[0] if not default_display.empty else listing["Display"].iloc[0]

selected_display = st.selectbox(
    "종목 선택",
    listing["Display"],
    index=listing["Display"].tolist().index(default_display),
)

row = listing[listing["Display"] == selected_display].iloc[0]
code = row["Code"]
name = row["Name"]

c1, c2 = st.columns(2)
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

# ------------------------------
# 설정
# ------------------------------
lookback = st.slider("고점 기준 기간", 20, 120, 60)
buy_drop_threshold = st.slider("매수 판단 기준(-%)", 5, 20, 8)
trend_ma_period = st.selectbox("추세 기준 이평선", [200, 120, 60])
avg_price = st.number_input("내 평단(선택)", min_value=0, value=0, step=1000)

run = st.button("계산")

# ------------------------------
# 계산
# ------------------------------
if run:
    df = fdr.DataReader(code)
    df = df[df.index >= datetime.now() - timedelta(days=365 * 2)]

    close = df["Close"]
    P = float(close.iloc[-1])
    H = float(close.tail(lookback).max())
    L = float(close.tail(lookback).min())

    trend_ma = safe_ma(close, trend_ma_period)
    atr = calc_atr(df)

    # 결론
    verdict, guide, tone = decision_engine(P, H, trend_ma, buy_drop_threshold)

    card("📌 결론", f"{verdict}", guide, tone)

    # 주요 지표
    st.subheader("📊 주요 지표")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("현재가", krw(P))
    c2.metric("최근 고점", krw(H))
    c3.metric("최근 저점", krw(L))
    c4.metric(f"{trend_ma_period}일선", krw(trend_ma))

    # 매수 기준
    st.subheader("📈 매수 기준")
    st.write(f"1차: {krw(H*0.92)}")
    st.write(f"2차: {krw(H*0.90)}")
    st.write(f"3차: {krw(H*0.85)}")

    # 평단 기준
    if avg_price > 0:
        st.subheader("🎯 평단 기준 목표")
        t1, t2, t3, t4 = st.columns(4)
        t1.metric("+10%", krw(avg_price*1.1))
        t2.metric("+20%", krw(avg_price*1.2))
        t3.metric("-10%", krw(avg_price*0.9))
        t4.metric("-15%", krw(avg_price*0.85))

    # 알림 텍스트
    memo = f"""
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
    st.text_area("", memo, height=200)
    copy_button(memo)

    # 차트
    st.subheader("📉 차트")
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df.index, y=close, name="종가"))
    if trend_ma:
        fig.add_trace(go.Scatter(
            x=df.index,
            y=close.rolling(trend_ma_period).mean(),
            name=f"{trend_ma_period}일선",
            line=dict(width=4)
        ))
    fig.update_layout(height=500)
    st.plotly_chart(fig, use_container_width=True)
