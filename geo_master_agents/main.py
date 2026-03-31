import uuid

import streamlit as st
from agent import run_geo_agent
from tools import get_global_country_map

st.set_page_config(page_title="지오 마스터 에이전트", layout="wide")

# 세션 초기화 (로그인 유저 ID 임시 발급)
if "messages" not in st.session_state:
    st.session_state.messages = [
        {
            "role": "assistant",
            "content": "안녕하세요! 어떤 국가의 어떤 분야 이슈를 웹툰으로 그려드릴까요?",
        }
    ]
if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())
if "issues" not in st.session_state:
    st.session_state.issues = []
if "waiting_for_user" not in st.session_state:
    st.session_state.waiting_for_user = False

# Streamlit 세션에 user_id가 있다고 가정
if "user_id" not in st.session_state:
    st.session_state.user_id = "guest"


st.title("🌍 글로벌 이슈 웹툰")

# 1. 초기 입력 폼
with st.sidebar:
    st.header("⚙️ 상세 설정")
    domain = st.selectbox(
        "분야", ["economy", "culture", "education", "science", "military"]
    )
    country_input = st.text_input("국가", "한국")
    years = st.number_input("기간(년)", min_value=1, max_value=100, value=10)

    if st.button("대화 초기화"):
        st.session_state.messages = []
        st.session_state.thread_id = str(uuid.uuid4())
        st.rerun()

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

# 2. 기존 대화 기록 출력
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# 3. 사용자 입력 처리
if prompt := st.chat_input("예: 한국의 경제 이슈를 알려줘"):
    # 유저 메시지 표시 및 저장
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # 에이전트 응답 생성
    with st.chat_message("assistant"):
        response_placeholder = st.empty()
        full_response = ""

        # 여기서 run_geo_agent를 호출 (국가명은 prompt에서 추출하거나 별도 로직 필요)
        # 테스트를 위해 간단한 가이드 로직으로 구성
        with st.spinner("에이전트가 생각 중..."):
            input_data = {"country": prompt, "years": years, "domain": domain}

            for event in run_geo_agent(input_data, st.session_state.thread_id):
                if "history_search" in event:
                    issues = event["history_search"]["issue_list"]
                    full_response = (
                        f"🔍 **{prompt}**에 대한 최근 주요 이슈를 찾았습니다:\n\n"
                    )
                    full_response += "\n".join(issues)
                    response_placeholder.markdown(full_response)

                if "__interrupt__" in event:
                    full_response += "\n\n💡 **시각화할 이슈를 위 리스트에서 선택해주세요!** (아래 버튼 활성화)"
                    response_placeholder.markdown(full_response)
                    st.session_state.waiting_for_user = True

        st.session_state.messages.append(
            {"role": "assistant", "content": full_response}
        )

# 4. HITL (Human-in-the-loop) 화면
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
                # 1. 모든 이벤트를 출력해서 어떤 키가 들어오는지 확인 (디버깅용)
                # st.write(event)

                # 2. 노드 이름이 포함되어 있는지 유연하게 체크
                for node_name, output in event.items():
                    if node_name == "cartoon_generation":
                        # 병렬 실행 결과이므로 리스트 형태임
                        final_images = output.get("final_images", [])

                        for res in final_images:
                            if res.get("status") == "success":
                                img_path = res.get("file") or res.get("url")
                                is_cached = res.get("is_cached", False)

                                if img_path:
                                    # 1. UI 구분 (캐시 vs 신규 생성)
                                    if is_cached:
                                        st.info(
                                            f"♻️ **기존 웹툰을 불러왔습니다** -> {res.get('issue')[9:].strip()}"
                                        )
                                    else:
                                        st.success(
                                            f"🎨 **새로운 웹툰이 완성되었습니다** -> {res.get('issue')[9:].strip()}"
                                        )

                                    # 2. 이미지 출력
                                    st.image(img_path)
                                else:
                                    st.error("이미지 경로를 찾을 수 없습니다.")

        with st.spinner("Gemini Flash 3.1 모델이 이미지를 그리고 있습니다..."):
            generate_images()
