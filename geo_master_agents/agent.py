import operator
import re
from typing import Annotated, Any, List, TypedDict

from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, Send, interrupt
from pydantic import BaseModel, Field
from tools import (
    CloudflareD1Saver,
    generate_single_image3,
    get_refined_issues,
)
from utils import (
    generate_cache_key_for_image,
    get_kv_cache,
    set_kv_cache,
)


# 1. State 정의
class AgentState(TypedDict):
    domain: str  # 예: "economy", "culture", "education", "science", "military"
    country: str  # 예: "한국", "kr", "south korea" -> "Korea, Republic of" (도구에서 영어 공식 명칭으로 치환)
    years: int  # 예: 1~100 사이의 정수 (고대 문명 시대도 포함하면 좋겠으나 검색 가능 데이터를 고려해서 100년 정도로 제한)
    issue_list: List[str]  # 검색된 이슈 목록 Top N (예: 5개)
    selected_indices: List[int]  # 사용자가 선택한 번호들 (HITL 입력값)
    selected_years: List[int]  # 선택한 이슈의 연도(yyyy) 값들
    final_images: Annotated[List[dict], operator.add]  # 병렬 실행 결과 취합
    messages: List[Any]


# 병렬 Node용 개별 State
class ImageTaskState(TypedDict):
    issue_text: str
    year: int  # 추출된 개별 이슈 연도(yyyy)
    domain: str  # 캐시 키용 분야 정보
    country: str  # 캐시 키용 국가 정보


# 사용자의 입력에서 추출할 데이터 구조 정의
class UserIntent(BaseModel):
    country: str = Field(description="추출된 국가 이름 (예: 한국, 미국, 영국)")
    domain: str = Field(
        description="관심 분야 (economy, culture, education, science, military 중 선택)",
        default="economy",
    )
    years: int = Field(description="조사 기간 (숫자만 추출, 범위는 1~100)", default=10)
    is_valid: bool = Field(description="국가 정보가 포함되어 있어 검색이 가능한지 여부")


# 2. Node용 Action 함수 정의
def classify_user_intent_node(state: AgentState):
    """단계 0: 사용자 의도 분석"""

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    structured_llm = llm.with_structured_output(UserIntent)

    messages = state.get("messages", [])
    if not messages:
        if state.get("country"):
            return {}  # 이미 국가 정보가 있다면 의도 분석 패스!
        else:
            return {
                "messages": [
                    ("assistant", "질문을 이해하지 못했어요. 다시 말씀해 주시겠어요?")
                ]
            }

    # 최근 사용자 메시지 가져오기 (튜플 형태인지 객체 형태인지 확인하여 순수 텍스트만 추출)
    last_message = messages[-1]
    if isinstance(last_message, tuple):
        user_query = last_message[1]  # ("user", "텍스트") 형태인 경우
    else:
        user_query = getattr(last_message, "content", str(last_message))

    system_prompt = """당신은 사용자의 질문에서 국가, 분야, 기간을 추출하는 전문가입니다.
    분야는 반드시 [economy, culture, education, science, military] 중 하나로 매핑하세요.
    국가 정보가 전혀 없다면 is_valid를 False로 설정하세요."""

    intent = structured_llm.invoke(
        [
            ("system", system_prompt),
            ("user", user_query),
        ]
    )

    if not intent.is_valid:
        return {
            "messages": [
                (
                    "assistant",
                    "어느 국가의 소식을 찾아드릴까요? 국가명을 포함해 말씀해 주세요!",
                )
            ]
        }

    # 추출된 정보를 State에 업데이트
    return {
        "country": intent.country,
        "domain": intent.domain,
        "years": intent.years,
        "messages": [
            (
                "assistant",
                f"🔎 {intent.country}의 {intent.domain} 이슈({intent.years}년치)를 분석해 드릴게요.",
            )
        ],
    }


def search_historical_issues_node(state: AgentState):
    """단계 1: 주요 히스토리 검색 및 LLM을 통한 Top N 필터링"""

    # 1. State에서 필요한 값 추출
    domain = state.get("domain", "economy")
    country = state.get("country")
    years = state.get("years", 10)
    top_n = 5

    if not country:
        # 국가 정보가 없으면 다시 물어보는 메시지 반환
        return {
            "messages": [
                (
                    "assistant",
                    "죄송합니다. 국가 정보를 찾지 못했어요. 어느 나라인지 다시 말씀해 주세요.",
                )
            ]
        }

    # 2. Tool 호출 (State 값을 인자로 전달)
    results = get_refined_issues(domain, country, years, top_n)
    return {"issue_list": results}


def approve_by_human_node(state: AgentState):
    """단계 2: 사용자가 선택한 인덱스를 받아 검증하는 HITL 노드 (Streamlit 전용)"""

    max_idx = len(state["issue_list"])

    # 1. 그래프 중단 및 사용자 입력 대기 (Streamlit에서 resume_data로 전달됨)
    values = interrupt(
        {
            "question": "시각화할 이슈 번호를 선택하세요",
            "options": state["issue_list"],
        }
    )

    # 2. 유효한 인덱스만 필터링
    selected_indices = values
    valid_indices = [i for i in selected_indices if 0 <= i < max_idx]

    # 3. 선택된 이슈 텍스트에서 연도(yyyy) 추출
    # 이슈 포맷이 "2013: [경제 성장]..." 형태라고 가정하고 정규식으로 4자리 숫자를 찾습니다.
    selected_years = []
    for i in valid_indices:
        issue_text = state["issue_list"][i]
        # 문자열 맨 앞의 4자리 숫자 추출
        year_match = re.search(r"^(\d{4})", issue_text)
        if year_match:
            selected_years.append(int(year_match.group(1)))
        else:
            # 연도를 찾지 못한 경우 기본값으로 0 또는 적절한 예외 처리
            selected_years.append(0)

    # 4. State에 선택된 인덱스와 추출된 연도 리스트를 함께 업데이트
    return {
        "selected_indices": valid_indices,
        "selected_years": selected_years,
    }


def trigger_parallel_jobs_node(state: AgentState):
    """단계 3: 병렬 실행을 위한 Send API (Map-Reduce 패턴) 호출 노드"""

    # zip을 활용해 인덱스와 연도를 쌍으로 묶어서 전달합니다.
    return [
        Send(
            "cartoon_generation",
            {
                "issue_text": state["issue_list"][idx],
                "year": year,  # 👈 개별 연도 전달
                "domain": state["domain"],
                "country": state["country"],
            },
        )
        for idx, year in zip(state["selected_indices"], state["selected_years"])
    ]


def create_cartoon_image_node(state: ImageTaskState, config: RunnableConfig):
    """단계 4: 실제 병렬로 실행될 개별 작업 (Send에 의해 호출됨)"""

    # 🚨 터미널 진행 상황 출력 추가!
    print(
        f"\n🎨 [이미지 생성 중] Gemini API 호출을 시작합니다: {state['issue_text'][:20]}..."
    )
    issue_text = state["issue_text"]

    # 1. 고유 캐시 키 생성 (조건 조합)
    cache_key = generate_cache_key_for_image(
        state.get("domain"),
        state.get("country"),
        state.get("year"),
        issue_text[9:].strip(),
    )

    # 2. KV 캐시 확인 (기존 utils 함수 재활용)
    cached_data = get_kv_cache(cache_key)
    if cached_data:
        print("⚡ [KV Cache Hit] 이미 생성된 이미지가 있습니다.")
        return {
            "final_images": [
                {
                    "status": "success",
                    "file": cached_data["image_url"],  # 저장된 URL 꺼내기
                    "issue": issue_text,
                    "is_cached": True,  # 👈 캐시 적중 플래그 추가!
                }
            ]
        }

    # 3. 캐시 미스 시 이미지 생성
    refined_text = issue_text[3:].strip()
    user_id = config.get("configurable", {}).get("user_id", "guest")
    result = generate_single_image3(refined_text, user_id)
    print("✅ [이미지 생성 완료] 결과를 반환합니다.")

    # 에러 방지 (예: 도구 내부에서 예외 발생 시 문자열 리턴)
    if isinstance(result, str):
        return {
            "final_images": [
                {"status": "error", "text": result, "issue": state["issue_text"]}
            ]
        }

    if result["status"] == "success":
        new_url = result["file"]
        # 4. KV 캐시 저장 (다음 호출을 위해)
        set_kv_cache(cache_key, {"image_url": new_url, "prompt": refined_text})

        return {
            "final_images": [
                {
                    "status": "success",
                    "file": new_url,
                    "issue": issue_text,
                    "is_cached": False,  # 👈 신규 생성 플래그 추가!
                }
            ]
        }
    else:
        return {
            "final_images": [
                {
                    "status": result.get("status"),
                    "text": result.get("fallback_text"),
                    "issue": state["issue_text"],
                }
            ]
        }


# 조건부 로직: 국가 정보가 확인되면 검색으로, 아니면 종료(대기)
def should_continue_to_search(state: AgentState):
    if state.get("country"):
        return "history_search"
    return END


# 3. Graph 구성 with Nodes and Edges
workflow = StateGraph(AgentState)

workflow.add_node("intent_classify", classify_user_intent_node)
workflow.add_node("history_search", search_historical_issues_node)
workflow.add_node("user_approval", approve_by_human_node)
workflow.add_node("cartoon_generation", create_cartoon_image_node)

# 챗 메시지의 맥락을 파악 후, 질문에 필수 조건이 모두 있는 지 확인
# 1. 시작은 무조건 의도 분석 노드부터! (Single Entry Point):
workflow.add_edge(START, "intent_classify")

# 2. 의도 분석 결과에 따른 분기 (국가 정보가 있으면 검색으로, 없으면 종료/대기)
workflow.add_conditional_edges(
    "intent_classify",
    should_continue_to_search,
    {"history_search": "history_search", END: END},
)

# 3. 검색 이후의 흐름은 기존과 동일하게 연결
# 이슈 분석 대상 도메인 + 국가 + 기간 선택 후, 이슈 검색 실행
workflow.add_edge("history_search", "user_approval")

# 4. 사용자 승인(HITL) 이후 병렬 이미지 생성 트리거
workflow.add_conditional_edges(
    "user_approval",
    trigger_parallel_jobs_node,
    ["cartoon_generation"],
)

# 5. 모든 이미지 생성 완료 후 종료
workflow.add_edge("cartoon_generation", END)

# 영구 체크포인터 정의 - HITL을 위해 상태 저장 必
memory = CloudflareD1Saver()
app = workflow.compile(checkpointer=memory)


# 4. Streamlit 호출용 실행 래퍼 (파라미터 추가)
def run_geo_agent(
    initial_input: dict, thread_id: str, user_id: str = "unknown", resume_data=None
):
    """
    Streamlit UI에서 호출하는 비동기 에이전트 실행 함수입니다.
    """
    print("🌍 [지오 마스터 에이전트]를 시작합니다.")

    # ✅ Streamlit이 넘겨준 고정된 thread_id와 user_id를 config에 장착
    config = {
        "configurable": {
            "thread_id": thread_id,
            "user_id": user_id,
        }
    }

    # Resume(재개)인지 초기 실행인지 분기 처리
    if resume_data is not None:
        # [분기 1] HITL 재개: 사용자가 UI에서 번호를 선택해 넘겨준 경우
        for event in app.stream(
            Command(resume=resume_data), config, stream_mode="updates"
        ):
            yield event

    else:
        # [분기 2] 초기 실행: 국가/기간을 입력받아 검색을 시작하는 경우
        for event in app.stream(initial_input, config, stream_mode="updates"):
            yield event
