import streamlit as st
import FinanceDataReader as fdr
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta

# ----------------------------
# Helper
# ----------------------------
def krw(x):
    if x is None or x == "데이터 부족":
        return "—"
    try:
        return f"{int(round(float(x), 0)):,}원"
    except:
        return str(x)

def card(title, value, subtitle="", tone="neutral"):
    styles = {
        "neutral": ("#f3f4f6", "#111827"),
        "buy": ("#ecfdf5", "#065f46"),
        "sell": ("#eff6ff", "#1d4ed8"),
        "warn": ("#fff7ed", "#9a3412"),
    }
    bg, fg = styles.get(tone, styles["neutral"])

    st.markdown(
        f"""
        <div style="
            background:{bg};
            padding:16px;
            border-radius:16px;
            border: 1px solid rgba(0,0,0,0.06);
            margin-bottom:10px;">
          <div style="font-size:13px; color:{fg}; opacity:0.85; margin-bottom:6px;">
            <b>{title}</b>
          </div>
          <div style="font-size:28px; color:{fg}; font-weight:800;">
            {value}
          </div>
          <div style="font-size:12px; color:{fg}; opacity:0.75;">
            {subtitle}
          </div>
        </div>
        """,
        unsafe_allow_html=True
    )

@st.cache_data(ttl=60*60*12)
def load_krx_listing():
    df = fdr.StockListing("KRX")
    df = df[["Code", "Name", "Market"]].dropna()
    df["Code"] = df["Code"].astype(str).str.zfill(6)
    df["Display"] = df["Name"] + " (" + df["Code"] + ")"
    return df

@st.cache_data(ttl=60*15)
def load_price(code):
    return fdr.DataReader(code)

def safe_ma(series, window):
    if len(series) < window:
        return None
    return float(series.rolling(window).mean().iloc[-1])

def calc_levels(df, lookback):
    close = df["Close"].dropna()
    P = float(close.iloc[-1])
    H = float(close.tail(lookback).max())
    L = float(close.tail(lookback).min())

    ma20 = safe_ma(close, 20)
    ma60 = safe_ma(close, 60)
    ma200 = safe_ma(close, 200)

    return {
        "P": P, "H": H, "L": L,
        "buy8": H * 0.92,
        "buy10": H * 0.90,
        "buy15": H * 0.85,
        "risk10": H * 0.90,
        "risk15": H * 0.85,
        "ma20": ma20,
        "ma60": ma60,
        "ma200": ma200,
    }

# ----------------------------
# UI
# ----------------------------
st.set_page_config(page_title="국장 매수/매도 기준값 계산기", layout="centered")
st.title("국장 매수/매도 기준값 계산기")

listing = load_krx_listing()

selected = st.selectbox(
    "종목을 선택하세요",
    listing["Display"].tolist()
)

row = listing[listing["Display"] == selected].iloc[0]
code = row["Code"]
name = row["Name"]

lookback = st.slider("고점 계산 기간(일)", 20, 120, 60)
avg_price = st.number_input("내 평단(선택)", min_value=0, value=0, step=1000)

if st.button("계산"):

    df = load_price(code)
    two_years_ago = datetime.now() - timedelta(days=365*2)
    df = df[df.index >= two_years_ago]

    lv = calc_levels(df, lookback)

    st.markdown("## 📌 요약")
    c1, c2, c3 = st.columns(3)
    c1.metric("현재가", krw(lv["P"]))
    c2.metric(f"최근 {lookback}일 고점", krw(lv["H"]))
    trend = "상승" if lv["P"] >= (lv["ma200"] or 0) else "주의"
    c3.metric("장기 추세(200일선)", trend)

    st.markdown("## ✅ 추천 매수 구간")
    b1, b2, b3 = st.columns(3)
    b1.write(card("1차 (-8%)", krw(lv["buy8"]), f"고점 × 0.92", "buy"))
    b2.write(card("2차 (-10%)", krw(lv["buy10"]), f"고점 × 0.90", "buy"))
    b3.write(card("3차 (-15%)", krw(lv["buy15"]), f"고점 × 0.85", "buy"))

    st.markdown("## 🛡 추천 리스크/매도 구간")
    s1, s2 = st.columns(2)
    s1.write(card("경고 (-10%)", krw(lv["risk10"]), "고점 × 0.90", "warn"))
    s2.write(card("강경고 (-15%)", krw(lv["risk15"]), "고점 × 0.85", "warn"))

    if avg_price > 0:
        st.markdown("## 🎯 평단 기준 목표가")
        t1, t2, t3 = st.columns(3)
        t1.write(card("+10%", krw(avg_price*1.1), "", "sell"))
        t2.write(card("+20%", krw(avg_price*1.2), "", "sell"))
        t3.write(card("-10% 손절", krw(avg_price*0.9), "", "warn"))

    with st.expander("📖 계산 기준 설명 보기"):
        st.markdown(f"""
- 최근 {lookback}일 최고가(H)를 기준으로 계산합니다.
- 1차 매수 = H × 0.92
- 2차 매수 = H × 0.90
- 3차 매수 = H × 0.85
- 경고 구간 = H × 0.90 / H × 0.85
- 장기 추세는 200일 이동평균선 기준입니다.
""")

    st.markdown("## 📈 최근 2년 차트")
    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=df.index, y=df["Close"],
        mode="lines", name="종가"
    ))

    for price, label, color in [
        (lv["buy8"], "매수 -8%", "green"),
        (lv["buy10"], "매수 -10%", "green"),
        (lv["buy15"], "매수 -15%", "green"),
        (lv["risk10"], "경고 -10%", "orange"),
        (lv["risk15"], "경고 -15%", "red"),
    ]:
        fig.add_hline(y=price, line_dash="dash", line_color=color,
                      annotation_text=label)

    st.plotly_chart(fig, use_container_width=True)
