import streamlit as st
import pandas as pd
import sqlite3
import glob
import os

# --- 1. 데이터베이스 구축 로직 ---
@st.cache_resource
def init_db():
    # 1. 파일 검색 (현재 폴더의 모든 엑셀 및 CSV)
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
            
            if df is None: continue
            cols = " ".join(df.columns.astype(str))
            
            # 가격 데이터와 기상 데이터 분류
            if '가격등록일자' in df.columns or '품목' in cols:
                p_list.append(df)
            elif any(w in cols for w in ['일시', '기온', '지점', '강수']):
                w_list.append(df)
        except: continue

    if not p_list or not w_list: return None

    # 데이터 통합
    raw_price = pd.concat(p_list, ignore_index=True)
    raw_weather = pd.concat(w_list, ignore_index=True)

    # [가격 데이터 전처리]
    date_col = '가격등록일자' if '가격등록일자' in raw_price.columns else (raw_price.columns[raw_price.columns.str.contains('일자|날짜')][0] if any(raw_price.columns.str.contains('일자|날짜')) else None)
    item_col = '품목명' if '품목명' in raw_price.columns else (raw_price.columns[raw_price.columns.str.contains('품목')][0] if any(raw_price.columns.str.contains('품목')) else None)
    price_col = next((c for c in ['당일조사가격', '가격', '단가'] if c in raw_price.columns), raw_price.columns[raw_price.columns.str.contains('가격|단가')][0])

    price_df = raw_price[raw_price[item_col].astype(str).str.contains('배추|양파|무', na=False)].copy()
    
    # 날짜 정규화
    price_df[date_col] = price_df[date_col].astype(str).str.replace(r'\.0$', '', regex=True)
    price_df['temp_date'] = pd.to_datetime(price_df[date_col], errors='coerce')
    failed = price_df['temp_date'].isna() | (price_df['temp_date'].dt.year == 1970)
    if failed.any():
        price_df.loc[failed, 'temp_date'] = pd.to_datetime(price_df.loc[failed, date_col], format='%Y%m%d', errors='coerce')

    price_df = price_df.dropna(subset=['temp_date'])
    price_df['formatted_date'] = price_df['temp_date'].dt.strftime('%Y-%m-%d')
    price_df['clean_price'] = pd.to_numeric(price_df[price_col].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
    unit_col = next((c for c in ['도매출하단위크기', '크기', '단위'] if c in price_df.columns), None)
    price_df['kg_price'] = price_df['clean_price'] / price_df[unit_col].replace(0, 1) if unit_col else price_df['clean_price']

    # [기상 데이터 전처리]
    weather_df = raw_weather.copy()
    w_date_col = next((c for c in weather_df.columns if any(w in c for w in ['일시', '날짜'])), weather_df.columns[0])
    weather_df['temp_date'] = pd.to_datetime(weather_df[w_date_col], errors='coerce')
    weather_df = weather_df.dropna(subset=['temp_date'])
    weather_df['formatted_date'] = weather_df['temp_date'].dt.strftime('%Y-%m-%d')
    rain_col = next((c for c in weather_df.columns if '강수' in c), None)
    weather_df['rain'] = pd.to_numeric(weather_df[rain_col], errors='coerce').fillna(0) if rain_col else 0

    # [데이터베이스 구축 - 테이블 3개]
    conn = sqlite3.connect('agri_analysis.db', check_same_thread=False)
    
    # 테이블 1: 가격 정보 (Fact)
    price_df[['formatted_date', item_col, '시도명', 'kg_price']].rename(columns={item_col:'item', '시도명':'region'}).to_sql('price_tab', conn, if_exists='replace', index=False)
    
    # 테이블 2: 기상 정보 (Environmental)
    weather_df[['formatted_date', 'rain']].to_sql('weather_tab', conn, if_exists='replace', index=False)
    
    # 테이블 3: 품목 마스터 (Dimension - 코드 기반 생성)
    item_info = pd.DataFrame({
        'item': ['배추', '양파', '무'],
        'category': ['엽채류', '양념채소', '근채류'],
        'description': ['기후에 민감한 대표 엽채류', '저장성이 강한 양념 채소', '수급 조절이 필요한 주요 근채류']
    })
    item_info.to_sql('item_master', conn, if_exists='replace', index=False)
    
    return conn

# --- 2. 메인 UI ---
st.set_page_config(page_title="농산물 데이터 분석", layout="wide")
st.title("🥬 농산물 조달 리스크 분석 대시보드")

conn = init_db()

if conn:
    item_choice = st.sidebar.selectbox("대상 품목 선택", ['배추', '양파', '무'])
    
    # 품목 마스터 정보 가져오기 (테이블 3 활용)
    item_desc = pd.read_sql(f"SELECT category, description FROM item_master WHERE item = '{item_choice}'", conn)
    if not item_desc.empty:
        st.sidebar.markdown(f"**품목 분류:** {item_desc['category'][0]}")
        st.sidebar.caption(f"**특징:** {item_desc['description'][0]}")

    # [차트 1] 일별 가격 추이 (정밀도 강화)
    st.subheader(f"1. {item_choice} 일별 단가 변동 추이")
    q1 = f"""
        SELECT formatted_date, ROUND(AVG(kg_price), 2) as avg_p 
        FROM price_tab 
        WHERE item LIKE '%{item_choice}%' 
        GROUP BY formatted_date 
        ORDER BY formatted_date
    """
    df1 = pd.read_sql(q1, conn)
    if not df1.empty:
        df1['formatted_date'] = pd.to_datetime(df1['formatted_date'])
        st.line_chart(df1.set_index('formatted_date'), y="avg_p")

    st.markdown("---")
    col1, col2 = st.columns(2)
    
    with col1:
        # [차트 2] 지역별 비교
        st.subheader("2. 지역별 평균 조달 단가 비교")
        q2 = f"SELECT region, ROUND(AVG(kg_price), 2) as avg_p FROM price_tab WHERE item LIKE '%{item_choice}%' GROUP BY region"
        df2 = pd.read_sql(q2, conn)
        if not df2.empty:
            st.bar_chart(df2.set_index('region'))

    with col2:
        # [차트 3] 강수량 상관관계
        st.subheader("3. 강수량과 단가 상관 분석")
        q3 = f"""
            SELECT p.kg_price, w.rain 
            FROM price_tab p 
            JOIN weather_tab w ON p.formatted_date = w.formatted_date 
            WHERE p.item LIKE '%{item_choice}%' AND w.rain > 0
        """
        df3 = pd.read_sql(q3, conn)
        if not df3.empty:
            st.scatter_chart(df3, x='rain', y='kg_price')
        else:
            st.info("강우 시 가격 매칭 데이터가 없습니다.")

    st.sidebar.success("✅ DB 테이블 3개 구축 완료")