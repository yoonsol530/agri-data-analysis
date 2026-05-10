import streamlit as st
import pandas as pd
import sqlite3
import glob

# --- 1. 데이터 처리 로직 ---
def process_data():
    all_files = glob.glob("*.csv")
    p_list, w_list = [], []
    
    for f in all_files:
        try:
            for enc in ['cp949', 'utf-8-sig', 'euc-kr']:
                try:
                    df = pd.read_csv(f, encoding=enc)
                    if not df.empty: break
                except: continue
            if df is None: continue
            
            cols = " ".join(df.columns)
            if '가격등록일자' in df.columns or '품목' in cols:
                p_list.append(df)
            elif any(w in cols for w in ['일시', '기온', '지점', '강수']):
                w_list.append(df)
        except: continue

    if not p_list or not w_list: return None

    raw_price = pd.concat(p_list, ignore_index=True)
    raw_weather = pd.concat(w_list, ignore_index=True)

    # 컬럼 매칭
    date_col = '가격등록일자' if '가격등록일자' in raw_price.columns else (raw_price.columns[raw_price.columns.str.contains('일자|날짜')][0] if any(raw_price.columns.str.contains('일자|날짜')) else None)
    item_col = '품목명' if '품목명' in raw_price.columns else (raw_price.columns[raw_price.columns.str.contains('품목')][0] if any(raw_price.columns.str.contains('품목')) else None)
    price_col = next((c for c in ['당일조사가격', '가격', '단가'] if c in raw_price.columns), raw_price.columns[raw_price.columns.str.contains('가격|단가')][0])

    # --- [중요: 가격 데이터 날짜 처리 강화] ---
    price_df = raw_price[raw_price[item_col].astype(str).str.contains('배추|양파|무', na=False)].copy()
    
    # 날짜 데이터가 숫자로 되어 있는 경우(20240701 등)를 위해 처리
    price_df[date_col] = price_df[date_col].astype(str).str.replace(r'\.0$', '', regex=True) # 소수점 제거
    
    # 여러 형식을 시도하여 날짜 변환
    price_df['temp_date'] = pd.to_datetime(price_df[date_col], errors='coerce')
    
    # 변환 실패(1970년 등)를 막기 위해 숫자로만 된 경우 재시도
    failed_idx = price_df['temp_date'].isna() | (price_df['temp_date'].dt.year == 1970)
    if failed_idx.any():
        price_df.loc[failed_idx, 'temp_date'] = pd.to_datetime(price_df.loc[failed_idx, date_col], format='%Y%m%d', errors='coerce')

    price_df = price_df.dropna(subset=['temp_date'])
    price_df['formatted_date'] = price_df['temp_date'].dt.strftime('%Y-%m-%d')
    price_df['month'] = price_df['temp_date'].dt.month.astype(str).str.zfill(2)
    
    # 가격 숫자화
    price_df['clean_price'] = pd.to_numeric(price_df[price_col].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
    unit_col = next((c for c in ['도매출하단위크기', '크기', '단위'] if c in price_df.columns), None)
    price_df['kg_price'] = price_df['clean_price'] / price_df[unit_col].replace(0, 1) if unit_col else price_df['clean_price']

    # --- [기상 데이터 날짜 처리] ---
    weather_df = raw_weather.copy()
    w_date_col = next((c for c in weather_df.columns if any(w in c for w in ['일시', '날짜'])), weather_df.columns[0])
    weather_df['temp_date'] = pd.to_datetime(weather_df[w_date_col], errors='coerce')
    weather_df = weather_df.dropna(subset=['temp_date'])
    weather_df['formatted_date'] = weather_df['temp_date'].dt.strftime('%Y-%m-%d')
    
    rain_col = next((c for c in weather_df.columns if '강수' in c), None)
    weather_df['rain'] = pd.to_numeric(weather_df[rain_col], errors='coerce').fillna(0) if rain_col else 0

    # DB 저장
    conn = sqlite3.connect('agri_analysis.db')
    price_df[['formatted_date', 'month', item_col, '시도명', 'kg_price']].rename(columns={item_col:'item', '시도명':'region'}).to_sql('price_tab', conn, if_exists='replace', index=False)
    weather_df[['formatted_date', 'rain']].to_sql('weather_tab', conn, if_exists='replace', index=False)
    
    return conn

# --- 2. UI ---
st.set_page_config(page_title="농산물 데이터 분석", layout="wide")
st.title("🥬 농산물 조달 리스크 분석 대시보드")
st.markdown("---")

conn = process_data()

if conn:
    item_choice = st.sidebar.selectbox("대상 품목 선택", ['배추', '양파', '무'])
    
    # 1. 월별 가격 추이
    st.subheader(f"1. {item_choice} 월별 평균 가격 변동")
    q1 = f"SELECT month, AVG(kg_price) as avg_p FROM price_tab WHERE item LIKE '%{item_choice}%' GROUP BY month ORDER BY month"
    df1 = pd.read_sql(q1, conn)
    
    if not df1.empty:
        st.line_chart(df1.set_index('month'))

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("2. 지역별 평균 가격 비교")
        q2 = f"SELECT region, AVG(kg_price) as avg_p FROM price_tab WHERE item LIKE '%{item_choice}%' AND region IS NOT NULL GROUP BY region"
        df2 = pd.read_sql(q2, conn)
        if not df2.empty: st.bar_chart(df2.set_index('region'))

    with c2:
        st.subheader("3. 강수량과 가격 상관 분석")
        q3 = f"""
            SELECT p.kg_price, w.rain 
            FROM price_tab p 
            INNER JOIN weather_tab w ON p.formatted_date = w.formatted_date 
            WHERE p.item LIKE '%{item_choice}%' AND w.rain > 0
        """
        df3 = pd.read_sql(q3, conn)
        if not df3.empty:
            st.scatter_chart(df3, x='rain', y='kg_price')
        else:
            st.warning("⚠️ 날짜가 일치하는 기상 데이터가 없습니다. 기상 파일의 연도를 확인하세요.")

    st.success("✅ 분석 완료")
        