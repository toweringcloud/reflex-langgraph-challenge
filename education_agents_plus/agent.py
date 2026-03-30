import asyncio
import operator
import uuid
from typing import Annotated, List, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, Send, interrupt
from tools import (
    generate_single_image3,
    get_domain_keyword,
    get_global_country_map,
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
    """단계 2: 사용자가 올바른 인덱스를 입력할 때까지 반복 확인하는 HITL 노드"""
    while True:
        max_idx = len(state["issue_list"])

        # 여기서 그래프가 중단(Interrupt)되고, 상태가 체크포인트에 저장됩니다.
        # 1. 사용자에게 입력을 요청 (1 ~ max_idx 범위 안내)
        values = interrupt(
            {
                "question": f"생성하고 싶은 이슈 번호 (1~{max_idx}, 여러 개 선택 시 쉼표로 구분):",
                "options": state["issue_list"],
            }
        )

        # 2. 입력값 검증 (잘못된 입력일 경우, 그래프는 다시 interrupt 지점에서 대기 必)
        try:
            # 1. 입력받은 값의 타입 체크
            selected = []
            for i in values:
                # 데이터 타입 판별 후 안전하게 변환
                val = int(i.strip()) if isinstance(i, str) else int(i)
                selected.append(val - 1)  # 사용자 입력(1~5)을 인덱스(0~4)로 변환

            # 2. 범위 검증 (1 ~ max_idx)
            if all(0 <= int(i) <= max_idx - 1 for i in selected):
                # print(f"✅ 유효한 입력 수신: {[i + 1 for i in selected]}")
                return {"selected_indices": selected}
            else:
                print(f"❌ 범위를 벗어난 번호가 있습니다. (1~{max_idx} 사이 입력)")
                # 빈 리스트로 반환하여 다시 입력 받도록 유도
                return {"selected_indices": []}

        except (ValueError, TypeError, AttributeError) as e:
            print(f"❌ 올바른 형식의 번호를 입력해 주세요. (에러: {e})")
            return {"selected_indices": []}


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


def create_cartoon_image_node(state: ImageTaskState):
    """단계 4: 실제 병렬로 실행될 개별 작업 (Send에 의해 호출됨)"""
    refined_issue_text = state["issue_text"][3:].strip()
    result = generate_single_image3(refined_issue_text)

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

# 메모리(체크포인터) 정의 - HITL을 위해 상태 저장이 필요함
memory = MemorySaver()
app = workflow.compile(checkpointer=memory)

# DB 연결 및 영구 체크포인터 생성 (추후 SqliteSaver로 교체 예정)
# conn = sqlite3.connect("agent_memory.db", check_same_thread=False)
# memory = SqliteSaver(conn)
# app = workflow.compile(checkpointer=memory)


# 4. 실행 방법 (HITL 흐름)
async def run_geo_agent():
    print("🌍 [지오 마스터 에이전트]를 시작합니다.")

    # 1. 초기 설정 및 스레드 생성
    # 실행할 때마다 혹은 사용자 세션마다 새로운 ID 발급
    session_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": session_id}}

    # 2. 입력 조건 중에 도메인 검증
    domain_map = {
        "1": "economy",
        "2": "culture",
        "3": "education",
        "4": "science",
        "5": "military",
    }

    while True:
        print("\n👉 분석할 주제 분야를 선택하세요:")
        print("  1. 경제 (Economy)")
        print("  2. 문화 (Culture)")
        print("  3. 교육 (Education)")
        print("  4. 과학 (Science)")
        print("  5. 방산 (Military)")
        domain_choice = input("선택 (1~5): ").strip()

        if domain_choice in domain_map:
            target_domain = domain_map[domain_choice]
            break
        print("❌ 잘못된 입력입니다. 1에서 5 사이의 숫자 중에 하나를 입력해 주세요.")

    # 3. 입력 조건 중에 국가 명 검증
    country_map = get_global_country_map()

    while True:
        target_country_input = input(
            "\n👉 분석하고 싶은 국가명을 한글 or 영문 or 국가코드로 입력해 주세요: "
        ).strip()
        if target_country_input in country_map:
            # 검색 엔진과 LLM의 품질을 극대화하기 위해 영어 공식 명칭으로 치환하여 State에 넘깁니다.
            target_country = country_map[target_country_input]
            print(
                f"✅ 인식된 국가: {target_country_input} (공식 명칭: {target_country})"
            )
            break
        else:
            print(
                "❌ 등록되지 않거나 잘못된 국가명입니다. 정확한 국가명을 입력해 주세요."
            )

    # 4. 입력 조건 중에 기간 (1~100) 검증 ---
    while True:
        try:
            target_years = int(
                input("\n👉 몇 년 전까지의 히스토리를 볼까요? (1~100): ").strip()
            )
            if 1 <= target_years <= 100:
                break
            else:
                print("❌ 범위를 벗어났습니다. 1에서 100 사이의 숫자를 입력해주세요.")
        except ValueError:
            print("❌ 숫자로만 입력해주세요.")

    initial_input = {
        "domain": target_domain,
        "country": target_country,
        "years": target_years,
    }

    # 5. 그래프 실행 루프
    # stream_mode="updates"를 사용하면 노드가 끝날 때마다 이벤트를 받습니다.
    async for event in app.astream(initial_input, config, stream_mode="updates"):
        # 에이전트가 이슈 리스트를 뽑아냈을 때 (history_search_node 완료 후)
        if "history_search" in event:
            issues = event["history_search"]["issue_list"]
            print(
                f"\n🔍 최근 {target_years}년 동안, {target_country}의 주요 {get_domain_keyword(target_domain)} 이슈 목록입니다:"
            )
            for issue in enumerate(issues):
                print(f"{issue[1]}")

        # 6. Human-in-the-loop: interrupt 처리
        if "__interrupt__" in event:
            interrupt_content = event["__interrupt__"][0].value
            print(f"\n💡 {interrupt_content['question']}")

            # 사용자의 입력을 리스트 형태로 정제합니다.
            user_input = input("👉 번호를 입력하세요 (예: 1, 3, 5): ")
            selected_indices = [i.strip() for i in user_input.split(",")]

            # 7. 입력받은 값을 들고 Command(resume=)로 다시 실행 재개!
            async for update in app.astream(Command(resume=selected_indices), config):
                if "cartoon_generation" in update:
                    res = update["cartoon_generation"]
                    image_data = res["final_images"][0]

                    # 7-1. 이미지 생성 성공 여부에 따른 분기 처리
                    if image_data.get("status") == "success":
                        print(f"ℹ️ 처리된 이슈: {image_data.get('issue')}")
                        print(f"✅ 이미지 생성 완료: {image_data.get('file')}")
                    # 7-2. Safety System에 의해 차단된 경우 안내 출력
                    else:
                        print(f"🔒 차단된 이슈: {image_data.get('issue')}")
                        print(f"⚠️ {image_data.get('reason')}")

    print("\n✨ 모든 작업이 완료되었습니다.")


# 에이전트 실행
if __name__ == "__main__":
    asyncio.run(run_geo_agent())
