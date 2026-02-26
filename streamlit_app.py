import json
import streamlit as st
import FinanceDataReader as fdr
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta
from streamlit_local_storage import LocalStorage
import streamlit.components.v1 as components

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

def pct(x):
    if x is None:
        return "—"
    try:
        return f"{float(x)*100:.1f}%"
    except:
        return str(x)

def card(title, value, subtitle="", tone="neutral"):
    styles = {
        "neutral": ("#f3f4f6", "#111827"),
        "buy": ("#ecfdf5", "#065f46"),
        "sell": ("#eff6ff", "#1d4ed8"),
        "warn": ("#fff7ed", "#9a3412"),
        "risk_g": ("#ecfdf5", "#065f46"),
        "risk_y": ("#fffbeb", "#92400e"),
        "risk_r": ("#fef2f2", "#991b1b"),
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

def copy_to_clipboard_button(text: str, button_label: str = "📋 복사", height: int = 48):
    """
    Streamlit에서 클립보드 복사를 위해 JS 버튼을 심어주는 함수.
    모바일/크롬/사파리 대부분에서 동작.
    """
    safe_text = json.dumps(text)  # JS 문자열 안전 처리
    html = f"""
    <div style="display:flex; gap:10px; align-items:center;">
      <button id="copyBtn"
        style="
          width:100%;
          height:{height}px;
          border-radius:12px;
          border:1px solid rgba(0,0,0,0.1);
          background:#111827;
          color:white;
          font-weight:700;
          cursor:pointer;">
        {button_label}
      </button>
    </div>
    <script>
      const txt = {safe_text};
      const btn = document.getElementById("copyBtn");
      btn.addEventListener("click", async () => {{
        try {{
          await navigator.clipboard.writeText(txt);
          btn.innerText = "✅ 복사됨!";
          setTimeout(() => btn.innerText = "{button_label}", 1200);
        }} catch (e) {{
          btn.innerText = "⚠️ 복사 실패(길게 눌러 복사)";
          setTimeout(() => btn.innerText = "{button_label}", 1500);
        }}
      }});
    </script>
    """
    components.html(html, height=height + 10)

@st.cache_data(ttl=60 * 60 * 12)
def load_krx_listing():
    df = fdr.StockListing("KRX")
    df = df[["Code", "Name", "Market"]].dropna()
    df["Code"] = df["Code"].astype(str).str.zfill(6)
    df["Display"] = df["Name"] + " (" + df["Code"] + ")"
    return df

@st.cache_data(ttl=60 * 15)
def load_price(code: str):
    return fdr.DataReader(code)

def safe_ma(series: pd.Series, window: int):
    if len(series) < window:
        return None
    return float(series.rolling(window).mean().iloc[-1])

def calc_atr(df: pd.DataFrame, period: int = 14):
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

    return {
        "P": P, "H": H, "L": L,
        "ma20": ma20, "ma60": ma60, "ma200": ma200,
        "atr14": atr14,
        "pivot": pivot, "r1": r1, "r2": r2,
        "buy8": H * 0.92,
        "buy10": H * 0.90,
        "buy15": H * 0.85,
        "risk10": H * 0.90,
        "risk15": H * 0.85,
    }

# =========================
# Beginner-friendly logic
# =========================
def risk_grade(lv: dict):
    if lv["atr14"] is None or lv["P"] is None:
        return ("🟡 보통", "데이터 부족으로 보수적으로 판단", "risk_y", None)

    atr_pct = lv["atr14"] / lv["P"]
    if atr_pct < 0.02:
        return ("🟢 낮음", f"변동성 낮음(ATR≈{pct(atr_pct)})", "risk_g", atr_pct)
    elif atr_pct < 0.04:
        return ("🟡 보통", f"변동성 보통(ATR≈{pct(atr_pct)})", "risk_y", atr_pct)
    else:
        return ("🔴 높음", f"변동성 높음(ATR≈{pct(atr_pct)})", "risk_r", atr_pct)

def position_summary(lv: dict):
    P, H = lv["P"], lv["H"]
    ma200 = lv["ma200"]

    drop = None
    if P and H:
        drop = (P / H) - 1.0

    trend = None
    if ma200 is not None:
        trend = "상승 추세" if P >= ma200 else "하락/조정 추세"

    if drop is None:
        return "현재 위치를 계산하기엔 데이터가 부족해요."
    if drop >= -0.03:
        base = "고점권(추격 매수 주의)"
    elif drop >= -0.10:
        base = "조정 초입(분할매수 고려)"
    else:
        base = "조정/하락 구간(리스크 관리 우선)"

    if trend:
        return f"{base} · {trend}"
    return base

def decision_engine(lv: dict, lookback: int, buy_drop_threshold: float, trend_ma_period: int, df2: pd.DataFrame):
    """
    초보자용 의사결정 엔진:
    - 고점 대비 하락률
    - 200일선 위/아래(장기 추세)
    - 변동성(ATR%) 기반으로
      [매수/관망/축소] 결론 + 이유 3줄을 반환
    """
    P, H = lv.get("P"), lv.get("H")
    ma200 = lv.get("ma200")
    atr = lv.get("atr14")

    reasons = []

    # 1) 고점 대비 위치
    drop = None
    if P and H:
        drop = (P / H) - 1.0  # 음수면 고점 대비 하락
        if drop >= -0.03:
            reasons.append(f"최근 {lookback}일 고점 대비 거의 근처(추격 매수 주의)")
        elif drop >= -0.10:
            reasons.append(f"최근 {lookback}일 고점 대비 조정 구간(분할 접근 유리)")
        else:
            reasons.append(f"최근 {lookback}일 고점 대비 크게 조정(-10% 이하)")

    # 2) 장기 추세(선택한 이동평균선 기준)
    trend = None
    trend_ma = None

    close = df2["Close"].dropna()
    if len(close) >= trend_ma_period:
        trend_ma = float(close.rolling(trend_ma_period).mean().iloc[-1])

    if trend_ma is not None and P is not None:
        if P >= trend_ma:
            trend = "up"
            reasons.append(f"{trend_ma_period}일선 위(추세 유지)")
        else:
            trend = "down"
            reasons.append(f"{trend_ma_period}일선 아래(추세 약화)")

    # 3) 변동성(ATR%)
    atr_pct = None
    vol = None
    if atr is not None and P:
        atr_pct = atr / P
        if atr_pct < 0.02:
            vol = "low"
            reasons.append("변동성 낮음(안정적인 편)")
        elif atr_pct < 0.04:
            vol = "mid"
            reasons.append("변동성 보통")
        else:
            vol = "high"
            reasons.append("변동성 높음(급등락 주의)")

    # ===== 결론 규칙(단순/일관성 우선) =====
    # 기본: 관망
    verdict = "🟡 관망"
    tone = "risk_y"
    guide = "추격 매수보다, 눌림/분할 구간을 기다리는 게 안전해요."

    # 매수 쪽
    if drop is not None and drop <= -(buy_drop_threshold / 100) and trend != "down":
        verdict = "🟢 분할 매수 고려"
        tone = "risk_g"
        guide = "한 번에 사지 말고 1~3차로 나눠서 접근해요."

    # 매도/축소 쪽
    if trend == "down":
        verdict = "🔴 비중 축소/매도 고려"
        tone = "risk_r"
        guide = "장기 추세가 약해져서, 리스크를 먼저 줄이는 게 좋아요."

    # 고점권 + 변동성 높음이면 더 강하게 관망
    if drop is not None and drop >= -0.03 and vol == "high":
        verdict = "🟡 관망(고점권·변동성↑)"
        tone = "risk_y"
        guide = "고점권에서 흔들림이 커서, 눌림 확인 후 접근을 추천해요."

    # 이유는 최대 3개만(초보자용)
    reasons = reasons[:3] if reasons else ["데이터가 부족해 보수적으로 관망을 추천해요."]

    return verdict, tone, guide, reasons


def preset_to_settings(preset: str):
    if preset == "안정형(보수)":
        return {
            "basis": "ATR(변동성)",
            "sell_mode": "추세 이탈 시 축소(이평 이탈)",
            "stages": 0,
            "defense": "20일선",
            "weights": None,
        }
    if preset == "균형형(기본 추천)":
        return {
            "basis": "ATR(변동성)",
            "sell_mode": "단계 익절(추천)",
            "stages": 3,
            "defense": "고점-10%",
            "weights": [30, 30, 40],
        }
    return {
        "basis": "최근고점(H)",
        "sell_mode": "단계 익절(추천)",
        "stages": 3,
        "defense": "60일선",
        "weights": [25, 25, 50],
    }

def pick_defense_line(defense_mode: str, lv: dict):
    if defense_mode == "고점-10%":
        return lv["risk10"]
    if defense_mode == "20일선":
        return lv["ma20"]
    if defense_mode == "60일선":
        return lv["ma60"]
    return lv["risk10"]

def build_sell_targets(lv: dict, basis: str, stages: int, defense_mode: str):
    P = lv["P"]
    H = lv["H"]
    atr = lv["atr14"]
    r1 = lv["r1"]
    r2 = lv["r2"]

    defense = pick_defense_line(defense_mode, lv)
    risk = None
    if defense is not None:
        risk = P - float(defense)

    targets = []

    if basis == "최근고점(H)":
        if stages == 1:
            targets = [H]
        else:
            if atr is not None:
                targets = [H, H + atr, H + 2 * atr]
            else:
                targets = [H, H * 1.03, H * 1.06]

    elif basis == "피벗 R1/R2":
        if r1 is None or r2 is None:
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
                if atr is not None:
                    targets = [r1, r2, r2 + atr]
                else:
                    targets = [r1, r2, r2 * 1.03]

    elif basis == "ATR(변동성)":
        if atr is None:
            targets = [P * 1.03, P * 1.06, P * 1.09]
        else:
            if stages == 1:
                targets = [P + 2 * atr]
            elif stages == 2:
                targets = [P + 1 * atr, P + 2 * atr]
            else:
                targets = [P + 1 * atr, P + 2 * atr, P + 3 * atr]

    elif basis == "R:R(손절 대비)":
        if risk is None or risk <= 0:
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

    targets = targets[:stages]
    targets = [float(t) for t in targets]
    return targets, defense

# =========================
# Favorites (Browser Local Storage)
# =========================
LOCAL_KEY = "fav_codes_v1"
localS = LocalStorage()

def _default_favs():
    return ["000660", "005930"]

def load_favs_from_browser():
    try:
        raw = localS.getItem(LOCAL_KEY, key="fav_get_item")
    except TypeError:
        raw = localS.getItem(LOCAL_KEY)

    if raw is None or raw == "":
        return None
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [str(x).zfill(6) for x in data]
    except:
        return None
    return None

def save_favs_to_browser(codes: list[str]):
    payload = json.dumps([str(c).zfill(6) for c in codes])
    try:
        localS.setItem(LOCAL_KEY, payload, key="fav_set_item")
    except TypeError:
        localS.setItem(LOCAL_KEY, payload)

if "fav_codes" not in st.session_state:
    st.session_state.fav_codes = _default_favs()
if "fav_loaded" not in st.session_state:
    st.session_state.fav_loaded = False
if "fav_pick_code" not in st.session_state:
    st.session_state.fav_pick_code = None

if not st.session_state.fav_loaded:
    loaded = load_favs_from_browser()
    if loaded:
        st.session_state.fav_codes = loaded
    else:
        save_favs_to_browser(st.session_state.fav_codes)
    st.session_state.fav_loaded = True

# =========================
# App UI
# =========================
st.set_page_config(page_title="국장 범용 매수/매도 계산기", layout="centered")
st.title("국장 범용 매수/매도 계산기 (초보자 모드)")

listing = load_krx_listing()
code_to_name = dict(zip(listing["Code"], listing["Name"]))
display_by_code = dict(zip(listing["Code"], listing["Display"]))

# ⭐ Favorites
st.subheader("⭐ 즐겨찾기")
fav_codes_existing = [c for c in st.session_state.fav_codes if c in display_by_code]

if fav_codes_existing:
    cols = st.columns(min(5, len(fav_codes_existing)))
    for i, c in enumerate(fav_codes_existing):
        with cols[i % len(cols)]:
            label = code_to_name.get(c, c)
            if st.button(f"⭐ {label}", use_container_width=True):
                st.session_state.fav_pick_code = c

m1, m2, m3 = st.columns(3)
with m1:
    if st.button("🧹 즐겨찾기 초기화", use_container_width=True):
        st.session_state.fav_codes = _default_favs()
        save_favs_to_browser(st.session_state.fav_codes)
        st.rerun()
with m2:
    if st.button("❌ 즐겨찾기 전체 삭제", use_container_width=True):
        st.session_state.fav_codes = []
        save_favs_to_browser([])
        st.rerun()
with m3:
    if st.button("🔄 브라우저에서 다시 불러오기", use_container_width=True):
        loaded = load_favs_from_browser()
        if loaded is not None:
            st.session_state.fav_codes = loaded
        st.rerun()

st.divider()

# 종목 선택
st.subheader("1) 종목 선택")
picked_code = st.session_state.fav_pick_code
if picked_code and picked_code in display_by_code:
    default_display = display_by_code[picked_code]
else:
    default_code = fav_codes_existing[0] if fav_codes_existing else "000660"
    default_display = display_by_code.get(default_code, listing["Display"].iloc[0])

display_list = listing["Display"].tolist()
default_idx = display_list.index(default_display) if default_display in display_list else 0

selected_display = st.selectbox(
    "종목명을 검색해서 선택하세요",
    options=display_list,
    index=default_idx
)
row = listing[listing["Display"] == selected_display].iloc[0]
code = row["Code"]
name = row["Name"]

f1, f2 = st.columns(2)
with f1:
    if st.button("➕ 즐겨찾기 추가", use_container_width=True):
        if code not in st.session_state.fav_codes:
            st.session_state.fav_codes.append(code)
            save_favs_to_browser(st.session_state.fav_codes)
        st.rerun()
with f2:
    if st.button("🗑️ 즐겨찾기 제거", use_container_width=True):
        if code in st.session_state.fav_codes:
            st.session_state.fav_codes.remove(code)
            save_favs_to_browser(st.session_state.fav_codes)
        st.rerun()

# 프리셋
st.subheader("2) 초보자용 전략 선택(프리셋)")
preset = st.radio(
    "딱 하나만 고르세요 (나머지는 자동 설정됨)",
    ["균형형(기본 추천)", "안정형(보수)", "공격형(수익 추구)"],
    horizontal=True
)
preset_settings = preset_to_settings(preset)

lookback = st.slider("고점/저점 기준 기간(일)", 20, 120, 60)
avg_price = st.number_input("내 평단(원) (선택)", min_value=0, value=0, step=1000)

# 고급 설정(숨김)
# 프리셋 기본값을 먼저 적용
basis = preset_settings["basis"]
sell_mode = preset_settings["sell_mode"]
defense_mode = preset_settings["defense"]

# 고급 설정(원하는 사람만) — expander 안에서 선택하면 덮어쓰기 됩니다.
with st.expander("⚙️ 고급 설정(원하는 사람만)"):
    basis = st.selectbox(
        "목표가 기준",
        ["ATR(변동성)", "최근고점(H)", "피벗 R1/R2", "R:R(손절 대비)"],
        index=["ATR(변동성)", "최근고점(H)", "피벗 R1/R2", "R:R(손절 대비)"].index(basis)
    )
    sell_mode = st.selectbox(
        "매도 방식",
        ["단계 익절(추천)", "목표가 도달 시 전량 익절", "추세 이탈 시 축소(이평 이탈)"],
        index=["단계 익절(추천)", "목표가 도달 시 전량 익절", "추세 이탈 시 축소(이평 이탈)"].index(sell_mode)
    )
    defense_mode = st.selectbox(
        "R:R 방어선(손절 기준)",
        ["고점-10%", "20일선", "60일선"],
        index=["고점-10%", "20일선", "60일선"].index(defense_mode)
    )

run = st.button("계산")

if run:
    with st.spinner("데이터 불러오는 중..."):
        df = load_price(code)

    if df is None or df.empty:
        st.error("데이터를 가져오지 못했어요. 잠시 후 다시 시도해 주세요.")
        st.stop()

    two_years_ago = datetime.now() - timedelta(days=365 * 2)
    df2 = df[df.index >= two_years_ago].copy()
    if df2.empty:
        st.error("최근 2년 데이터가 비어 있어요.")
        st.stop()

    lv = calc_levels(df2, lookback)

    # 초보자 결론
    st.markdown("---")
    st.subheader("✅ 결론(초보자용 한 줄 요약)")

    rg, rg_desc, rg_tone, atr_pct = risk_grade(lv)
    pos = position_summary(lv)

    a, b = st.columns(2)
    with a:
        card("현재 위치", pos, f"기준: 최근고점({lookback}일) + 200일선", "neutral")
    with b:
        card("리스크(변동성)", rg, rg_desc, rg_tone)
        
    # ✅ 의사결정 카드(요약 아래)
    verdict, tone, guide, reasons = decision_engine(
    lv,
    lookback,
    buy_drop_threshold,
    trend_ma_period,
    df2
)

    st.markdown("### 🧭 지금 사도 되나? / 지금 팔아야 되나?")
    card("결론", verdict, guide, tone)

    st.markdown("**이유(간단):**")
    for r in reasons:
        st.markdown(f"- {r}")


    st.subheader(f"📌 {name} ({code})")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("현재가(종가)", krw(lv["P"]))
    m2.metric(f"최근 {lookback}일 고점", krw(lv["H"]))
    m3.metric(f"최근 {lookback}일 저점", krw(lv["L"]))
    trend_text = "데이터 부족"

    close = df2["Close"].dropna()
    trend_ma = None
    if len(close) >= trend_ma_period:
        trend_ma = float(close.rolling(trend_ma_period).mean().iloc[-1])

    if trend_ma is not None and lv["P"] is not None:
    trend_text = f"상승({trend_ma_period}일선 위)" if lv["P"] >= trend_ma else f"주의({trend_ma_period}일선 아래)"

    m4.metric("장기추세", trend_text)

    # 매수
    st.markdown("## ✅ 추천 매수 구간(분할)")
    b1, b2, b3 = st.columns(3)
    with b1:
        card("1차 (-8%)", krw(lv["buy8"]), "고점 × 0.92", "buy")
    with b2:
        card("2차 (-10%)", krw(lv["buy10"]), "고점 × 0.90", "buy")
    with b3:
        card("3차 (-15%)", krw(lv["buy15"]), "고점 × 0.85", "buy")

    # 매도/관리
    st.markdown("## 🎯 매도/관리 가이드(자동 설정)")
    sell_targets = []
    defense_line = None
    weights = preset_settings.get("weights")
    stages = 1 if sell_mode == "목표가 도달 시 전량 익절" else (preset_settings.get("stages", 3) or 3)

    if sell_mode == "추세 이탈 시 축소(이평 이탈)":
        t1, t2, t3 = st.columns(3)
        with t1:
            card("축소 신호(20일선)", krw(lv["ma20"]), "20일선 아래면 비중 점검", "warn")
        with t2:
            card("축소 신호(60일선)", krw(lv["ma60"]), "조정이 깊어질 때 방어", "warn")
        with t3:
            card("최종 방어(200일선)", krw(lv["ma200"]), "장기 추세 붕괴 기준", "warn")
    else:
        sell_targets, defense_line = build_sell_targets(lv, basis, stages, defense_mode)

        if sell_mode == "목표가 도달 시 전량 익절":
            card("전량 익절 목표가", krw(sell_targets[0]), f"기준: {basis}", "sell")
        else:
            cols = st.columns(len(sell_targets))
            for i, tgt in enumerate(sell_targets, start=1):
                w = weights[i-1] if (weights and i-1 < len(weights)) else None
                sub = f"기준: {basis}" + (f" · 비중 {w}%" if w is not None else "")
                with cols[i-1]:
                    card(f"{i}차 목표가", krw(tgt), sub, "sell")

        if defense_line is not None:
            st.caption(f"방어선({defense_mode}): {krw(defense_line)}")

    # =========================
    # 📋 알림 텍스트 생성 + 복사
    # =========================
    st.markdown("## 📋 알림/메모용 텍스트 (복사해서 쓰기)")

    # 선택한 추세 이평선 계산 (알림 텍스트용)
    close = df2["Close"].dropna()
    trend_ma = None
    if len(close) >= trend_ma_period:
        trend_ma = float(close.rolling(trend_ma_period).mean().iloc[-1])

    # 텍스트 만들기
    lines = []
    lines.append(f"[{name}({code})]  |  프리셋: {preset}")
    lines.append(
    f"- 현재가: {krw(lv['P'])} / 최근{lookback}일 고점: {krw(lv['H'])} / {trend_ma_period}일선: {krw(trend_ma)}"
)
    lines.append(f"- 매수: 1차 {krw(lv['buy8'])} / 2차 {krw(lv['buy10'])} / 3차 {krw(lv['buy15'])}")
    if sell_mode == "추세 이탈 시 축소(이평 이탈)":
        lines.append(f"- 관리: 20일선 {krw(lv['ma20'])}, 60일선 {krw(lv['ma60'])}, 200일선 {krw(lv['ma200'])} 이탈 시 점검")
    else:
        if sell_targets:
            if sell_mode == "목표가 도달 시 전량 익절":
                lines.append(f"- 매도(전량): 목표 {krw(sell_targets[0])} (기준: {basis})")
            else:
                # weights가 없을 수도 있으니 안전 처리
                tparts = []
                for i, tgt in enumerate(sell_targets, start=1):
                    w = weights[i-1] if (weights and i-1 < len(weights)) else None
                    if w is None:
                        tparts.append(f"{i}차 {krw(tgt)}")
                    else:
                        tparts.append(f"{i}차 {krw(tgt)}({w}%)")
                lines.append(f"- 매도(분할): " + " / ".join(tparts) + f"  (기준: {basis})")
        if defense_line is not None:
            lines.append(f"- 방어선({defense_mode}): {krw(defense_line)}")

    if avg_price and avg_price > 0:
        lines.append(f"- 내 평단: {krw(avg_price)}")

    memo_text = "\n".join(lines)

    st.text_area("텍스트 미리보기", value=memo_text, height=160)
    copy_to_clipboard_button(memo_text, button_label="📋 한 번에 복사")

    st.caption("※ 복사 버튼이 안 먹으면, 위 텍스트를 길게 눌러 직접 복사해도 됩니다(특히 일부 iOS 환경).")

    # 참고값/차트 (접기)
    with st.expander("📊 참고값/차트 보기(고급)"):
        st.subheader("참고값(세부)")
        detail_rows = [
            ("현재가(종가)", lv["P"]),
            (f"최근 {lookback}일 고점", lv["H"]),
            (f"최근 {lookback}일 저점", lv["L"]),
            ("ATR(14)", lv["atr14"]),
            ("피벗 R1", lv["r1"]),
            ("피벗 R2", lv["r2"]),
            ("20일선", lv["ma20"]),
            ("60일선", lv["ma60"]),
            ("200일선", lv["ma200"]),
        ]
        table_data = [(k, krw(v)) for k, v in detail_rows]
        st.table(pd.DataFrame(table_data, columns=["항목", "값"]))

        st.subheader("최근 2년 차트")
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df2.index, y=df2["Close"], mode="lines", name="종가"))

        close = df2["Close"].dropna().astype(float)
        if len(close) >= 20:
            fig.add_trace(go.Scatter(x=df2.index, y=close.rolling(20).mean(), mode="lines", name="20일선", opacity=0.6))
        if len(close) >= 60:
            fig.add_trace(go.Scatter(x=df2.index, y=close.rolling(60).mean(), mode="lines", name="60일선", opacity=0.6))
        if len(close) >= 200:
            fig.add_trace(go.Scatter(x=df2.index, y=close.rolling(200).mean(), mode="lines", name="200일선", opacity=0.6))

        # 선택한 추세선 강조
        trend_ma = None
        if len(close) >= trend_ma_period:
            trend_ma = float(close.rolling(trend_ma_period).mean().iloc[-1])
            fig.add_trace(
                go.Scatter(
                    x=df2.index,
                    y=close.rolling(trend_ma_period).mean(),
                    mode="lines",
                    name=f"{trend_ma_period}일선(기준)",
                    line=dict(width=4)  # 굵게
                )
            )


        for y, label in [(lv["buy8"], "매수 -8%"), (lv["buy10"], "매수 -10%"), (lv["buy15"], "매수 -15%")]:
            fig.add_hline(y=y, line_dash="dash", annotation_text=label)

        if sell_targets:
            for i, t in enumerate(sell_targets, start=1):
                fig.add_hline(y=t, line_dash="dot", annotation_text=f"목표 {i}")

        fig.update_layout(height=520, margin=dict(l=10, r=10, t=30, b=10))
        st.plotly_chart(fig, use_container_width=True)

    st.caption("※ 본 앱은 과거 가격/이평/변동성 기반 기준값을 계산해 보여주는 도구이며, 투자 판단과 책임은 사용자에게 있습니다.")




