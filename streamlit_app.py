import streamlit as st
import FinanceDataReader as fdr
import pandas as pd
from datetime import datetime, timedelta

# ----------------------------
# UI helpers
# ----------------------------
def krw(x):
    if x is None or x == "데이터 부족":
        return "—"
    try:
        return f"{int(round(float(x), 0)):,}원"
    except:
        return str(x)

def card(title, value, subtitle="", tone="neutral"):
    # tone: neutral / buy / sell / warn
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
            padding:16px 16px;
            border-radius:16px;
            border: 1px solid rgba(0,0,0,0.06);
            margin-bottom:10px;">
          <div style="font-size:13px; color:{fg}; opacity:0.85; margin-bottom:6px;">
            <b>{title}</b>
          </div>
          <div style="font-size:28px; color:{fg}; font-weight:800; line-height:1.15;">
            {value}
          </div>
          <div style="font-size:12px; color:{fg}; opacity:0.75; margin-top:6px;">
            {subtitle}
          </div>
        </div>
        """,
        unsafe_allow_html=True
    )

@st.cache_data(ttl=60*60*12)  # 12h
def load_krx_listing():
    df = fdr.StockListing("KRX")
    df = df[["Code", "Name", "Market"]].dropna()
    df["Code"] = df["Code"].astype(str).str.zfill(6)
    df["Display"] = df["Name"] + " (" + df["Code"] + ", " + df["Market"].astype(str) + ")"
    return df

@st.cache_data(ttl=60*15)
def load_price(code: str):
    return fdr.DataReader(code)

def safe_ma(series: pd.Series, window: int):
    if len(series) < window:
        return None
    return float(series.rolling(window).mean().iloc[-1])

def calc_levels(df: pd.DataFrame, lookback: int = 60):
    close = df["Close"].dropna()
    P = float(close.iloc[-1])                 # latest close
    H = float(close.tail(lookback).max())     # lookback high
    L = float(close.tail(lookback).min())     # lookback low

    ma20  = safe_ma(close, 20)
    ma60  = safe_ma(close, 60)
    ma200 = safe_ma(close, 200)

    # near-high 판단: 최근 고점의 99.5% 이상이면 "고점권"
    near_high = P >= H * 0.995

    # 기본 조정 매수 레벨
    buy_8  = H * 0.92
    buy_10 = H * 0.90
    buy_15 = H * 0.85

    # 추격/눌림 레벨 (고점권일 때)
    pull20 = ma20
    pull60 = ma60
    breakout = H * 1.01  # 고점 +1%

    # 리스크/매도 가이드 (기본형)
    risk_high_m10 = H * 0.90
    risk_high_m15 = H * 0.85

    trend = None
    if ma200 is not None:
        trend = "상승(200일선 위)" if P >= ma200 else "주의(200일선 아래)"
    else:
        trend = "데이터 부족"

    return {
        "P": P, "H": H, "L": L,
        "buy_8": buy_8, "buy_10": buy_10, "buy_15": buy_15,
        "ma20": ma20, "ma60": ma60, "ma200": ma200,
        "near_high": near_high,
        "pull20": pull20, "pull60": pull60, "breakout": breakout,
        "risk_high_m10": risk_high_m10, "risk_high_m15": risk_high_m15,
        "trend": trend,
    }

# ----------------------------
# App
# ----------------------------
st.set_page_config(page_title="국장 매수/매도 기준값 계산기", layout="centered")
st.title("국장 매수/매도 기준값 계산기 (업데이트 UI)")

listing = load_krx_listing()

st.subheader("1) 종목 선택")
default_name = "SK하이닉스"
display_list = listing["Display"].tolist()
try:
    default_idx = int(listing.index[listing["Name"] == default_name][0])
except Exception:
    default_idx = 0

selected_display = st.selectbox(
    "종목명을 검색해서 선택하세요 (코드 입력 X)",
    options=display_list,
    index=default_idx
)
row = listing[listing["Display"] == selected_display].iloc[0]
code = row["Code"]
name = row["Name"]

st.subheader("2) 내 정보(선택)")
c1, c2 = st.columns(2)
with c1:
    avg_price = st.number_input("내 평단(원) (없으면 0)", min_value=0, value=0, step=1000)
with c2:
    lookback = st.slider("고점/저점 계산 기간(일)", 20, 120, 60)

if st.button("계산"):
    with st.spinner("데이터 불러오는 중..."):
        df = load_price(code)

    if df is None or df.empty:
        st.error("데이터를 가져오지 못했어요. 잠시 후 다시 시도해 주세요.")
        st.stop()

    # 최근 2년만
    two_years_ago = datetime.now() - timedelta(days=365*2)
    df2 = df[df.index >= two_years_ago]
    lv = calc_levels(df2, lookback)

    # ----------------------------
    # Header metrics
    # ----------------------------
    st.markdown("---")
    st.subheader(f"📌 {name} ({code}) 요약")

    m1, m2, m3 = st.columns(3)
    m1.metric("현재가(종가)", krw(lv["P"]))
    m2.metric(f"최근 {lookback}일 고점", krw(lv["H"]))
    m3.metric("장기추세", lv["trend"])

    # ----------------------------
    # Big callouts: Buy / Sell
    # ----------------------------
    st.markdown("## ✅ 추천 매수 구간 (눈에 띄게)")
    b1, b2, b3 = st.columns(3)
    with b1:
        card("1차(완만한 조정)", krw(lv["buy_8"]), "최근 고점 대비 -8%", tone="buy")
    with b2:
        card("2차(일반 조정)", krw(lv["buy_10"]), "최근 고점 대비 -10%", tone="buy")
    with b3:
        card("3차(강한 조정)", krw(lv["buy_15"]), "최근 고점 대비 -15%", tone="buy")

    # 고점권이면 돌파/눌림도 크게
    if lv["near_high"]:
        st.markdown("## 🚀 고점권 모드 (돌파/눌림 매수)")
        d1, d2, d3 = st.columns(3)
        with d1:
            card("눌림(20일선)", krw(lv["pull20"]), "강세장 눌림 타점", tone="buy")
        with d2:
            card("눌림(60일선)", krw(lv["pull60"]), "조정 깊을 때 2차", tone="buy")
        with d3:
            card("추격(고점+1%)", krw(lv["breakout"]), "돌파 확인 후 분할", tone="buy")
    else:
        st.info("현재는 '고점권'이 아니라서 조정매수(분할) 중심으로 보는 게 더 자연스럽습니다.")

    st.markdown("## 🛡️ 추천 매도/리스크 구간 (눈에 띄게)")
    s1, s2, s3 = st.columns(3)
    with s1:
        card("경고(-10%)", krw(lv["risk_high_m10"]), "고점 대비 -10%: 비중 점검", tone="warn")
    with s2:
        card("강경고(-15%)", krw(lv["risk_high_m15"]), "고점 대비 -15%: 축소 고려", tone="warn")
    with s3:
        card("추세선(200일선)", krw(lv["ma200"]), "장기 추세 붕괴 기준", tone="warn")

    # ----------------------------
    # Avg price based targets
    # ----------------------------
    if avg_price and avg_price > 0:
        st.markdown("## 🎯 내 평단 기준 목표가/손절가 (자동)")
        tp1 = avg_price * 1.10
        tp2 = avg_price * 1.20
        tp3 = avg_price * 1.30
        sl1 = avg_price * 0.90
        sl2 = avg_price * 0.85

        t1, t2, t3, t4, t5 = st.columns(5)
        with t1: card("익절 +10%", krw(tp1), f"평단 {krw(avg_price)} 기준", tone="sell")
        with t2: card("익절 +20%", krw(tp2), "단계적 익절", tone="sell")
        with t3: card("익절 +30%", krw(tp3), "강세장 목표", tone="sell")
        with t4: card("손절 -10%", krw(sl1), "리스크 제한", tone="warn")
        with t5: card("손절 -15%", krw(sl2), "강한 방어", tone="warn")
    else:
        st.caption("내 평단을 입력하면 익절/손절 가격이 자동으로 계산됩니다.")

    # ----------------------------
    # Details table + chart
    # ----------------------------
    st.markdown("---")
    st.subheader("참고값(세부)")
    detail_rows = [
        ("현재가(종가)", lv["P"]),
        (f"최근 {lookback}일 고점", lv["H"]),
        (f"최근 {lookback}일 저점", lv["L"]),
        ("20일선", lv["ma20"]),
        ("60일선", lv["ma60"]),
        ("200일선", lv["ma200"]),
        ("상태", "고점권" if lv["near_high"] else "고점권 아님"),
    ]
    st.table(pd.DataFrame([(k, krw(v)) for k, v in detail_rows], columns=["항목", "값"]))

    st.subheader("최근 2년 종가 추이")
    st.line_chart(df2["Close"])