import uuid

import streamlit as st
from agent import run_geo_agent
from tools import get_global_country_map

st.set_page_config(page_title="지오 마스터 에이전트", layout="wide")


def show_starter_guide():
    st.session_state.messages = [
        {
            "role": "assistant",
            "content": """
                안녕하세요! 어떤 국가의 어떤 분야 이슈가 궁금하세요?
                - 사이드 바 : 분야 (경제/문화/교육/과학/방산) 선택 -> 국가 입력 -> 기간 선택 -> 이슈 검색 시작 -> Top 5 이슈 조회 -> 이슈 선택 -> 웹툰 생성
                - 챗 입력창 : 분야와 국가 입력 (예: 한국의 최근 30년 경제 이슈를 알려줘) -> 엔터 -> Top 5 이슈 조회 -> 이슈 선택 -> 웹툰 생성
            """,
        }
    ]


# 세션 초기화
if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())
if "user_id" not in st.session_state:
    st.session_state.user_id = "guest"
if "waiting_for_user" not in st.session_state:
    st.session_state.waiting_for_user = False
if "is_processing" not in st.session_state:
    st.session_state.is_processing = False
if "start_search" not in st.session_state:
    st.session_state.start_search = False
if "start_generation" not in st.session_state:
    st.session_state.start_generation = False
if "selected_indices" not in st.session_state:
    st.session_state.selected_indices = []
if "issues" not in st.session_state:
    st.session_state.issues = []
if "messages" not in st.session_state:
    show_starter_guide()


st.title("🌍 글로벌 이슈 웹툰")


# 1. 초기 입력 폼
with st.sidebar:
    st.header("⚙️ 상세 설정")

    # Label과 Value를 매핑할 딕셔너리 생성 (원하는 이모지도 넣을 수 있습니다!)
    domain_mapping = {
        "economy": "💰 경제 (Economy)",
        "culture": "🎭 문화 (Culture)",
        "education": "📚 교육 (Education)",
        "science": "🔬 과학 (Science)",
        "military": "⚔️ 방산 (Military)",
    }

    # selectbox에 format_func 적용
    domain = st.selectbox(
        "관심 분야",
        options=list(
            domain_mapping.keys()
        ),  # 👈 실제 코드가 쓸 값 (economy, culture...)
        format_func=lambda x: domain_mapping[x],  # 👈 화면에 보여줄 값 매핑
        disabled=st.session_state.is_processing,
    )
    country_input = st.text_input(
        "대상 국가",
        "한국",
        disabled=st.session_state.is_processing,
    )
    years = st.number_input(
        "검색 기간(년)",
        min_value=1,
        max_value=100,
        value=10,
        disabled=st.session_state.is_processing,
    )

    if st.button(
        "이슈 검색 시작",
        use_container_width=True,
        disabled=st.session_state.is_processing,
    ):
        # 상태 변경 및 검색 트리거 활성화
        st.session_state.thread_id = str(uuid.uuid4())
        st.session_state.is_processing = True
        st.session_state.start_search = True
        st.session_state.waiting_for_user = False
        st.session_state.issues = []
        st.rerun()

    if st.button(
        "대화 초기화",
        use_container_width=True,
        disabled=st.session_state.is_processing,
    ):
        st.session_state.thread_id = str(uuid.uuid4())
        st.session_state.selected_indices = []
        st.session_state.issues = []
        show_starter_guide()
        st.rerun()

    # 비동기 루프 실행 래퍼
    def fetch_issues():
        for event in run_geo_agent(
            input_data, st.session_state.thread_id, st.session_state.user_id
        ):
            if "history_search" in event:
                # st.session_state.issues = event["history_search"]["issue_list"]
                search_result = event.get("history_search", {})
                found_issues = search_result.get("issue_list", [])
                st.session_state.issues = found_issues

            if "__interrupt__" in event:
                st.session_state.waiting_for_user = True

    if st.session_state.start_search:
        # 버튼을 누른 순간, 프론트엔드에서 1차 검증 및 치환을 수행합니다!
        country_map = get_global_country_map()
        input_lower = country_input.strip().lower()

        if input_lower in country_map:
            # 정상적인 경우, 공식 명칭으로 치환해서 백엔드(agent)로 넘김!
            target_country = country_map[input_lower]

            input_data = {
                "country": target_country,  # 치환된 영문 명칭
                "years": years,
                "domain": domain,
            }

            with st.spinner("Tavily 검색 및 LLM 분석 중..."):
                fetch_issues()
        else:
            # 에러 메시지를 띄우고 함수 실행을 멈춤
            st.error(
                "❌ 등록되지 않거나 잘못된 국가명입니다. 정확한 국가명이나 코드를 입력해주세요."
            )

        # 작업 완료 후 상태 복구 및 리런
        st.session_state.is_processing = False
        st.session_state.start_search = False
        st.rerun()


# 2. 기존 대화 기록 출력
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        if message.get("type") == "image":
            if message.get("is_cached"):
                st.info(f"♻️ **기존 웹툰을 불러왔습니다** -> {message['title']}")
            else:
                st.success(f"🎨 **새로운 웹툰이 완성되었습니다** -> {message['title']}")
            st.image(message["path"])

        elif message.get("type") == "warning":
            st.warning(f"⚠️ **생성 지연:** {message['title']}\n\n{message['content']}")

        elif message.get("type") == "error":
            st.error(message["content"])

        else:
            st.markdown(message["content"])


# 3. 사용자 입력 처리
if prompt := st.chat_input(
    "예: 한국의 경제 이슈를 알려줘", disabled=st.session_state.is_processing
):
    st.session_state.thread_id = str(uuid.uuid4())

    # 유저 메시지 표시 및 저장
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # 에이전트 응답 생성
    with st.chat_message("assistant"):
        response_placeholder = st.empty()
        full_response = ""

        # 여기서 run_geo_agent를 호출 (classify_user_intent_node에서 country 추출)
        with st.spinner("에이전트가 생각 중..."):
            input_data = {
                "messages": [("user", prompt)],  # LangChain 메시지 형식
                "years": years,
                "domain": domain,
            }

            for event in run_geo_agent(input_data, st.session_state.thread_id):
                if "history_search" in event:
                    result_data = event["history_search"]

                    # 정상적으로 이슈 리스트가 돌아온 경우
                    if "issue_list" in result_data:
                        issues = result_data["issue_list"]

                        # 🚨 에이전트가 찾은 이슈를 세션에 저장
                        st.session_state.issues = issues

                        full_response = (
                            f"🔍 **{prompt}**에 대한 최근 주요 이슈를 찾았습니다:\n\n"
                        )
                        full_response += "\n".join(issues)
                        response_placeholder.markdown(full_response)

                    # 국가 정보가 부족해 에러 메시지가 돌아온 경우
                    elif "messages" in result_data:
                        error_msg = result_data["messages"][0][1]  # 에러 텍스트 추출
                        response_placeholder.markdown(f"⚠️ {error_msg}")
                        # 이 경우 interrupt가 발생하지 않으므로 여기서 루프 통과

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
        if st.checkbox(
            issue, key=f"issue_{idx}", disabled=st.session_state.is_processing
        ):
            selected_indices.append(idx)

    if st.button("선택한 이슈로 웹툰 생성", disabled=st.session_state.start_generation):
        st.session_state.selected_indices = selected_indices  # 선택한 값 저장
        st.session_state.is_processing = True  # 전체 UI 잠금
        st.session_state.start_generation = True  # 생성 트리거 ON
        st.session_state.waiting_for_user = False  # 대기 상태 해제
        st.rerun()


def generate_images():
    # 🚨 실시간 출력을 위한 빈 공간 컨테이너 생성
    realtime_container = st.container()

    # 사용자가 선택한 인덱스를 resume으로 전달
    for event in run_geo_agent(
        {},
        st.session_state.thread_id,
        st.session_state.user_id,
        resume_data=st.session_state.selected_indices,
    ):
        # 1. 모든 이벤트를 출력해서 어떤 키가 들어오는지 확인 (디버깅용)
        # st.write(event)

        # 2. 노드 이름이 포함되어 있는지 유연하게 체크
        for node_name, output in event.items():
            if node_name == "cartoon_generation":
                # 병렬 실행 결과이므로 리스트 형태임
                final_images = output.get("final_images", [])

                for res in final_images:
                    issue_title = (
                        res.get("issue")[9:].strip()
                        if res.get("issue")
                        else "알 수 없는 이슈"
                    )

                    # ✅ 1. 성공 시, 기존 로직 그대로 처리
                    if res.get("status") == "success":
                        img_path = res.get("file") or res.get("url")
                        is_cached = res.get("is_cached", False)

                        if img_path:
                            # 영구 보관용 세션 저장
                            st.session_state.messages.append(
                                {
                                    "role": "assistant",
                                    "type": "image",
                                    "is_cached": is_cached,
                                    "title": issue_title,
                                    "path": img_path,
                                }
                            )
                            # 사용자 피드백용 실시간 화면 출력
                            with realtime_container:
                                if is_cached:
                                    st.info(f"♻️ **기존 웹툰 (캐시):** {issue_title}")
                                else:
                                    st.success(f"🎨 **새로운 웹툰:** {issue_title}")
                                st.image(img_path)
                        else:
                            st.session_state.messages.append(
                                {
                                    "role": "assistant",
                                    "type": "error",
                                    "content": "이미지 경로를 찾을 수 없습니다.",
                                }
                            )

                    # 🚨 2. 실패 시, Warning 노출 로직 추가!
                    else:
                        error_message = (
                            res.get("text") or "알 수 없는 오류가 발생했습니다."
                        )
                        st.session_state.messages.append(
                            {
                                "role": "assistant",
                                "type": "warning",
                                "title": issue_title,
                                "content": error_message,
                            }
                        )


if st.session_state.start_generation:
    with st.spinner("Gemini Flash 3.1 모델이 이미지를 그리고 있습니다..."):
        generate_images()

    # 🚨 작업 완료 후, 상태 복구 및 리런하여 UI 잠금 해제
    st.session_state.is_processing = False
    st.session_state.start_generation = False
    st.rerun()
