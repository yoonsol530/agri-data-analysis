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
                for enc in ['utf-8-sig', 'cp949', 'euc-kr']:
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
    
    # [데이터 처리] 가격 데이터 통합 및 전처리
    raw_price = pd.concat(p_list, ignore_index=True)
    item_col = '품목명' if '품목명' in raw_price.columns else (raw_price.columns[raw_price.columns.str.contains('품목')][0])
    price_col = next((c for c in ['당일조사가격', '가격', '단가'] if c in raw_price.columns), raw_price.columns[raw_price.columns.str.contains('가격|단가')][0])
    unit_col = next((c for c in ['도매출하단위크기', '크기', '단위'] if c in raw_price.columns), None)

    price_df = raw_price[raw_price[item_col].astype(str).str.contains('배추|양파|무', na=False)].copy()
    price_df['temp_date'] = pd.to_datetime(price_df['가격등록일자'].astype(str).str.replace(r'\.0$', '', regex=True), errors='coerce', format='mixed')
    price_df = price_df.dropna(subset=['temp_date'])
    price_df['formatted_date'] = price_df['temp_date'].dt.strftime('%Y-%m-%d')
    
    price_df['clean_price'] = pd.to_numeric(price_df[price_col].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
    units = pd.to_numeric(price_df[unit_col], errors='coerce').fillna(1).replace(0, 1) if unit_col else 1
    price_df['kg_price'] = price_df['clean_price'] / units

    # [데이터 처리] 기상 데이터 통합
    raw_weather = pd.concat(w_list, ignore_index=True)
    w_date_col = next((c for c in raw_weather.columns if any(w in c for w in ['일시', '날짜'])), raw_weather.columns[0])
    raw_weather['formatted_date'] = pd.to_datetime(raw_weather[w_date_col], errors='coerce').dt.strftime('%Y-%m-%d')
    rain_col = next((c for c in raw_weather.columns if '강수' in c), '강수량')
    raw_weather['rain'] = pd.to_numeric(raw_weather[rain_col], errors='coerce').fillna(0) if rain_col in raw_weather.columns else 0

    # [DB 저장]
    conn = sqlite3.connect('agri_strategy.db', check_same_thread=False)
    price_df[['formatted_date', item_col, '시도명', 'kg_price']].rename(columns={item_col:'item', '시도명':'region'}).to_sql('price_tab', conn, if_exists='replace', index=False)
    raw_weather[['formatted_date', 'rain']].to_sql('weather_tab', conn, if_exists='replace', index=False)
    
    # --- 추가: 품목 마스터 테이블 (Dimension) 생성 ---
    item_info = pd.DataFrame({
        'item': ['배추', '양파', '무'],
        'category': ['엽채류', '양념채소', '근채류'],
        'description': ['기후에 민감한 대표 엽채류', '저장성이 강한 양념 채소', '수급 조절이 필요한 주요 근채류']
    })
    item_info.to_sql('item_master', conn, if_exists='replace', index=False)
    
    return conn

# --- 2. 메인 UI 구성 ---
st.set_page_config(page_title="농산물 조달 전략 분석", layout="wide")
st.title("🥬 농산물 조달 리스크 및 전략적 시사점 분석")

conn = init_db()

if conn:
    item_choice = st.sidebar.selectbox("전략 분석 품목", ['배추', '양파', '무'])
    
    # 품목 마스터 정보 가져오기
    item_meta = pd.read_sql(f"SELECT * FROM item_master WHERE item = '{item_choice}'", conn).iloc[0]
    st.sidebar.info(f"**분류:** {item_meta['category']}\n\n**특징:** {item_meta['description']}")
    st.sidebar.markdown("---")
    
    # 데이터 로드
    df_trend = pd.read_sql(f"SELECT formatted_date, AVG(kg_price) as price FROM price_tab WHERE item LIKE '%{item_choice}%' GROUP BY formatted_date ORDER BY formatted_date", conn)
    df_trend['formatted_date'] = pd.to_datetime(df_trend['formatted_date'])
    df_trend = df_trend.set_index('formatted_date')
    df_trend['7일 이동평균'] = df_trend['price'].rolling(window=7).mean()
    df_trend['30일 이동평균'] = df_trend['price'].rolling(window=30).mean()

    df_reg = pd.read_sql(f"SELECT region, AVG(kg_price) as avg_p FROM price_tab WHERE item LIKE '%{item_choice}%' GROUP BY region", conn)
    df_corr = pd.read_sql(f"SELECT p.kg_price, w.rain FROM price_tab p JOIN weather_tab w ON p.formatted_date = w.formatted_date WHERE p.item LIKE '%{item_choice}%' AND w.rain > 0", conn)

    # 기본 통계
    hist_avg = df_trend['price'].mean()
    hist_std = df_trend['price'].std()
    current_p = df_trend['price'].iloc[-1]
    st.sidebar.metric(f"{item_choice} 리스크", "분석 완료", f"{((current_p-hist_avg)/hist_avg)*100:.1f}%")

    # 1. 가격 추세 차트
    st.subheader(f"📈 1. {item_choice} 가격 추세 및 변동 모멘텀")
    st.line_chart(df_trend[['price', '7일 이동평균', '30일 이동평균']])

    # 2. 전략적 시사점
    st.markdown("### 💡 전략적 시사점 (Strategic Insights)")
    col_ins1, col_ins2, col_ins3 = st.columns(3)
    
    with col_ins1:
        st.info("**📅 조달 타이밍 전략**")
        if '배추' in item_choice:
            st.write("12월 말 공급 쇼크 후 1월 가격 급락 패턴이 확인됩니다. **연말 직전 선도계약**이 조달 안정성의 핵심입니다.")
        else:
            volatility = (hist_std / hist_avg) if hist_avg > 0 else 0
            st.write(f"시세 변동성({volatility:.1%}) 기반의 **재고 회전율 최적화** 전략이 유효합니다.")

    with col_ins2:
        st.success("**🚚 공급망 최적화 전략**")
        is_online = df_reg['region'].str.contains('온라인', na=False)
        df_local = df_reg[~is_online]
        local_avg = df_local['avg_p'].mean() if not df_local.empty else 0
        online_p = df_reg[is_online]['avg_p'].mean() if any(is_online) else np.nan
        local_cv = (df_local['avg_p'].std() / local_avg) if local_avg > 0 else 0

        if not np.isnan(online_p) and online_p > local_avg * 1.1:
            st.error(f"⚠️ **온라인 가격 역전 발생**")
            st.write("온라인 소싱을 축소하고 **로컬 산지 직거래 비중**을 확대하세요.")
        elif local_cv < 0.05:
            st.info("📍 **지역 간 가격 평단화 감지**")
            st.write("지역 간 편차가 미미하므로 **물량 통합 발주**를 통한 협상력 강화에 집중하세요.")
        else:
            st.write("지역별 단가 편차를 활용한 **Sourcing Mix 최적화**가 필요합니다.")

    with col_ins3:
        st.warning("**⚠️ 외부 리스크 대응**")
        corr_val = df_corr.corr().iloc[0, 1] if not df_corr.empty else 0
        if corr_val > 0.3:
            st.write(f"기상 민감도({corr_val:.2f})가 높습니다. 강수 예보 시 선제적 재고 확보를 권고합니다.")
        else:
            st.write("계절적 수급 불균형 및 유통 리스크 관리에 집중하십시오.")

    st.markdown("---")
    
    # 3. 하단 차트
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("2. 지역별 조달 단가 편차")
        st.bar_chart(df_reg.sort_values('avg_p', ascending=False).set_index('region'))
    with c2:
        st.subheader("3. 강수량-단가 상관 분석")
        if not df_corr.empty:
            st.scatter_chart(df_corr, x='rain', y='kg_price')