import streamlit as st
import pandas as pd
import sqlite3
import glob
import numpy as np

# --- 1. 데이터베이스 구축 및 Dimension Table 강화 ---
@st.cache_resource
def init_db():
    all_files = glob.glob("*.csv") + glob.glob("*.xlsx")
    p_list, w_list = [], []
    
    for f in all_files:
        try:
            if f.endswith('.csv'):
                for enc in ['cp949', 'utf-8-sig', 'euc-kr']:
                    try:
                        df = pd.read_csv(f, encoding=enc)
                        if not df.empty: break
                    except: continue
            else:
                df = pd.read_excel(f)
            
            cols = " ".join(df.columns.astype(str))
            if '가격등록일자' in df.columns or '품목' in cols:
                p_list.append(df)
            elif any(w in cols for w in ['일시', '기온', '지점', '강수']):
                w_list.append(df)
        except: continue
    
    if not p_list or not w_list: return None
    
    # [Fact: 가격 데이터 전처리]
    raw_price = pd.concat(p_list, ignore_index=True)
    date_col = '가격등록일자' if '가격등록일자' in raw_price.columns else (raw_price.columns[raw_price.columns.str.contains('일자|날짜')][0] if any(raw_price.columns.str.contains('일자|날짜')) else None)
    item_col = '품목명' if '품목명' in raw_price.columns else (raw_price.columns[raw_price.columns.str.contains('품목')][0] if any(raw_price.columns.str.contains('품목')) else None)
    price_col = next((c for c in ['당일조사가격', '가격', '단가'] if c in raw_price.columns), raw_price.columns[raw_price.columns.str.contains('가격|단가')][0])
    unit_col = next((c for c in ['도매출하단위크기', '크기', '단위'] if c in raw_price.columns), None)

    price_df = raw_price[raw_price[item_col].astype(str).str.contains('배추|양파|무', na=False)].copy()
    price_df['temp_date'] = pd.to_datetime(price_df[date_col].astype(str).str.replace(r'\.0$', '', regex=True), errors='coerce', format='mixed')
    price_df = price_df.dropna(subset=['temp_date'])
    price_df['formatted_date'] = price_df['temp_date'].dt.strftime('%Y-%m-%d')
    price_df['clean_price'] = pd.to_numeric(price_df[price_col].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
    units = pd.to_numeric(price_df[unit_col], errors='coerce').fillna(1).replace(0, 1) if unit_col else 1
    price_df['kg_price'] = price_df['clean_price'] / units

    # [Environmental: 기상 데이터 전처리]
    raw_weather = pd.concat(w_list, ignore_index=True)
    w_date_col = next((c for c in raw_weather.columns if any(w in c for w in ['일시', '날짜'])), raw_weather.columns[0])
    raw_weather['formatted_date'] = pd.to_datetime(raw_weather[w_date_col], errors='coerce').dt.strftime('%Y-%m-%d')
    rain_col = next((c for c in raw_weather.columns if '강수' in c), None)
    raw_weather['rain'] = pd.to_numeric(raw_weather[rain_col], errors='coerce').fillna(0) if rain_col else 0

    conn = sqlite3.connect('agri_strategy_v2.db', check_same_thread=False)
    price_df[['formatted_date', item_col, '시도명', 'kg_price']].rename(columns={item_col:'item', '시도명':'region'}).to_sql('price_tab', conn, if_exists='replace', index=False)
    raw_weather[['formatted_date', 'rain']].to_sql('weather_tab', conn, if_exists='replace', index=False)
    
    # [Dimension: 품목 마스터 테이블 (중요!)]
    item_master = pd.DataFrame({
        'item': ['배추', '양파', '무'],
        'category': ['엽채류', '양념채소', '근채류'],
        'storage_type': ['저장성 낮음 (단기 소진)', '저장성 높음 (장기 비축)', '저장성 보통 (수급 조절)'],
        'risk_factor': ['고온다습/무름병', '습도/부패', '강수량/생육 저하'],
        'strategy': ['12월 최저점 대량 소싱', '상시 재고 관리 및 계약재배', '기상 임계점 기반 안전재고']
    })
    item_master.to_sql('item_master', conn, if_exists='replace', index=False)
    
    return conn

# --- 2. 메인 UI ---
st.set_page_config(page_title="농산물 조달 리스크 전략", layout="wide")
st.title("🎯 농산물 조달 리스크 및 전략적 시사점 분석")

conn = init_db()

if conn:
    # 1. 사이드바 - Dimension 정보 활용
    item_list = ['배추', '양파', '무']
    item_choice = st.sidebar.selectbox("전략 분석 품목", item_list)
    
    dim_info = pd.read_sql(f"SELECT * FROM item_master WHERE item = '{item_choice}'", conn).iloc[0]
    
    st.sidebar.markdown(f"### 📋 품목 가이드 ({item_choice})")
    st.sidebar.info(f"**분류:** {dim_info['category']}\n\n**특성:** {dim_info['storage_type']}\n\n**주요 리스크:** {dim_info['risk_factor']}")
    st.sidebar.markdown("---")

    # 2. 상단 핵심 전략 (인사이트 시각화)
    st.markdown(f"### 💡 {item_choice} 핵심 조달 전략")
    col_ins1, col_ins2, col_ins3 = st.columns(3)
    
    with col_ins1:
        st.success(f"**✅ 권고 전략**\n\n{dim_info['strategy']}")
    with col_ins2:
        q_online = f"SELECT AVG(kg_price) as p FROM price_tab WHERE item LIKE '%{item_choice}%' AND region LIKE '%온라인%'"
        online_p = pd.read_sql(q_online, conn)['p'].iloc[0]
        if online_p:
            st.info(f"**🚚 채널 분석**\n\n온라인 단가가 오프라인 대비 유리합니다. 중앙 조달 비중 확대를 제안합니다.")
    with col_ins3:
        st.warning(f"**⚠️ 리스크 관리**\n\n{dim_info['risk_factor']} 리스크가 높으므로 기상 예보 연동 자동 발주가 필요합니다.")

    # 3. 데이터 시각화 (Fact + Dimension Join)
    st.markdown("---")
    st.subheader(f"📈 {item_choice} 가격 추세 및 이동평균 분석")
    query = f"SELECT formatted_date, AVG(kg_price) as price FROM price_tab WHERE item LIKE '%{item_choice}%' GROUP BY formatted_date ORDER BY formatted_date"
    df_trend = pd.read_sql(query, conn)
    df_trend['formatted_date'] = pd.to_datetime(df_trend['formatted_date'])
    df_trend = df_trend.set_index('formatted_date')
    df_trend['7일 이동평균'] = df_trend['price'].rolling(window=7).mean()
    df_trend['30일 이동평균'] = df_trend['price'].rolling(window=30).mean()
    st.line_chart(df_trend)

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("📍 지역별 조달 단가 (Channel Analysis)")
        df_reg = pd.read_sql(f"SELECT region, AVG(kg_price) as avg_p FROM price_tab WHERE item LIKE '%{item_choice}%' GROUP BY region ORDER BY avg_p", conn)
        st.bar_chart(df_reg.set_index('region'))
    with col2:
        st.subheader("⛈ 강수 임계점 리스크 (Env Analysis)")
        df_corr = pd.read_sql(f"SELECT p.kg_price, w.rain FROM price_tab p JOIN weather_tab w ON p.formatted_date = w.formatted_date WHERE p.item LIKE '%{item_choice}%' AND w.rain > 0", conn)
        if not df_corr.empty: st.scatter_chart(df_corr, x='rain', y='kg_price')