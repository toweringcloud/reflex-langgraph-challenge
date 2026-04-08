import base64
import os
import uuid

import pandas as pd
import pydeck as pdk
import requests
import streamlit as st
import streamlit.components.v1 as components
from agent import run_geo_agent
from tools import get_domain_keyword, get_global_country_map
from utils import GEO_ALIASES_REVERSE

st.set_page_config(page_title="지오 마스터 플러스", layout="wide")


@st.cache_data(ttl=3600)  # 1시간 동안 데이터를 캐싱(임시 저장)하여 재다운로드 방지
def fetch_geo_data():
    """세계 지도와 지진 데이터를 안전하게 불러옵니다."""
    # 🚨 반드시 raw 데이터를 반환하는 주소를 사용해야 합니다.
    worldmap_url = "https://raw.githubusercontent.com/datasets/geo-boundaries-world-110m/master/countries.geojson"
    earthquake_url = (
        "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_week.geojson"
    )

    data_world = requests.get(worldmap_url).json()
    data_earthquake = requests.get(earthquake_url).json()

    return data_world, data_earthquake


def render_global_earthquake_map():
    # 세걔 지도 데이터 로딩
    with st.spinner("실시간 지오 데이터 로드 중..."):
        try:
            data_world, data_earthquake = fetch_geo_data()
        except Exception:
            # 🚨 에러가 발생하면 지도를 그리지 않고 조용히 안내 문구만 띄움
            st.info("⚠️ 현재 실시간 지진 데이터를 불러올 수 없어 지도를 생략합니다.")
            return

    # 지진 GeoJSON을 Pydeck용 DataFrame으로 변환
    features = data_earthquake["features"]
    earthquake_data = []
    for f in features:
        coords = f["geometry"]["coordinates"]
        props = f["properties"]
        earthquake_data.append(
            {
                "lon": coords[0],
                "lat": coords[1],
                "mag": props["mag"],  # 지진 강도
                "place": props["place"],  # 발생 장소
                "time": pd.to_datetime(props["time"], unit="ms").strftime(
                    "%Y-%m-%d %H:%M"
                ),  # 시간 가공
            }
        )
    df_earthquake = pd.DataFrame(earthquake_data)

    # [Pydeck 레이어 설정]

    # 레이어 1: 밑바탕이 되는 세계지도 (GeoJsonLayer)
    base_map_layer = pdk.Layer(
        "GeoJsonLayer",
        data_world,
        opacity=0.4,  # 바탕 지도는 투명하게
        stroked=True,
        filled=True,
        get_fill_color=[200, 200, 200, 100],  # 연한 회색 바탕
        get_line_color=[255, 255, 255, 150],  # 흰색 경계선
        line_width_min_pixels=1,
        pickable=False,  # 바탕 지도는 클릭 불가
    )

    # 레이어 2: 그 위에 세울 3D 지진 기둥 (ColumnLayer)
    earthquake_column_layer = pdk.Layer(
        "ColumnLayer",
        df_earthquake,
        get_position="[lon, lat]",
        get_elevation="mag * mag * 10000",  # 강도의 제곱에 비례해 높이 설정 (시각적 강조)
        elevation_scale=1,
        radius=30000,  # 기둥 두께
        get_fill_color=[255, "mag * 40", 0, 200],  # 강도가 셀수록 붉은색으로 변함
        pickable=True,  # 👈 클릭(Pick) 이벤트 활성화
        auto_highlight=True,
    )

    # 지도를 40도 기울여 3D 기둥이 잘 보이게 설정
    # view_state = pdk.ViewState(latitude=20, longitude=0, zoom=1.2, pitch=40)

    # 대화형 툴팁 설정 (장소, 강도, 시간 표시)
    tooltip_content = {
        "html": "<b>장소:</b> {place}<br/><b>강도:</b> {mag}<br/><b>시간:</b> {time}",
        "style": {
            "background": "rgba(0,0,0,0.8)",
            "color": "white",
            "border-radius": "8px",
            "padding": "10px",
        },
    }

    # 고정된 view_state 대신 세션 상태에 저장된 값을 사용합니다.
    r = pdk.Deck(
        layers=[base_map_layer, earthquake_column_layer],
        initial_view_state=st.session_state.map_view_state,  # ✅ 동적 업데이트 반영
        tooltip=tooltip_content,
        map_provider="carto",  # 깔끔한 지도 스타일 적용
        map_style="light",
    )

    # Streamlit 화면에 렌더링
    st.pydeck_chart(r)


def show_global_map():
    # 1. 지도를 그립니다. (샘플 테스트)
    with st.container():
        render_global_earthquake_map()

    # 2. (향후 과제) 지도를 클릭했을 때 에이전트 작동시키기
    # st.pydeck_chart는 클릭된 객체의 정보를 반환할 수 있습니다.
    # 이를 활용해 사용자가 지진 기둥을 클릭하면,
    # 'sidebar_country' 세션 값을 해당 지역 국가로 업데이트하고
    # 에이전트 검색을 자동 트리거하는 로직을 붙여보세요.


def show_starter_guide():
    st.session_state.messages = [
        {
            "role": "assistant",
            "content": """
                안녕하세요! 어떤 국가의 어떤 분야 이슈가 궁금하세요?
                - 사이드 바 : 국가 명을 입력하고, 분야(경제/문화/교육/과학/방산)와 기간을 선택해 주세요.
                - 챗 입력창 : 국가 + 분야 + 기간(옵셔널임, 기본값: 10년)을 포함하여 입력해 주세요.
                - 지도 모드 : 아래의 지도를 클릭하면 해당 국가의 분야별 검색 이력을 확인할 수 있어요! (Comming Soon)
            """,
        },
        # 안내 문구 바로 아래에 지도를 띄우기 위한 특수 메시지 추가!
        {"role": "assistant", "type": "map"},
    ]


def get_image_base64(img_path):
    """로컬 이미지를 HTML에서 띄우기 위해 Base64로 변환하거나 URL을 그대로 반환합니다."""
    if not img_path:
        return ""
    if img_path.startswith("http"):  # 웹 URL인 경우 그대로 반환
        return img_path
    elif os.path.exists(img_path):  # 로컬 파일인 경우 Base64 인코딩
        with open(img_path, "rb") as f:
            data = f.read()
        return f"data:image/jpeg;base64,{base64.b64encode(data).decode()}"
    return ""


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
if "country_input" not in st.session_state:
    st.session_state.country_input = ""
if "selected_indices" not in st.session_state:
    st.session_state.selected_indices = []
if "issues" not in st.session_state:
    st.session_state.issues = []
if "messages" not in st.session_state:
    show_starter_guide()

# 세션 초기화 (사이드바와 챗입력창 동기화)
if "sidebar_domain" not in st.session_state:
    st.session_state.sidebar_domain = "economy"
if "sidebar_country" not in st.session_state:
    st.session_state.sidebar_country = "한국"
if "sidebar_years" not in st.session_state:
    st.session_state.sidebar_years = 10

# 앱이 리런될 때마다 이 기본값으로 초기화되지 않고 유지됩니다.
if "map_view_state" not in st.session_state:
    st.session_state.map_view_state = pdk.ViewState(
        latitude=36.5, longitude=127.5, zoom=6, pitch=45
    )

# 하단에서 올라온 업데이트 명령을 최상단에서 적용!
if "pending_updates" in st.session_state:
    for key, value in st.session_state.pending_updates.items():
        st.session_state[key] = value
    del st.session_state.pending_updates


st.title("🌍 Geo Master Plus")

# 1. 초기 입력 폼
with st.sidebar:
    st.header("⚙️ 사이드바 이슈 검색")

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
        options=list(domain_mapping.keys()),
        format_func=lambda x: domain_mapping[x],
        key="sidebar_domain",  # 👈 위젯 전용 내부 키
        disabled=st.session_state.is_processing,
    )

    # Text input은 초기값을 value로 주입합니다.
    country_input = st.text_input(
        "대상 국가",
        key="sidebar_country",
        disabled=st.session_state.is_processing,
    )

    # Number input도 초기값을 value로 주입합니다.
    years = st.number_input(
        "검색 기간(년)",
        min_value=10,
        max_value=100,
        key="sidebar_years",
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
    def fetch_issues(payload: dict):
        for event in run_geo_agent(
            input_data, st.session_state.thread_id, st.session_state.user_id
        ):
            if "history_search" in event:
                search_result = event.get("history_search", {})
                found_issues = search_result.get("issue_list", [])
                st.session_state.issues = found_issues

                target_info = f"{payload['country_input']}의 {get_domain_keyword(payload['domain'])} 이슈"
                full_response = (
                    f"🔍 **{target_info}**에 대한 히스토리 분석 결과입니다:\n\n"
                )
                full_response += "\n".join(found_issues)

                st.session_state.messages.append(
                    {"role": "assistant", "content": full_response}
                )

            if "__interrupt__" in event:
                st.session_state.waiting_for_user = True

    if st.session_state.start_search:
        # 버튼을 누른 순간, 프론트엔드에서 1차 검증 및 치환을 수행합니다!
        country_map = get_global_country_map()
        user_input = country_input.strip().lower()

        if user_input in country_map:
            # 정상적인 경우, 공식 명칭으로 치환해서 백엔드(agent)로 넘김!
            coords = country_map[user_input]

            # 사이드바에서 검색할 때도 지도가 해당 국가로 줌인되도록!
            st.session_state.map_view_state = pdk.ViewState(
                latitude=coords["lat"],
                longitude=coords["lon"],
                zoom=coords["zoom"],
                pitch=45,
            )

            input_data = {
                "country_input": country_input,  # 유저가 입력한 원본 텍스트
                "country": coords["name"],  # 치환된 영문 명칭
                "years": years,
                "domain": domain,
            }

            with st.spinner("Tavily 검색 및 LLM 분석 중..."):
                fetch_issues(payload=input_data)
        else:
            # 에러 메시지를 띄우고 함수 실행을 멈춤
            st.session_state.messages.append(
                {
                    "role": "assistant",
                    "type": "error",
                    "content": "등록되지 않거나 잘못된 국가명입니다. 정확한 국가명(예: 대한민국)과 관심 분야(경제/문화/교육/과학/방산)를 입력해주세요.",
                }
            )
            st.rerun()  # 에러 메시지 띄우고 즉시 종료

        # 작업 완료 후 상태 복구 및 리런
        st.session_state.is_processing = False
        st.session_state.start_search = False
        st.rerun()


# 2. 기존 대화 기록 출력
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        if message.get("type") == "image":
            if message.get("is_cached"):
                st.info(f"♻️ **기존 웹툰을 불러왔습니다**\n\n{message['title']}")
            else:
                st.success(f"🎨 **새로운 웹툰이 완성되었습니다**\n\n{message['title']}")
            st.image(message["path"])

        elif message.get("type") == "map":
            render_global_earthquake_map()

        elif message.get("type") == "warning":
            st.warning(f"⚠️ {message['content']}\n\n{message['title']}")

        elif message.get("type") == "error":
            st.error(f"🚨 {message['content']}")

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
        with st.spinner("Tavily 검색 및 LLM 분석 중..."):
            input_data = {
                "messages": [("user", prompt)],  # LangChain 메시지 형식
                "years": years,
                "domain": domain,
            }

            for event in run_geo_agent(
                input_data, st.session_state.thread_id, st.session_state.user_id
            ):
                # 의도 분석 결과가 나오면 사이드바 값을 즉시 업데이트!
                if "intent_classify" in event:
                    intent_data = event["intent_classify"]

                    # 🚨 사용자가 엉뚱한 말을 해서 국가가 추출되지 않은 경우
                    raw_country = intent_data.get("country", "").strip()
                    if not raw_country or raw_country.lower() in [
                        "unknown",
                        "none",
                        "null",
                    ]:
                        st.session_state.messages.append(
                            {
                                "role": "assistant",
                                "type": "error",
                                "content": "등록되지 않거나 잘못된 국가명입니다. 정확한 국가명(예: 대한민국)과 관심 분야(경제/문화/교육/과학/방산)를 입력해주세요.",
                            }
                        )
                        st.rerun()  # 에러 메시지 띄우고 즉시 종료

                    # 정상 추출 시 바구니(pending_updates)에 담기
                    updates = {}

                    if "domain" in intent_data:
                        updates["sidebar_domain"] = intent_data["domain"]

                    if "years" in intent_data:
                        updates["sidebar_years"] = intent_data["years"]

                    if "country" in intent_data:
                        raw_country = intent_data["country"]
                        display_country = GEO_ALIASES_REVERSE.get(
                            raw_country, raw_country
                        )
                        updates["sidebar_country"] = display_country

                        # 지도 좌표 업데이트를 위해 국가명으로 검색
                        country_map = get_global_country_map()
                        search_key = raw_country.strip().lower()

                        if search_key in country_map:
                            coords = country_map[search_key]

                            # 세션의 뷰 상태를 해당 국가 좌표로 교체!
                            st.session_state.map_view_state = pdk.ViewState(
                                latitude=coords["lat"],
                                longitude=coords["lon"],
                                zoom=coords["zoom"],
                                pitch=45,
                            )

                    # 바구니를 통째로 세션에 저장!
                    if updates:
                        st.session_state.pending_updates = updates

                if "history_search" in event:
                    result_data = event["history_search"]

                    # 정상적으로 이슈 리스트가 돌아온 경우
                    if "issue_list" in result_data:
                        issues = result_data["issue_list"]
                        st.session_state.issues = issues

                        full_response = (
                            f"🔍 **{prompt}**에 대한 히스토리 분석 결과입니다:\n\n"
                        )
                        full_response += "\n".join(issues)
                        response_placeholder.markdown(full_response)

                    # 🚨 국가 정보가 부족해 LLM이 폴백(Fallback) 메시지를 뱉은 경우
                    elif "messages" in result_data:
                        # 기존의 LLM 자유 응답(error_msg) 대신, 통일된 규격 에러 메시지로 덮어씌움!
                        st.session_state.messages.append(
                            {
                                "role": "assistant",
                                "type": "error",
                                "content": "등록되지 않거나 잘못된 국가명입니다. 정확한 국가명(예: 대한민국)과 이슈 관심 분야(경제/문화/교육/과학/방산)를 입력해주세요.",
                            }
                        )
                        st.rerun()  # 에러 메시지 띄우고 즉시 종료

                if "__interrupt__" in event:
                    st.session_state.waiting_for_user = True

        st.session_state.messages.append(
            {"role": "assistant", "content": full_response}
        )
        st.rerun()

# 4. HITL (Human-in-the-loop) 화면

# 잔상(Ghosting) 제거를 위한 특수 빈 컨테이너 생성
hitl_placeholder = st.empty()

# 생성 트리거(start_generation)가 켜져 있을 때는 메뉴판을 아예 숨깁니다!
if (
    st.session_state.waiting_for_user
    and st.session_state.issues
    and not st.session_state.start_generation
):
    with hitl_placeholder.container():
        st.subheader("💡 시각화할 이슈를 선택하세요")

        # 여러 개 선택 가능한 체크박스 렌더링
        selected_indices = []
        if st.session_state.start_generation:
            selected_indices = (
                st.session_state.selected_indices
            )  # 이전에 선택한 값 유지
        else:
            for idx, issue in enumerate(st.session_state.issues):
                if st.checkbox(issue[3:], key=f"issue_{idx}"):
                    selected_indices.append(idx)

        if st.button(
            "선택한 이슈로 웹툰 생성", disabled=st.session_state.start_generation
        ):
            st.session_state.selected_indices = selected_indices  # 선택한 값 저장
            st.session_state.is_processing = True  # 전체 UI 잠금
            st.session_state.start_generation = True  # 생성 트리거 ON
            st.session_state.waiting_for_user = False  # 대기 상태 해제
            st.rerun()
else:
    # 🚨 이미지를 생성 중일 때(조건이 안 맞을 때), 남아있는 체크박스들을 화면에서 즉시 삭제!
    hitl_placeholder.empty()


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
                                    st.info(
                                        f"♻️ **기존 웹툰을 불러왔습니다**\n\n{issue_title}"
                                    )
                                else:
                                    st.success(
                                        f"🎨 **새로운 웹툰이 완성되었습니다**\n\n{issue_title}"
                                    )
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
                        print(f"⚠️ 웹툰 생성 실패: {error_message}")

                        st.session_state.messages.append(
                            {
                                "role": "assistant",
                                "type": "warning",
                                "title": issue_title,
                                "content": "현재 선택하신 이슈는 시각화 정책 또는 시스템 과부화로 인해 웹툰 생성이 제한되었습니다.",
                            }
                        )


if st.session_state.start_generation:
    # 세션에 저장된 대화 기록 중 '이미지'만 필터링해서 가져옵니다.
    existing_images = [
        msg for msg in st.session_state.messages if msg.get("type") == "image"
    ]

    # 기존에 생성된 이미지가 1개라도 있다면 HTML/JS 슬라이드쇼를 띄웁니다!
    if existing_images:
        st.info("💡 **Tip:** 새로운 웹툰이 그려지는 동안 기존 작품들을 감상해 보세요!")

        slides_html = ""
        for i, msg in enumerate(existing_images):
            # 첫 번째 이미지만 보이게 하고 나머지는 숨김 처리
            display = "block" if i == 0 else "none"
            img_src = get_image_base64(msg["path"])

            if img_src:
                slides_html += f"""
                <div class="auto-slide" style="display: {display}; text-align: center; animation: fade 1.5s;">
                    <img src="{img_src}" style="max-height: 400px; max-width: 100%; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.15);">
                    <div style="margin-top: 15px; font-weight: bold; font-size: 1.0em; color: #444;">
                        {msg["title"]}
                    </div>
                </div>
                """

        # 순수 CSS + JS로 파이썬이 멈춰있어도 브라우저에서 알아서 3초마다 넘어갑니다!
        html_code = f"""
        <style>
        @keyframes fade {{
            from {{opacity: .4}} 
            to {{opacity: 1}}
        }}
        </style>
        <div style="width: 100%; max-width: 600px; margin: 0 auto; padding: 10px; position: relative;">
            {slides_html}
        </div>
        <script>
            let slideIndex = 0;
            const slides = document.querySelectorAll('.auto-slide');
            if (slides.length > 1) {{
                setInterval(() => {{
                    slides[slideIndex].style.display = 'none';
                    slideIndex = (slideIndex + 1) % slides.length;
                    slides[slideIndex].style.display = 'block';
                }}, 3000); // 3000ms = 3초마다 슬라이드 전환
            }}
        </script>
        """
        # 독립된 iframe 컴포넌트로 화면에 렌더링 (높이 여유 있게 설정)
        components.html(html_code, height=525)

    # 슬라이드쇼가 브라우저에서 도는 동안 파이썬은 열심히 스피너와 함께 이미지를 생성합니다.
    with st.spinner("선택한 이슈의 웹툰 이미지를 그리고 있습니다..."):
        generate_images()

    # 작업 완료 후, 상태 복구 및 리런하여 UI 잠금 해제
    st.session_state.is_processing = False
    st.session_state.start_generation = False
    st.rerun()
