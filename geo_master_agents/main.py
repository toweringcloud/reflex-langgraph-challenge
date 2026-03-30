import uuid

import streamlit as st
from agent import run_geo_agent
from tools import get_global_country_map

st.set_page_config(page_title="지오 마스터 에이전트", layout="wide")

# 세션 초기화 (로그인 유저 ID 임시 발급)
if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())
if "issues" not in st.session_state:
    st.session_state.issues = []
if "waiting_for_user" not in st.session_state:
    st.session_state.waiting_for_user = False

# Streamlit 세션에 user_id가 있다고 가정
if "user_id" not in st.session_state:
    st.session_state.user_id = "test_user_999"


st.title("🌍 글로벌 이슈 웹툰")

# 1. 초기 입력 폼
with st.sidebar:
    st.header("설정")
    domain = st.selectbox(
        "분야", ["economy", "culture", "education", "science", "military"]
    )
    country_input = st.text_input("국가", "한국")
    years = st.number_input("기간(년)", min_value=1, max_value=100, value=10)

    if st.button("이슈 검색 시작"):
        st.session_state.waiting_for_user = False
        st.session_state.issues = []

        # 버튼을 누른 순간, 프론트엔드에서 1차 검증 및 치환을 수행합니다!
        country_map = get_global_country_map()
        input_lower = country_input.strip().lower()

        if input_lower not in country_map:
            # 에러 메시지를 띄우고 함수 실행을 멈춤
            st.error(
                "❌ 등록되지 않거나 잘못된 국가명입니다. 정확한 국가명이나 코드를 입력해주세요."
            )
        else:
            # 정상적인 경우, 공식 명칭으로 치환해서 백엔드(agent)로 넘김!
            target_country = country_map[input_lower]

            input_data = {
                "country": target_country,  # 치환된 영문 명칭
                "years": years,
                "domain": domain,
            }

            # 비동기 루프 실행 래퍼
            def fetch_issues():
                for event in run_geo_agent(
                    input_data, st.session_state.thread_id, st.session_state.user_id
                ):
                    if "history_search" in event:
                        st.session_state.issues = event["history_search"]["issue_list"]
                    if "__interrupt__" in event:
                        st.session_state.waiting_for_user = True

            with st.spinner("Tavily 검색 및 LLM 분석 중..."):
                fetch_issues()

# 2. HITL (Human-in-the-loop) 화면
if st.session_state.waiting_for_user and st.session_state.issues:
    st.subheader("💡 시각화할 이슈를 선택하세요")

    # 여러 개 선택 가능한 체크박스 렌더링
    selected_indices = []
    for idx, issue in enumerate(st.session_state.issues):
        if st.checkbox(issue, key=f"issue_{idx}"):
            selected_indices.append(idx)

    if st.button("선택한 이슈로 웹툰 생성"):
        st.session_state.waiting_for_user = False  # 상태 초기화

        def generate_images():
            # 사용자가 선택한 인덱스를 resume으로 전달
            for event in run_geo_agent(
                {},
                st.session_state.thread_id,
                st.session_state.user_id,
                resume_data=selected_indices,
            ):
                if "cartoon_generation" in event:
                    res = event["cartoon_generation"]["final_images"][0]
                    if res["status"] == "success":
                        st.success(f"생성 완료: {res['issue']}")
                        # 🚨 디버깅용: 실제 URL이 어떻게 나오는지 화면에 찍어봅니다.
                        st.write(f"DEBUG 이미지 주소: {res['file']}")
                        st.image(res["file"])  # R2에서 발급된 URL 렌더링

        with st.spinner("Gemini Flash 3.1 모델이 이미지를 그리고 있습니다..."):
            generate_images()
