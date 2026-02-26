import streamlit as st
import FinanceDataReader as fdr
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta

# =========================
# Helpers
# =========================
def krw(x):
    if x is None:
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

@st.cache_data(ttl=60 * 60 * 12)  # 12h
def load_krx_listing():
    df = fdr.StockListing("KRX")
    df = df[["Code", "Name", "Market"]].dropna()
    df["Code"] = df["Code"].astype(str).str.zfill(6)
    df["Display"] = df["Name"] + " (" + df["Code"] + ")"
    return df

@st.cache_data(ttl=60 * 15)  # 15m
def load_price(code: str):
    return fdr.DataReader(code)

def safe_ma(series: pd.Series, window: int):
    if len(series) < window:
        return None
    return float(series.rolling(window).mean().iloc[-1])

def calc_atr(df: pd.DataFrame, period: int = 14):
    """
    ATR(14) = TR의 period 이동평균
    TR = max(High-Low, abs(High-prevClose), abs(Low-prevClose))
    """
    needed_cols = {"High", "Low", "Close"}
    if not needed_cols.issubset(df.columns):
        return None

    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    close = df["Close"].astype(float)
    prev_close = close.shift(1)

    tr = pd.concat([
        (high - low),
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)

    atr = tr.rolling(period).mean()
    if atr.dropna().empty:
        return None
    return float(atr.iloc[-1])

def calc_pivots(df: pd.DataFrame):
    """
    전일 고/저/종 기준 Pivot / R1 / R2
    Pivot = (H+L+C)/3
    R1 = 2*Pivot - L
    R2 = Pivot + (H-L)
    """
    needed_cols = {"High", "Low", "Close"}
    if not needed_cols.issubset(df.columns) or len(df) < 2:
        return None, None, None

    prev = df.iloc[-2]
    H = float(prev["High"])
    L = float(prev["Low"])
    C = float(prev["Close"])
    pivot = (H + L + C) / 3.0
    r1 = 2 * pivot - L
    r2 = pivot + (H - L)
    return pivot, r1, r2

def calc_levels(df: pd.DataFrame, lookback: int):
    close = df["Close"].dropna().astype(float)
    P = float(close.iloc[-1])
    H = float(close.tail(lookback).max())
    L = float(close.tail(lookback).min())

    ma20 = safe_ma(close, 20)
    ma60 = safe_ma(close, 60)
    ma200 = safe_ma(close, 200)
    atr14 = calc_atr(df, 14)
    pivot, r1, r2 = calc_pivots(df)

    near_high = P >= H * 0.995

    return {
        "P": P, "H": H, "L": L,
        "ma20": ma20, "ma60": ma60, "ma200": ma200,
        "atr14": atr14,
        "pivot": pivot, "r1": r1, "r2": r2,
        "near_high": near_high,
        # buy levels from recent high
        "buy8": H * 0.92,
        "buy10": H * 0.90,
        "buy15": H * 0.85,
        # warning levels
        "risk10": H * 0.90,
        "risk15": H * 0.85,
    }

def pick_defense_line(defense_mode: str, lv: dict):
    """R:R 계산에 쓸 방어선 선택"""
    if defense_mode == "고점-10%":
        return lv["risk10"]
    if defense_mode == "20일선":
        return lv["ma20"]
    if defense_mode == "60일선":
        return lv["ma60"]
    # 기본
    return lv["risk10"]

def build_sell_targets(lv: dict, basis: str, stages: int, defense_mode: str):
    """
    사용자가 선택한 basis에 따라 목표가 후보를 (최대 3단) 만들어줌.
    """
    P = lv["P"]
    H = lv["H"]
    atr = lv["atr14"]
    r1 = lv["r1"]
    r2 = lv["r2"]

    defense = pick_defense_line(defense_mode, lv)
    risk = None
    if defense is not None:
        risk = P - float(defense)

    # stage 목표 리스트(최대 3개)
    targets = []

    # 1) 최근고점 기반
    if basis == "최근고점(H)":
        if stages == 1:
            targets = [H]
        else:
            # 고점 + ATR을 더해서 단계 만들기 (ATR 없으면 1~3%로 대체)
            if atr is not None:
                targets = [H, H + atr, H + 2 * atr]
            else:
                targets = [H, H * 1.03, H * 1.06]

    # 2) 피벗 기반
    elif basis == "피벗 R1/R2":
        if r1 is None or r2 is None:
            # 데이터 없으면 fallback
            if atr is not None:
                targets = [P + atr, P + 2 * atr, P + 3 * atr]
            else:
                targets = [P * 1.03, P * 1.06, P * 1.09]
        else:
            if stages == 1:
                targets = [r1]
            elif stages == 2:
                targets = [r1, r2]
            else:
                # R2 이후는 ATR로 확장 (없으면 +3% 대체)
                if atr is not None:
                    targets = [r1, r2, r2 + atr]
                else:
                    targets = [r1, r2, r2 * 1.03]

    # 3) ATR 기반
    elif basis == "ATR(변동성)":
        if atr is None:
            # fallback
            targets = [P * 1.03, P * 1.06, P * 1.09]
        else:
            if stages == 1:
                targets = [P + 2 * atr]  # 기본은 2ATR
            elif stages == 2:
                targets = [P + 1 * atr, P + 2 * atr]
            else:
                targets = [P + 1 * atr, P + 2 * atr, P + 3 * atr]

    # 4) R:R 기반
    elif basis == "R:R(손절 대비)":
        if risk is None or risk <= 0:
            # 방어선이 현재가 이상이거나 데이터 부족이면 fallback
            if atr is not None:
                targets = [P + atr, P + 2 * atr, P + 3 * atr]
            else:
                targets = [P * 1.03, P * 1.06, P * 1.09]
        else:
            if stages == 1:
                targets = [P + 2 * risk]
            elif stages == 2:
                targets = [P + 2 * risk, P + 3 * risk]
            else:
                targets = [P + 2 * risk, P + 3 * risk, P + 4 * risk]

    # stages만큼 자르기
    targets = targets[:stages]
    # 반올림
    targets = [float(t) for t in targets]
    return targets, defense

# =========================
# App UI
# =========================
st.set_page_config(page_title="국장 매수/매도 기준값 계산기", layout="centered")
st.title("국장 매수/매도 기준값 계산기 (매도 설정 선택형)")

listing = load_krx_listing()

st.subheader("1) 종목 선택")
default_name = "SK하이닉스"
default_idx = int(listing.index[listing["Name"] == default_name][0]) if (listing["Name"] == default_name).any() else 0

selected_display = st.selectbox(
    "종목명을 검색해서 선택하세요 (코드 입력 X)",
    options=listing["Display"].tolist(),
    index=default_idx
)
row = listing[listing["Display"] == selected_display].iloc[0]
code = row["Code"]
name = row["Name"]

st.subheader("2) 기본 설정")
c1, c2 = st.columns(2)
with c1:
    lookback = st.slider("고점/저점 계산 기간(일)", 20, 120, 60)
with c2:
    avg_price = st.number_input("내 평단(원) (선택)", min_value=0, value=0, step=1000)

st.subheader("3) 매도 설정 (사용자가 선택)")
sell_mode = st.radio(
    "매도 방식",
    ["단계 익절(추천)", "목표가 도달 시 전량 익절", "추세 이탈 시 축소(이평 이탈)"],
    horizontal=False
)

basis = st.selectbox(
    "목표가 기준 선택",
    ["ATR(변동성)", "최근고점(H)", "피벗 R1/R2", "R:R(손절 대비)"],
    index=0
)

defense_mode = st.selectbox(
    "R:R 계산용 방어선(손절 기준) 선택",
    ["고점-10%", "20일선", "60일선"],
    index=0
)

stages = 3
if sell_mode == "단계 익절(추천)":
    stages = st.slider("익절 단계 수", 2, 3, 3)
elif sell_mode == "목표가 도달 시 전량 익절":
    stages = 1
else:
    stages = 0  # 추세 이탈 모드: 목표가 대신 이평선 기준 제시

# 단계익절 비중
weights = None
if sell_mode == "단계 익절(추천)":
    if stages == 2:
        w1 = st.slider("1차 비중(%)", 10, 90, 50, step=5)
        w2 = 100 - w1
        weights = [w1, w2]
        st.caption(f"2차 비중은 자동으로 {w2}%로 설정됩니다.")
    else:
        w1 = st.slider("1차 비중(%)", 10, 80, 30, step=5)
        w2 = st.slider("2차 비중(%)", 10, 80, 30, step=5)
        w3 = 100 - w1 - w2
        if w3 < 0:
            st.error("비중 합이 100%를 초과했습니다. 1차/2차를 줄여주세요.")
        else:
            weights = [w1, w2, w3]
            st.caption(f"3차 비중은 자동으로 {w3}%로 설정됩니다.")

run = st.button("계산")

if run:
    with st.spinner("데이터 불러오는 중..."):
        df = load_price(code)

    if df is None or df.empty:
        st.error("데이터를 가져오지 못했어요. 잠시 후 다시 시도해 주세요.")
        st.stop()

    # 최근 2년만 (UI 가독성)
    two_years_ago = datetime.now() - timedelta(days=365 * 2)
    df2 = df[df.index >= two_years_ago].copy()
    if df2.empty:
        st.error("최근 2년 데이터가 비어 있어요. 기간을 늘리거나 다시 시도해 주세요.")
        st.stop()

    lv = calc_levels(df2, lookback)

    # -------------------------
    # 요약
    # -------------------------
    st.markdown("---")
    st.subheader(f"📌 {name} ({code}) 요약")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("현재가(종가)", krw(lv["P"]))
    m2.metric(f"최근 {lookback}일 고점(H)", krw(lv["H"]))
    m3.metric(f"최근 {lookback}일 저점(L)", krw(lv["L"]))
    trend_text = "데이터 부족"
    if lv["ma200"] is not None:
        trend_text = "상승(200일선 위)" if lv["P"] >= lv["ma200"] else "주의(200일선 아래)"
    m4.metric("장기추세", trend_text)

    # -------------------------
    # 초보자 설명
    # -------------------------
    with st.expander("📖 추천 가격이 이렇게 계산됩니다 (초보자용)"):
        st.markdown(f"""
- **추천 매수(-8/-10/-15)**는 최근 {lookback}일 고점(H) 기준 조정폭입니다.
- **ATR(변동성)**은 최근 14일간 평균 흔들림(원 단위)이며, 목표가/손절을 종목 성격에 맞게 잡는 데 유용합니다.
- **피벗 R1/R2**는 전일 고/저/종으로 계산하는 대표 저항선입니다.
- **R:R(손절 대비)**는 내가 정한 방어선(손절 기준) 대비 수익 목표를 2배/3배로 잡는 방식입니다.
        """)

    # -------------------------
    # 추천 매수 구간 (카드)
    # -------------------------
    st.markdown("## ✅ 추천 매수 구간")
    b1, b2, b3 = st.columns(3)
    with b1:
        card("1차 (-8%)", krw(lv["buy8"]), f"고점 × 0.92 = {krw(lv['H'])} × 0.92", "buy")
    with b2:
        card("2차 (-10%)", krw(lv["buy10"]), f"고점 × 0.90 = {krw(lv['H'])} × 0.90", "buy")
    with b3:
        card("3차 (-15%)", krw(lv["buy15"]), f"고점 × 0.85 = {krw(lv['H'])} × 0.85", "buy")

    # -------------------------
    # 추천 리스크/매도 구간 (경고)
    # -------------------------
    st.markdown("## 🛡️ 추천 리스크/매도(경고) 구간")
    r1c, r2c, r3c = st.columns(3)
    with r1c:
        card("경고 (-10%)", krw(lv["risk10"]), "고점 대비 -10% 구간", "warn")
    with r2c:
        card("강경고 (-15%)", krw(lv["risk15"]), "고점 대비 -15% 구간", "warn")
    with r3c:
        card("200일선", krw(lv["ma200"]), "장기 추세 기준(이탈 시 주의)", "warn")

    # -------------------------
    # 매도 설정 결과(사용자 선택 반영)
    # -------------------------
    st.markdown("## 🎯 내가 선택한 매도 설정 결과")

    sell_targets = []
    defense_line = None

    if sell_mode == "추세 이탈 시 축소(이평 이탈)":
        t1, t2, t3 = st.columns(3)
        with t1:
            card("축소 신호(20일선)", krw(lv["ma20"]), "종가가 20일선 아래면 비중 점검", "warn")
        with t2:
            card("축소 신호(60일선)", krw(lv["ma60"]), "조정이 깊어질 때 방어", "warn")
        with t3:
            card("최종 방어(200일선)", krw(lv["ma200"]), "장기 추세 붕괴 기준", "warn")
    else:
        sell_targets, defense_line = build_sell_targets(lv, basis, stages, defense_mode)

        # 표시용 카드
        if sell_mode == "목표가 도달 시 전량 익절":
            card("전량 익절 목표가", krw(sell_targets[0]), f"기준: {basis}", "sell")
            if defense_line is not None:
                st.caption(f"R:R 방어선({defense_mode}): {krw(defense_line)}")
        else:
            # 단계익절
            if weights is None:
                st.warning("비중 설정이 유효하지 않습니다(합계 100% 확인).")
            else:
                cols = st.columns(len(sell_targets))
                for i, (tgt, w, col) in enumerate(zip(sell_targets, weights, cols), start=1):
                    with col:
                        card(f"{i}차 목표가 ({w}%)", krw(tgt), f"기준: {basis}", "sell")
                if defense_line is not None:
                    st.caption(f"R:R 방어선({defense_mode}): {krw(defense_line)}")

    # -------------------------
    # 평단 기준(보조)
    # -------------------------
    if avg_price and avg_price > 0:
        st.markdown("## 📌 (보조) 내 평단 기준 참고 목표/방어")
        tp1 = avg_price * 1.10
        tp2 = avg_price * 1.20
        tp3 = avg_price * 1.30
        sl1 = avg_price * 0.90
        sl2 = avg_price * 0.85
        t1, t2, t3, t4, t5 = st.columns(5)
        with t1: card("익절 +10%", krw(tp1), f"평단 {krw(avg_price)} 기준", "sell")
        with t2: card("익절 +20%", krw(tp2), "단계적 익절", "sell")
        with t3: card("익절 +30%", krw(tp3), "강세장 목표", "sell")
        with t4: card("방어 -10%", krw(sl1), "리스크 제한", "warn")
        with t5: card("방어 -15%", krw(sl2), "강한 방어", "warn")

    # -------------------------
    # 참고값(세부 표)
    # -------------------------
    st.markdown("---")
    st.subheader("📊 참고값(세부)")
    detail_rows = [
        ("현재가(종가)", lv["P"]),
        (f"최근 {lookback}일 고점", lv["H"]),
        (f"최근 {lookback}일 저점", lv["L"]),
        ("ATR(14)", lv["atr14"]),
        ("피벗 Pivot", lv["pivot"]),
        ("피벗 R1", lv["r1"]),
        ("피벗 R2", lv["r2"]),
        ("20일선", lv["ma20"]),
        ("60일선", lv["ma60"]),
        ("200일선", lv["ma200"]),
        ("상태", "고점권" if lv["near_high"] else "일반 구간"),
    ]
    table_data = []
    for k, v in detail_rows:
        if k == "상태":
            table_data.append((k, v))
        else:
            table_data.append((k, krw(v)))
    st.table(pd.DataFrame(table_data, columns=["항목", "값"]))

    # -------------------------
    # 차트 (수평선 표시)
    # -------------------------
    st.markdown("## 📈 최근 2년 차트")
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df2.index, y=df2["Close"], mode="lines", name="종가"))

    close = df2["Close"].dropna().astype(float)
    if len(close) >= 20:
        fig.add_trace(go.Scatter(x=df2.index, y=close.rolling(20).mean(), mode="lines", name="20일선", opacity=0.6))
    if len(close) >= 60:
        fig.add_trace(go.Scatter(x=df2.index, y=close.rolling(60).mean(), mode="lines", name="60일선", opacity=0.6))
    if len(close) >= 200:
        fig.add_trace(go.Scatter(x=df2.index, y=close.rolling(200).mean(), mode="lines", name="200일선", opacity=0.6))

    # 매수/경고선
    for y, label in [
        (lv["buy8"], "매수 -8%"),
        (lv["buy10"], "매수 -10%"),
        (lv["buy15"], "매수 -15%"),
        (lv["risk10"], "경고 -10%"),
        (lv["risk15"], "강경고 -15%"),
    ]:
        fig.add_hline(y=y, line_dash="dash", annotation_text=label)

    # 매도 목표선(사용자 선택)
    if sell_mode != "추세 이탈 시 축소(이평 이탈)" and sell_targets:
        for i, t in enumerate(sell_targets, start=1):
            fig.add_hline(y=t, line_dash="dot", annotation_text=f"목표 {i}")

    # 방어선 (R:R용)
    if defense_line is not None:
        fig.add_hline(y=float(defense_line), line_dash="dash", annotation_text=f"방어선({defense_mode})")

    fig.update_layout(
        height=540,
        margin=dict(l=10, r=10, t=30, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    st.plotly_chart(fig, use_container_width=True)

    st.caption("※ 본 앱은 과거 가격/이평/변동성 기반 기준값을 계산해 보여주는 도구이며, 투자 판단과 책임은 사용자에게 있습니다.")
