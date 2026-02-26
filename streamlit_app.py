# ==============================
# 국장 범용 매수/매도 계산기 3.0
# ==============================

import json
from datetime import datetime, timedelta
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components
from streamlit_local_storage import LocalStorage
import FinanceDataReader as fdr
import requests
import xml.etree.ElementTree as ET
from urllib.parse import quote
from email.utils import parsedate_to_datetime

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

# ------------------------------
# 종목 점수 계산
# ------------------------------
def calc_score(df, P, H, trend_ma, atr):
    score = 0
    details = []

    # 1️⃣ 장기추세 (25점)
    if trend_ma and P >= trend_ma:
        score += 25
        details.append("장기추세 +25")

    # 2️⃣ 조정폭 (25점)
    drop = (P/H)-1
    if -0.15 <= drop <= -0.08:
        score += 25
        details.append("적정 조정 +25")
    elif drop < -0.15:
        score += 15
        details.append("과도 조정 +15")

    # 3️⃣ 변동성 (15점)
    if atr is not None:
        atr_pct = atr/P
        if atr_pct < 0.02:
            score += 15
            details.append("낮은 변동성 +15")
        elif atr_pct < 0.04:
            score += 10
            details.append("보통 변동성 +10")

    # 4️⃣ 1개월 수익률 (20점)
    close = df["Close"]
    if len(close)>22:
        ret1 = (close.iloc[-1]/close.iloc[-22])-1
        if ret1>0:
            score+=20
            details.append("1개월 상승 +20")

    # 5️⃣ 3개월 수익률 (15점)
    if len(close)>66:
        ret3 = (close.iloc[-1]/close.iloc[-66])-1
        if ret3>0:
            score+=15
            details.append("3개월 상승 +15")

    return min(score,100), details

# ------------------------------
# Decision Engine
# ------------------------------
def decision_engine(P,H,trend_ma,drop_threshold):
    drop=(P/H)-1
    verdict="🟡 관망"
    guide="추격보다 눌림 대기"

    if trend_ma and P<trend_ma:
        verdict="🔴 비중 축소 고려"
        guide="추세선 이탈"
    elif drop<=-(drop_threshold/100):
        verdict="🟢 분할 매수 고려"
        guide="조정 구간"
    elif drop>=-0.03:
        verdict="🟡 고점권 주의"
        guide="추격 매수 위험"

    return verdict,guide

# ------------------------------
# 뉴스 + 감성
# ------------------------------
def _parse_rss_items(xml_bytes, limit=6, max_age_days=7):
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

        # 날짜 필터
        try:
            dt = parsedate_to_datetime(pub).replace(tzinfo=None)
            if (now - dt).days > max_age_days:
                continue
        except:
            # 날짜 파싱 실패하면 그냥 제외(오래된거 섞이는거 방지)
            continue

        if title and link:
            out.append((title, link, pub))
        if len(out) >= limit:
            break

    return out


def get_google_news_rss(query, limit=6):
    # 한국/한국어 뉴스 위주
    # 참고: q에 회사명 + 종목코드 같이 넣으면 검색정확도가 올라감
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


def get_yahoo_rss(ticker_with_suffix, limit=6):
    url = f"https://finance.yahoo.com/rss/headline?s={ticker_with_suffix}"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, headers=headers, timeout=6)
        if r.status_code != 200:
            return []
        return _parse_rss_items(r.content, limit=limit)
    except:
        return []


def get_free_news(code, name, market=None, limit=6):
    # 1) Google News RSS: 회사명 + 코드 (가장 잘 뜸)
    q1 = f"{name} {code} 주가"
    news = get_google_news_rss(q1, limit=limit)
    if news:
        return "Google News", news

    # 2) Google News RSS: 회사명만
    q2 = f"{name} 주식"
    news = get_google_news_rss(q2, limit=limit)
    if news:
        return "Google News", news

    # 3) (옵션) Yahoo RSS: KOSPI/KOSDAQ 구분 못하면 .KS 먼저 시도
    # market이 있으면 더 정확히 할 수 있음
    suffixes = []
    if market:
        # KOSPI/KOSDAQ
        if "KOSDAQ" in str(market).upper():
            suffixes = [".KQ", ".KS"]
        else:
            suffixes = [".KS", ".KQ"]
    else:
        suffixes = [".KS", ".KQ"]

    for sfx in suffixes:
        news = get_yahoo_rss(code + sfx, limit=limit)
        if news:
            return "Yahoo Finance", news

    return None, []

def simple_sentiment(title: str):
    t = (title or "").lower()

    pos = [
        # EN
        "gain","rise","surge","beat","growth","profit","record","strong","upgrade",
        # KR
        "호재","상승","급등","강세","최고","신고가","돌파","개선","흑자","호황","수혜",
        "기대","확대","성장","증가","상향"
    ]
    neg = [
        # EN
        "fall","drop","loss","weak","decline","cut","miss","risk","downgrade",
        # KR
        "악재","하락","급락","약세","최저","신저가","부진","적자","우려","경고","충격",
        "감소","축소","하향","리스크","불확실"
    ]

    score = 0
    for w in pos:
        if w in t:
            score += 1
    for w in neg:
        if w in t:
            score -= 1

    if score > 0:
        return "🟢 긍정"
    if score < 0:
        return "🔴 부정"
    return "🟡 중립"

# ------------------------------
# UI 시작
# ------------------------------
st.set_page_config(page_title="국장 분석툴 3.0",layout="centered")
st.title("📊 국장 분석툴 3.0")

listing=fdr.StockListing("KRX")
listing["Code"]=listing["Code"].astype(str).str.zfill(6)
listing["Display"]=listing["Name"]+" ("+listing["Code"]+")"

selected=st.selectbox("종목 선택",listing["Display"])
row=listing[listing["Display"]==selected].iloc[0]
code=row["Code"]
name=row["Name"]

lookback=st.slider("고점 기준 기간",20,120,60)
drop_threshold=st.slider("매수 판단 기준(-%)",5,20,8)
trend_ma_period=st.selectbox("추세 기준 이평선",[200,120,60])
avg_price=st.number_input("내 평단(선택)",min_value=0,value=0,step=1000)

run=st.button("계산")

P = None
H = None
trend_ma = None
atr = None

if run:
    df = fdr.DataReader(code)
    df = df[df.index >= datetime.now() - timedelta(days=365*2)]

    close = df["Close"]
    P = float(close.iloc[-1])
    H = float(close.tail(lookback).max())
    L = float(close.tail(lookback).min())

    trend_ma = safe_ma(close, trend_ma_period)
    atr = calc_atr(df)   # ← 이 줄 반드시 있어야 함

    verdict,guide=decision_engine(P,H,trend_ma,drop_threshold)

    st.subheader("📌 결론")
    st.write(f"### {verdict} - {guide}")

    st.subheader("📊 종목 점수")
    score,details=calc_score(df,P,H,trend_ma,atr)

    if score>=75:
        st.success(f"{score} / 100")
    elif score>=50:
        st.warning(f"{score} / 100")
    else:
        st.error(f"{score} / 100")

    with st.expander("점수 계산 방식 보기"):
        for d in details:
            st.write("•",d)

    st.subheader("📈 매수 기준")
    st.write(f"1차: {krw(H*0.92)}")
    st.write(f"2차: {krw(H*0.90)}")
    st.write(f"3차: {krw(H*0.85)}")

    st.subheader("📉 매도 기준")

    if trend_ma:
        st.write(f"손절(추세 이탈): {krw(trend_ma)}")
    else:
        st.write("손절: 추세선 데이터 부족")

    st.write(f"1차 목표(최근 고점): {krw(H)}")

if atr is not None:
    st.write(f"2차 목표(고점+ATR): {krw(H + atr)}")

    if avg_price>0:
        st.subheader("🎯 평단 기준 목표")
        st.write(f"+10%: {krw(avg_price*1.1)}")
        st.write(f"+20%: {krw(avg_price*1.2)}")
        st.write(f"-10%: {krw(avg_price*0.9)}")

    st.subheader("📰 최신 뉴스 + 감성")

    # market 정보 있으면 더 좋음 (listing에서 row["Market"]로 전달)
    source, news = get_free_news(code=code, name=name, market=row.get("Market", None), limit=6)

    if news:
        st.caption(f"출처: {source} · 최근 기사 {len(news)}개")
        for title, link, pub in news:
            senti = simple_sentiment(title)
            st.markdown(f"**[{title}]({link})**  → {senti}")
            if pub:
                st.caption(pub)
    else:
        st.info("뉴스를 불러오지 못했습니다. (무료 RSS도 가끔 막히거나 지연될 수 있어요)")

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




