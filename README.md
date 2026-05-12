# agri-data-analysis
프로젝트 제목: 🥬 농산물 조달 리스크 분석 대시보드

사이트 주소: https://agri-data-analysis-vw9h8xpkaupwrkokqjkswb.streamlit.app/
GitHub 주소:
프롬프트 링크: https://gemini.google.com/share/3119462bd907

1. 프로젝트 개요

기획 의도: 기후 변화에 민감한 농산물의 가격 형성 메커니즘을 데이터로 이해하고, 조달 리스크를 최소화하는 의사결정 지원 도구를 구축함.

분석 대상: 배추(엽채류), 양파(양념채소), 무(근채류).

품목 선정 이유: 기상 변화에 민감한 엽채류(배추)와 수급 조절이 용이한 저장 채소(양파)의 가격 형성 메커니즘 차이를 비교 분석하기 위해 선정함.

주요 기술: Python, Pandas, SQLite3, Streamlit.

2. 데이터 및 클린징 과정 (3개 테이블 구축)
데이터 출처: 공공데이터포털 농산물 가격 데이터 및 기상청 전국 강수량 데이터 활용.

-구축된 테이블 (3-Tier)
price_tab (Fact Table): 전국 도매시장별 품목 단가 데이터.

weather_tab (Environmental Table): 일별 전국 평균 강수량 관측 데이터.

item_master (Dimension Table): 품목별 카테고리(엽채류, 양념채소 등) 및 저장성 특성을 정의한 기준 정보 테이블.

-데이터 클린징 및 전처리 과정
단위 표준화: 콤마(,) 제거 및 수치형 변환, 품목별로 상이한 유통 규격을 kg당 단가로 산출하여 통계적 왜곡을 방지함.

날짜 포맷 정규화 (Troubleshooting): 엑셀의 정수형 날짜 데이터가 Epoch Time(1970-01-01)으로 오인되는 결함을 발견하여 pd.to_datetime 로직을 정교화해 복구함.

데이터 정밀도 강화: 변동 폭이 좁은 품목(양파 등) 분석을 위해 SQL의 ROUND 함수 및 소수점 처리를 강화하여 분석 정밀도를 높임.

시스템 최적화: st.cache_resource를 도입하여 DB 연결을 캐싱함으로써 품목 변경 시 즉각적인 반응 속도를 구현함.


3. 시각화 결과 및 인사이트 (3개 차트 구성)
차트 1: 가격 추세 및 변동 모멘텀
사용 SQL: SELECT formatted_date, AVG(kg_price) FROM price_tab WHERE item LIKE '%{item}%' GROUP BY formatted_date ORDER BY formatted_date

설명: 단기(7일)/장기(30일) 이동평균선을 결합하여 중장기 시세 흐름과 변동성을 시각화함.

인사이트: 배추는 12월 말 공급 쇼크 후 1월 급락 패턴이 반복됨을 확인. 연말 직전 선도계약 체결이 조달 안정성의 핵심임을 도출함. 채널 최적화: 배추의 경우 연말/연초 온라인 가격 역전 현상을 발견, 해당 시기 로컬 산지 직거래 비중 확대 전략 도출. 기상에 민감한 배추에 비해, 양파는 '저장 농산물'로서 매우 안정적인 가격 추이를 보임을 데이터로 확인.

차트 2: 지역별 조달 단가 편차
사용 SQL: SELECT region, AVG(kg_price) FROM price_tab WHERE item LIKE '%{item}%' GROUP BY region

설명: 산지별, 그리고 온라인 채널 간의 단가 편차를 막대 차트로 비교함.

인사이트: 양파와 같이 지역 간 가격 편차가 미미한(CV < 0.05) 품목은 산지 다변화보다 물량 통합 발주(Volume Pooling)를 통한 협상력 강화가 유리함을 확인.

차트 3: 강수량-단가 상관 분석
사용 SQL: SELECT p.kg_price, w.rain FROM price_tab p JOIN weather_tab w ON p.formatted_date = w.formatted_date WHERE p.item LIKE '%{item}%' AND w.rain > 0

설명: 기상 요인(강수량)과 조달 단가 사이의 통계적 상관성을 산점도로 표현함.

인사이트: 강수량과 단가 사이의 정(+)의 상관관계가 높은 품목의 경우, 기상 예보 시 선제적으로 2주 분량의 안전 재고를 확보해야 한다는 리스크 대응 근거를 마련함.


우리의 밥상에 식재료가 오르기까지, 그 이면에 숨겨진 데이터의 흐름을 읽고 최적의 조달 타이밍을 찾는 것이 본 프로젝트의 목표입니다. 기상 변화와 과거의 가격 패턴을 결합하여, 리스크는 줄이고 효율은 높이는 '조달 전략'을 제시하고자 했습니다.

