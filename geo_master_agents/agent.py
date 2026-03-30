import operator
from typing import Annotated, List, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, Send, interrupt
from tools import (
    CloudflareD1Saver,
    generate_single_image3,
    get_refined_issues,
)


# 1. State 정의
class AgentState(TypedDict):
    domain: str  # 예: "economy", "culture", "education", "science", "military"
    country: str  # 예: "한국", "kr", "south korea" -> "Korea, Republic of" (도구에서 영어 공식 명칭으로 치환)
    years: int  # 예: 1~100 사이의 정수 (고대 문명 시대도 포함하면 좋겠으나 검색 가능 데이터를 고려해서 100년 정도로 제한)
    issue_list: List[str]  # 검색된 이슈 목록 Top N (예: 5개)
    selected_indices: List[int]  # 사용자가 선택한 번호들 (HITL 입력값)
    final_images: Annotated[List[dict], operator.add]  # 병렬 실행 결과 취합


# 병렬 Node용 개별 State
class ImageTaskState(TypedDict):
    issue_text: str


# 2. Node용 Action 함수 정의
def search_historical_issues_node(state: AgentState):
    """단계 1: 주요 히스토리 검색 및 LLM을 통한 Top N 필터링"""
    # 1. State에서 필요한 값 추출
    domain = state["domain"]
    country = state["country"]
    years = state["years"]
    top_n = 5

    # 2. Tool 호출 (State 값을 인자로 전달)
    results = get_refined_issues(domain, country, years, top_n)
    return {"issue_list": results}


def approve_by_human_node(state: AgentState):
    """단계 2: 사용자가 선택한 인덱스를 받아 검증하는 HITL 노드 (Streamlit 전용)"""
    max_idx = len(state["issue_list"])

    # 1. 그래프 중단 및 사용자 입력 대기
    # Streamlit에서 resume_data로 넘겨준 리스트(예: [0, 2])가 values로 들어옵니다.
    values = interrupt(
        {
            "question": "시각화할 이슈 번호를 선택하세요",
            "options": state["issue_list"],
        }
    )

    # 2. Streamlit이 이미 정확한 0-based 정수 인덱스 리스트를 넘겨주므로,
    # 빼기 1 같은 변환 없이 그대로 사용하면 됩니다!
    selected_indices = values

    # 3. 안전을 위한 범위 검증 (유효한 인덱스만 걸러냄)
    valid_indices = [i for i in selected_indices if 0 <= i < max_idx]

    # 터미널용 print 문들은 전부 삭제하고 바로 리턴합니다.
    return {"selected_indices": valid_indices}


def trigger_parallel_jobs_node(state: AgentState):
    """단계 3: 병렬 실행을 위한 Send API (Map-Reduce 패턴) 호출 노드"""

    # 선택된 인덱스가 유효한 경우에만 Send 호출
    valid_indices = [
        i for i in state["selected_indices"] if 0 <= i < len(state["issue_list"])
    ]

    # 유효한 인덱스에 대해서만 병렬 노드 생성
    return [
        Send("cartoon_generation", {"issue_text": state["issue_list"][i]})
        for i in valid_indices
    ]


def create_cartoon_image_node(state: ImageTaskState, config: RunnableConfig):
    """단계 4: 실제 병렬로 실행될 개별 작업 (Send에 의해 호출됨)"""

    # 🚨 터미널 진행 상황 출력 추가!
    print(
        f"\n🎨 [이미지 생성 중] Gemini API 호출을 시작합니다: {state['issue_text'][:20]}..."
    )

    refined_issue_text = state["issue_text"][3:].strip()
    user_id = config.get("configurable", {}).get("user_id", "guest")

    # (이하 기존 코드 동일)
    result = generate_single_image3(refined_issue_text, user_id)
    print("✅ [이미지 생성 완료] 결과를 반환합니다.")

    # 에러 방지 (예: 도구 내부에서 예외 발생 시 문자열 리턴)
    if isinstance(result, str):
        return {
            "final_images": [
                {"status": "error", "text": result, "issue": state["issue_text"]}
            ]
        }

    # 정상적인 딕셔너리 결과 처리
    if result["status"] == "success":
        return {
            "final_images": [
                {
                    "status": "success",
                    "file": result.get("file"),
                    "issue": state["issue_text"],
                },
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


# 3. Graph 구성 with Nodes and Edges
workflow = StateGraph(AgentState)

workflow.add_node("history_search", search_historical_issues_node)
workflow.add_node("user_approval", approve_by_human_node)
workflow.add_node("cartoon_generation", create_cartoon_image_node)

# 기본 Edge 연결 (순차적 흐름)
workflow.add_edge(START, "history_search")
workflow.add_edge("history_search", "user_approval")
workflow.add_edge("cartoon_generation", END)

# 조건부 Edge 연결 (병렬 실행)
workflow.add_conditional_edges(
    "user_approval", trigger_parallel_jobs_node, ["cartoon_generation"]
)

# 영구 체크포인터 정의 - HITL을 위해 상태 저장이 필요함
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
