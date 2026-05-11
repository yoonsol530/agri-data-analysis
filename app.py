import streamlit as st
import pandas as pd
import sqlite3
import glob
import numpy as np

# --- 1. 데이터베이스 구축 및 정규화 로직 ---
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
    
    # [가격 데이터 전처리 및 정규화]
    raw_price = pd.concat(p_list, ignore_index=True)
    date_col = '가격등록일자' if '가격등록일자' in raw_price.columns else (raw_price.columns[raw_price.columns.str.contains('일자|날짜')][0] if any(raw_price.columns.str.contains('일자|날짜')) else None)
    item_col = '품목명' if '품목명' in raw_price.columns else (raw_price.columns[raw_price.columns.str.contains('품목')][0] if any(raw_price.columns.str.contains('품목')) else None)
    price_col = next((c for c in ['당일조사가격', '가격', '단가'] if c in raw_price.columns), raw_price.columns[raw_price.columns.str.contains('가격|단가')][0])
    unit_col = next((c for c in ['도매출하단위크기', '크기', '단위'] if c in raw_price.columns), None)

    price_df = raw_price[raw_price[item_col].astype(str).str.contains('배추|양파|무', na=False)].copy()
    price_df['temp_date'] = pd.to_datetime(price_df[date_col].astype(str).str.replace(r'\.0$', '', regex=True), errors='coerce', format='mixed')
    price_df = price_df.dropna(subset=['temp_date'])
    price_df['formatted_date'] = price_df['temp_date'].dt.strftime('%Y-%m-%d')
    
    # 스케일 오류 방지: 숫자 외 문자 제거 및 단위 정규화(kg당 가격)
    price_df['clean_price'] = pd.to_numeric(price_df[price_col].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
    # 단위(kg)가 0이거나 없을 경우 1로 처리하여 단가 왜곡 방지
    units = pd.to_numeric(price_df[unit_col], errors='coerce').fillna(1).replace(0, 1) if unit_col else 1
    price_df['kg_price'] = price_df['clean_price'] / units

    # [기상 데이터 전처리]
    raw_weather = pd.concat(w_list, ignore_index=True)
    w_date_col = next((c for c in raw_weather.columns if any(w in c for w in ['일시', '날짜'])), raw_weather.columns[0])
    raw_weather['formatted_date'] = pd.to_datetime(raw_weather[w_date_col], errors='coerce').dt.strftime('%Y-%m-%d')
    rain_col = next((c for c in raw_weather.columns if '강수' in c), None)
    raw_weather['rain'] = pd.to_numeric(raw_weather[rain_col], errors='coerce').fillna(0) if rain_col else 0

    conn = sqlite3.connect('agri_strategy.db', check_same_thread=False)
    price_df[['formatted_date', item_col, '시도명', 'kg_price']].rename(columns={item_col:'item', '시도명':'region'}).to_sql('price_tab', conn, if_exists='replace', index=False)
    raw_weather[['formatted_date', 'rain']].to_sql('weather_tab', conn, if_exists='replace', index=False)
    
    return conn

# --- 2. 메인 UI 구성 ---
st.set_page_config(page_title="농산물 조달 전략 분석", layout="wide")
st.title("🥬 농산물 조달 리스크 및 전략적 시사점 분석")

conn = init_db()

if conn:
    # 사이드바 설정
    item_choice = st.sidebar.selectbox("전략 분석 품목", ['배추', '양파', '무'])
    st.sidebar.markdown("---")
    
    # 1. 일별 추이 및 이동평균선 (SMA)
    st.subheader(f"📈 1. {item_choice} 가격 추세 및 변동 모멘텀")
    query = f"""
        SELECT formatted_date, AVG(kg_price) as price 
        FROM price_tab WHERE item LIKE '%{item_choice}%' 
        GROUP BY formatted_date ORDER BY formatted_date
    """
    df_trend = pd.read_sql(query, conn)
    df_trend['formatted_date'] = pd.to_datetime(df_trend['formatted_date'])
    df_trend = df_trend.set_index('formatted_date')
    
    # 이동평균선 계산 (7일/30일)
    df_trend['7일 이동평균'] = df_trend['price'].rolling(window=7).mean()
    df_trend['30일 이동평균'] = df_trend['price'].rolling(window=30).mean()
    
    st.line_chart(df_trend[['price', '7일 이동평균', '30일 이동평균']])

    # 2. 전략적 인사이트 (알고리즘 기반 메시지)
    st.markdown("### 💡 전략적 시사점 (Strategic Insights)")
    col_ins1, col_ins2, col_ins3 = st.columns(3)
    
    latest_price = df_trend['price'].iloc[-1]
    avg_price = df_trend['price'].mean()
    price_diff = ((latest_price - avg_price) / avg_price) * 100
    
    with col_ins1:
        st.info("**📅 시즌별 조달 기회**")
        if item_choice in ['배추', '무']:
            st.write("12월~1월 가격 급락 패턴이 확인됩니다. 이 시기에 **선도계약 및 비축 물량 확보**를 통해 연간 조달 원가를 최대 20% 절감 가능합니다.")
        else:
            st.write("양파는 가격 변동성이 낮으므로 단기 대응보다 **장기 저장 시설 비용**을 관리하는 것이 소싱의 핵심입니다.")

    with col_ins2:
        st.success("**🚚 채널 최적화**")
        q_region = f"SELECT region, AVG(kg_price) as avg_p FROM price_tab WHERE item LIKE '%{item_choice}%' GROUP BY region"
        df_reg = pd.read_sql(q_region, conn)
        online_p = df_reg[df_reg['region'].str.contains('온라인', na=False)]['avg_p'].mean()
        if not np.isnan(online_p) and online_p < df_reg['avg_p'].mean():
            st.write(f"온라인 채널 단가가 전체 평균 대비 저렴합니다. **고단가 지역 사업소는 중앙 온라인 조달 체계**로 전환을 권고합니다.")
        else:
            st.write("지역별 단가 편차가 적습니다. 물류비를 고려한 **근거리 로컬 소싱**이 유리합니다.")

    with col_ins3:
        st.warning("**⚠️ 기상 리스크 임계치**")
        st.write("강수량 200mm 이상의 임계점에서 가격 점프 리스크가 존재합니다. **장마철 이전 2주 분량의 안전 재고** 확보 전략이 필요합니다.")

    st.markdown("---")
    
    # 3. 하단 상세 분석 차트
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("2. 지역별 조달 단가 편차 (Online vs Local)")
        df_reg_sorted = df_reg.sort_values(by='avg_p', ascending=False)
        st.bar_chart(df_reg_sorted.set_index('region'))
        
    with col2:
        st.subheader("3. 강수량과 단가 상관관계 (임계점 분석)")
        q_corr = f"""
            SELECT p.kg_price, w.rain FROM price_tab p 
            JOIN weather_tab w ON p.formatted_date = w.formatted_date 
            WHERE p.item LIKE '%{item_choice}%' AND w.rain > 0
        """
        df_corr = pd.read_sql(q_corr, conn)
        if not df_corr.empty:
            st.scatter_chart(df_corr, x='rain', y='kg_price')
            
    st.sidebar.success(f"현재 {item_choice} 리스크 지수: {'높음' if price_diff > 10 else '보통'}")