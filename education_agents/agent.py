from typing import List, TypedDict

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph

# .env 파일의 내용을 환경 변수로 로드
load_dotenv()


# 1. State 정의
class AgentState(TypedDict):
    input_country: str
    related_countries: List[str]
    timeline_story: str


# 모델 설정 (GPT-4o)
llm = ChatOpenAI(model="gpt-4o-mini")


# 2. Nodes 정의
def find_issues(state: AgentState):
    """입력 국가와 관련된 지정학적 이슈 국가를 찾습니다."""
    country = state["input_country"]
    prompt = f"{country}와 최근 100년 이내에 중요한 지정학적 이슈가 있었던 국가 3곳을 콤마로 구분해서 이름만 알려줘."
    response = llm.invoke([HumanMessage(content=prompt)])
    countries = [c.strip() for c in response.content.split(",")]
    return {"related_countries": countries}


def create_cartoon(state: AgentState):
    """지정학적 이슈를 타임라인 카툰 스토리로 생성합니다."""
    target = state["input_country"]
    partners = ", ".join(state["related_countries"])
    prompt = f"{target}와 {partners} 사이의 주요 지정학적 사건들을 4컷 카툰 형식의 타임라인(이미지 묘사 + 대사)으로 작성해줘."
    response = llm.invoke([HumanMessage(content=prompt)])
    return {"timeline_story": response.content}


# 3. 그래프 구축
workflow = StateGraph(AgentState)

workflow.add_node("find_issues", find_issues)
workflow.add_node("create_cartoon", create_cartoon)

workflow.add_edge(START, "find_issues")
workflow.add_edge("find_issues", "create_cartoon")
workflow.add_edge("create_cartoon", END)

# 4. 컴파일 및 실행
app = workflow.compile()

if __name__ == "__main__":
    # 테스트 실행
    inputs = {"input_country": "대한민국"}
    config = {"configurable": {"thread_id": "1"}}

    for event in app.stream(inputs, config):
        for value in event.values():
            print("--- Output ---")
            print(value)
