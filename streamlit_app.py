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
from bs4 import BeautifulSoup

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
    if atr:
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
def get_naver_news(code):
    try:
        url = f"https://finance.naver.com/item/news_news.naver?code={code}&mode=RANK"
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=5)

        soup = BeautifulSoup(r.text, "html.parser")
        items = soup.select(".title a")[:5]

        news = []
        for item in items:
            title = item.get_text(strip=True)
            link = "https://finance.naver.com" + item["href"]
            news.append((title, link))

        return news
    except:
        return []

def simple_sentiment(text):
    positive_words=["gain","rise","surge","beat","growth","profit","record","strong"]
    negative_words=["fall","drop","loss","weak","decline","cut","miss","risk"]

    score=0
    t=text.lower()
    for w in positive_words:
        if w in t:
            score+=1
    for w in negative_words:
        if w in t:
            score-=1

    if score>0:
        return "🟢 긍정"
    elif score<0:
        return "🔴 부정"
    else:
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

if run:
    df=fdr.DataReader(code)
    df=df[df.index>=datetime.now()-timedelta(days=365*2)]
    close=df["Close"]

    P=float(close.iloc[-1])
    H=float(close.tail(lookback).max())
    L=float(close.tail(lookback).min())

    trend_ma=safe_ma(close,trend_ma_period)
    atr=calc_atr(df)

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

if atr:
    st.write(f"2차 목표(고점+ATR): {krw(H + atr)}")

    if avg_price>0:
        st.subheader("🎯 평단 기준 목표")
        st.write(f"+10%: {krw(avg_price*1.1)}")
        st.write(f"+20%: {krw(avg_price*1.2)}")
        st.write(f"-10%: {krw(avg_price*0.9)}")

    st.subheader("📰 최신 뉴스 + 감성")
    news = get_naver_news(code)
    if news:
        for title,link in news:
            senti=simple_sentiment(title)
            st.markdown(f"**[{title}]({link})**  → {senti}")
    else:
        st.write("뉴스를 불러오지 못했습니다.")

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

