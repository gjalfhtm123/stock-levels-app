# ==============================
# 국장 범용 매수/매도 계산기 3.2 (즐겨찾기+UI강조+자동배지+뉴스감성+점수)
# ==============================

import json
from datetime import datetime, timedelta
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import FinanceDataReader as fdr
import requests
import xml.etree.ElementTree as ET
from urllib.parse import quote
from email.utils import parsedate_to_datetime

from streamlit_local_storage import LocalStorage  # ⭐ 즐겨찾기 저장용

# ------------------------------
# 유틸
# ------------------------------
def krw(x):
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

def big_box(title, lines, tone="neutral"):
    styles = {
        "neutral": ("#f3f4f6", "#111827", "#e5e7eb"),
        "buy": ("#ecfdf5", "#065f46", "#a7f3d0"),
        "sell": ("#fff7ed", "#9a3412", "#fdba74"),
        "warn": ("#fffbeb", "#92400e", "#fde68a"),
        "risk": ("#fef2f2", "#991b1b", "#fecaca"),
    }
    bg, fg, bd = styles.get(tone, styles["neutral"])
    html_lines = "".join([f"<div style='margin:6px 0; font-size:18px;'><b>{l}</b></div>" for l in lines])

    st.markdown(
        f"""
        <div style="background:{bg}; border:2px solid {bd}; padding:18px; border-radius:18px; margin:12px 0;">
          <div style="font-size:16px; color:{fg}; opacity:0.9; margin-bottom:8px;"><b>{title}</b></div>
          {html_lines}
        </div>
        """,
        unsafe_allow_html=True
    )

def near(a, b, pct=0.01):
    if a is None or b is None or b == 0:
        return False
    return abs(a - b) / b <= pct

# ------------------------------
# 종목 점수 계산
# ------------------------------
def calc_score(df, P, H, trend_ma, atr):
    score = 0
    details = []

    if trend_ma and P >= trend_ma:
        score += 25
        details.append("장기추세: 현재가가 선택 이평선 위면 +25")

    drop = (P/H)-1
    if -0.15 <= drop <= -0.08:
        score += 25
        details.append("조정폭: 고점 대비 -8%~-15%면 +25")
    elif drop < -0.15:
        score += 15
        details.append("조정폭: -15%보다 더 빠지면 +15(과도조정)")

    if atr is not None:
        atr_pct = atr/P
        if atr_pct < 0.02:
            score += 15
            details.append("변동성: ATR% < 2%면 +15")
        elif atr_pct < 0.04:
            score += 10
            details.append("변동성: ATR% < 4%면 +10")
        else:
            score += 5
            details.append("변동성: ATR% >= 4%면 +5")

    close = df["Close"]
    if len(close) > 22:
        ret1 = (close.iloc[-1]/close.iloc[-22]) - 1
        if ret1 > 0:
            score += 20
            details.append("모멘텀(1개월): 최근 1개월 수익률이 +면 +20")

    if len(close) > 66:
        ret3 = (close.iloc[-1]/close.iloc[-66]) - 1
        if ret3 > 0:
            score += 15
            details.append("모멘텀(3개월): 최근 3개월 수익률이 +면 +15")

    return min(score, 100), details

# ------------------------------
# Decision Engine
# ------------------------------
def decision_engine(P, H, trend_ma, drop_threshold):
    drop = (P/H) - 1
    verdict = "🟡 관망"
    guide = "추격보다 눌림 대기"

    if trend_ma and P < trend_ma:
        verdict = "🔴 비중 축소 고려"
        guide = "추세선 이탈"
    elif drop <= -(drop_threshold/100):
        verdict = "🟢 분할 매수 고려"
        guide = "조정 구간"
    elif drop >= -0.03:
        verdict = "🟡 고점권 주의"
        guide = "추격 매수 위험"

    return verdict, guide

# ------------------------------
# 뉴스 + 감성
# ------------------------------
def _parse_rss_items(xml_bytes, limit=6, max_age_days=3):
    root = ET.fromstring(xml_bytes)
    out = []
    now = datetime.now()

    for item in root.findall(".//item"):
        title_el = item.find("title")
        link_el = item.find("link")
        pub_el = item.find("pubDate")

        title = title_el.text if title_el is not None else ""
        link = link_el.text if link_el is not None else ""
        pub  = pub_el.text  if pub_el is not None else ""

        try:
            dt = parsedate_to_datetime(pub).replace(tzinfo=None)
            if (now - dt).days > max_age_days:
                continue
        except:
            continue

        if title and link:
            out.append((title, link, pub))
        if len(out) >= limit:
            break

    return out

def get_google_news_rss(query, limit=6):
    q = quote(query + " when:3d")
    url = f"https://news.google.com/rss/search?q={q}&hl=ko&gl=KR&ceid=KR:ko"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, headers=headers, timeout=6)
        if r.status_code != 200:
            return []
        return _parse_rss_items(r.content, limit=limit, max_age_days=3)
    except:
        return []

def get_free_news(code, name, limit=6):
    q1 = f"{name} {code} 주가"
    news = get_google_news_rss(q1, limit=limit)
    if news:
        return "Google News", news

    q2 = f"{name} 주식"
    news = get_google_news_rss(q2, limit=limit)
    if news:
        return "Google News", news

    return None, []

def simple_sentiment(title: str):
    t = (title or "").lower()
    pos = [
        "gain","rise","surge","beat","growth","profit","record","strong","upgrade",
        "호재","상승","급등","강세","최고","신고가","돌파","개선","흑자","호황","수혜",
        "기대","확대","성장","증가","상향"
    ]
    neg = [
        "fall","drop","loss","weak","decline","cut","miss","risk","downgrade",
        "악재","하락","급락","약세","최저","신저가","부진","적자","우려","경고","충격",
        "감소","축소","하향","리스크","불확실"
    ]

    s = 0
    for w in pos:
        if w in t:
            s += 1
    for w in neg:
        if w in t:
            s -= 1

    if s > 0:
        return "🟢 긍정"
    if s < 0:
        return "🔴 부정"
    return "🟡 중립"

# ------------------------------
# 즐겨찾기(LocalStorage)
# ------------------------------
LOCAL_KEY = "fav_codes_v4"
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

# ------------------------------
# UI 시작
# ------------------------------
st.set_page_config(page_title="국장 분석툴 3.2", layout="centered")
st.title("📊 국장 분석툴 3.2")

@st.cache_data(ttl=60*60*6)  # 6시간 캐시(일시 장애에도 버팀)
def load_krx_listing():
    df = fdr.StockListing("KRX")  # 여기서 가끔 JSONDecodeError 남
    df["Code"] = df["Code"].astype(str).str.zfill(6)
    df["Display"] = df["Name"] + " (" + df["Code"] + ")"
    return df

def fallback_listing():
    # 최소한 앱이 뜨도록 기본 몇 종목만 제공(즐겨찾기용)
    df = pd.DataFrame({
        "Name": ["삼성전자", "SK하이닉스", "NAVER", "카카오", "LG에너지솔루션"],
        "Code": ["005930", "000660", "035420", "035720", "373220"],
    })
    df["Display"] = df["Name"] + " (" + df["Code"] + ")"
    return df

try:
    listing = load_krx_listing()
except Exception as e:
    st.warning("KRX 종목 목록을 불러오지 못해요(일시적). 기본 목록으로 실행합니다.")
    listing = fallback_listing()

# 세션 즐겨찾기 초기화
if "favs" not in st.session_state:
    st.session_state.favs = load_favs()

# ⭐ 즐겨찾기 버튼 영역
st.subheader("⭐ 즐겨찾기")
if st.session_state.favs:
    cols = st.columns(min(6, len(st.session_state.favs)))
    for i, c in enumerate(st.session_state.favs):
        name_ = listing.loc[listing["Code"] == c, "Name"]
        label = name_.iloc[0] if not name_.empty else c
        with cols[i]:
            if st.button(label):
                st.session_state["picked"] = c

# 기본 선택값(즐겨찾기에서 눌렀으면 그거)
default_code = st.session_state.get("picked", st.session_state.favs[0] if st.session_state.favs else listing["Code"].iloc[0])
default_display = listing.loc[listing["Code"] == default_code, "Display"]
default_display = default_display.iloc[0] if not default_display.empty else listing["Display"].iloc[0]

selected = st.selectbox(
    "종목 선택",
    listing["Display"],
    index=listing["Display"].tolist().index(default_display)
)

row = listing[listing["Display"] == selected].iloc[0]
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

lookback = st.slider("고점 기준 기간", 20, 120, 60)
drop_threshold = st.slider("매수 판단 기준(-%)", 5, 20, 8)
trend_ma_period = st.selectbox("추세 기준 이평선", [200, 120, 60])
avg_price = st.number_input("내 평단(선택)", min_value=0, value=0, step=1000)

run = st.button("계산")

# 안전 초기화
P = H = L = trend_ma = atr = None

if run:
    df = fdr.DataReader(code)
    df = df[df.index >= datetime.now() - timedelta(days=365 * 2)]
    close = df["Close"]

    P = float(close.iloc[-1])
    H = float(close.tail(lookback).max())
    L = float(close.tail(lookback).min())

    trend_ma = safe_ma(close, trend_ma_period)
    atr = calc_atr(df)

    verdict, guide = decision_engine(P, H, trend_ma, drop_threshold)

    st.subheader("📌 결론")
    st.write(f"### {verdict} - {guide}")

    # 점수
    st.subheader("📊 종목 점수")
    score, details = calc_score(df, P, H, trend_ma, atr)
    if score >= 75:
        st.success(f"{score} / 100")
    elif score >= 50:
        st.warning(f"{score} / 100")
    else:
        st.error(f"{score} / 100")

    with st.expander("점수 계산 방식 보기"):
        for d in details:
            st.write("•", d)

    # 기준값
    buy1 = H * 0.92
    buy2 = H * 0.90
    buy3 = H * 0.85

    tp1 = H
    tp2 = (H + atr) if atr is not None else None
    stop_trend = trend_ma
    stop_avg = (avg_price * 0.90) if avg_price and avg_price > 0 else None

    # 자동 배지(매수)
    buy_badge = None
    if P <= buy3:
        buy_badge = "✅ 지금 매수 가능(3차 구간)"
    elif P <= buy2:
        buy_badge = "✅ 지금 매수 가능(2차 구간)"
    elif P <= buy1:
        buy_badge = "✅ 지금 매수 가능(1차 구간)"
    else:
        if near(P, buy1, 0.01):
            buy_badge = "🟡 1차 매수선 근접(1% 이내)"

    # 자동 배지(매도/리스크)
    sell_badge = None
    if stop_trend is not None:
        if P < stop_trend:
            sell_badge = "🔴 추세선 이탈(리스크 매우 큼)"
        elif near(P, stop_trend, 0.01):
            sell_badge = "🟠 추세선 근접(1% 이내)"

    if sell_badge is None:
        if P >= tp1:
            sell_badge = "🟠 1차 목표가 도달(분할 매도 고려)"
        elif tp2 is not None and P >= tp2:
            sell_badge = "🟠 2차 목표가 도달(강한 매도 구간)"
        elif near(P, tp1, 0.01):
            sell_badge = "🟡 1차 목표가 근접(1% 이내)"

    # 매수 카드
    st.subheader("📈 매수 기준 (추천 구간)")
    buy_lines = [
        f"1차 (-8%): {krw(buy1)}   (고점×0.92)",
        f"2차 (-10%): {krw(buy2)}  (고점×0.90)",
        f"3차 (-15%): {krw(buy3)}  (고점×0.85)",
    ]
    if buy_badge:
        buy_lines.insert(0, buy_badge)
    big_box("✅ 추천 매수 구간 (분할)", buy_lines, tone="buy")

    # 매도 카드
    st.subheader("📉 매도 기준 (목표/리스크)")
    sell_lines = [
        f"1차 목표(최근 고점): {krw(tp1)}",
        f"2차 목표(고점+ATR): {krw(tp2)}" if tp2 is not None else "2차 목표(고점+ATR): ATR 데이터 부족",
        f"손절(추세 이탈): {krw(stop_trend)}" if stop_trend is not None else "손절(추세 이탈): 추세선 데이터 부족",
    ]
    if stop_avg is not None:
        sell_lines.append(f"손절(평단-10%): {krw(stop_avg)}")
    if sell_badge:
        sell_lines.insert(0, sell_badge)

    sell_tone = "sell"
    if "🔴" in verdict or (stop_trend is not None and P < stop_trend):
        sell_tone = "risk"
    big_box("🛡️ 추천 매도/리스크 구간", sell_lines, tone=sell_tone)

    # 참고 표
    st.subheader("📌 참고값(세부)")
    ref = pd.DataFrame([
        ("현재가(종가)", krw(P)),
        (f"최근 {lookback}일 고점", krw(H)),
        (f"최근 {lookback}일 저점", krw(L)),
        (f"{trend_ma_period}일선", krw(trend_ma)),
        ("ATR(14)", krw(atr) if atr is not None else "—"),
    ], columns=["항목", "값"])
    st.table(ref)

    # 평단 목표
    if avg_price > 0:
        st.subheader("🎯 평단 기준 목표")
        c1,c2,c3,c4 = st.columns(4)
        c1.metric("+10%", krw(avg_price*1.1))
        c2.metric("+20%", krw(avg_price*1.2))
        c3.metric("-10%", krw(avg_price*0.9))
        c4.metric("-15%", krw(avg_price*0.85))

    # 뉴스
    st.subheader("📰 최신 뉴스 + 감성")
    source, news = get_free_news(code=code, name=name, limit=6)
    if news:
        st.caption(f"출처: {source} · 최근 3일 기사 {len(news)}개")
        for title, link, pub in news:
            senti = simple_sentiment(title)
            st.markdown(f"**[{title}]({link})**  → {senti}")
            if pub:
                st.caption(pub)
    else:
        st.info("뉴스를 불러오지 못했습니다. (무료 RSS도 가끔 막히거나 지연될 수 있어요)")

    # 차트
    st.subheader("📉 차트")
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df.index, y=close, name="종가"))
    if trend_ma is not None:
        fig.add_trace(go.Scatter(
            x=df.index,
            y=close.rolling(trend_ma_period).mean(),
            name=f"{trend_ma_period}일선",
            line=dict(width=4)
        ))
    fig.update_layout(height=500)
    st.plotly_chart(fig, use_container_width=True)

