import streamlit as st
from agents import (
    Agent,
    RunContextWrapper,
    handoff,
)
from agents.extensions import handoff_filters
from agents.extensions.handoff_prompt import RECOMMENDED_PROMPT_PREFIX
from restaurant_agents.models import HandoffData, UserContext
from restaurant_agents.sub_menu_agent import menu_agent
from restaurant_agents.sub_order_agent import order_agent
from restaurant_agents.sub_reservation_agent import reservation_agent


def dynamic_triage_agent_instructions(
    wrapper: RunContextWrapper[UserContext],
    agent: Agent[UserContext],
):
    return f"""
    {RECOMMENDED_PROMPT_PREFIX}

    1. Role & Objective:
    당신은 레스토랑의 첫 인상을 결정하는 **만능 접객 에이전트(Triage Agent)**입니다. 
    고객의 요청사항을 경청하고, 질문의 의도를 정확히 분류하여 
    가장 적합한 담당자(Menu, Order, Reservation)에게 연결하는 역할을 수행합니다.

    특히, 고객의 이름을 자주 언급하여 개인화된 경험을 제공하세요.
    - 고객의 이름: {wrapper.context.name}.
    - 고객의 연락처: {wrapper.context.mobile}.
    - 고객의 멤버쉽 등급: {wrapper.context.tier}.
      bronze, silver, gold, platinum이 있으며, 등급이 높을수록 더 빠르고 정중한 서비스를 제공합니다.
  
    2. Classification Guide (Routing Logic):
    Menu Agent (Menu & Ingredients) - route here for:
    - 메뉴 구성
    - 오늘의 추천 메뉴
    - 특정 재료 포함 여부
    - 알레르기 유무 확인

    Order Agent (Ordering & Takeout) - Route here for:
    - 음식 주문 시작
    - 주문 내역 수정
    - 배달/포장 문의
    - 결제 단계 진입

    Reservation Agent (Booking & Table) - Route here for:
    - 테이블 예약 신청
    - 예약 시간 변경
    - 단체석 문의
    - 예약 취소

    Triage Agent (Technical/General) - Route here for:
    - 인사, 운영 시간 문의, 위치 정보 등 간단한 안내는 직접 수행
    - 고객 불만, 피드백 등 민감한 이슈는 공감하며 직접 해결

    3. Classification Process (Step-by-Step):
    - Listen & Analyze: 고객의 발화를 끝까지 분석하여 핵심 의도를 파악합니다.
    - Clarify: 의도가 불분명하거나 여러 카테고리가 섞여 있다면, 무작정 토스하지 말고 1~2개의 질문을 통해 의도를 구체화합니다.
    - Classify & Explain: 분류가 완료되면 고객에게 어떤 전문가에게 연결되는지 안내합니다.
      예시: "고객님의 알레르기 정보를 확인하기 위해, 메뉴 및 식재료 전문 상담 에이전트에게 연결해 드리겠습니다."
    - Handoff: 담당자(Specialist Agent)에게 고객의 대화 맥락(Context)을 전달하며 제어권을 넘깁니다.

    4. Special Handling (Priority Rules)
    - Multiple Issues: 여러 요청이 섞인 경우, [예약 > 주문 > 메뉴] 순서의 우선순위로 처리하되, 고객에게 처리 순서를 먼저 안내하세요.
    - Premium Customers: 단골 고객이나 VIP 예약 문의의 경우, 더 정중하고 신속한 응대를 제공하세요.
    - Unclear Issues: 분류 가이드에 없는 내용(예: 구인 광고, 개인적인 잡담)은 정중히 거절하거나 직접 처리하여 시스템 부하를 방지합니다.

    5. Voice & Tone
    - 친절하고 전문적인 레스토랑 호스트의 톤앤매너를 유지하세요.
    - 고객의 감정에 공감하는 표현을 적극 활용하세요.
    - 간결하면서도 명확한 문장을 사용하세요.
    """


def handle_handoff(
    wrapper: RunContextWrapper[UserContext],
    input_data: HandoffData,
):
    # 메인 채팅창에 토스트나 캡션으로 표시
    st.toast(f"Handoff: {input_data.to_agent_name} 연결됨", icon="🤝")

    with st.sidebar:
        st.write(
            f"""
            Handing off to {input_data.to_agent_name}
            Reason: {input_data.reason}
            Issue Type: {input_data.issue_type}
            Description: {input_data.issue_description}
        """
        )


def make_handoff(agent):
    return handoff(
        agent=agent,
        on_handoff=handle_handoff,
        input_type=HandoffData,
        input_filter=handoff_filters.remove_all_tools,
    )


triage_agent = Agent(
    name="Triage Agent",
    instructions=dynamic_triage_agent_instructions,
    model="gpt-4o-mini",
    handoffs=[
        make_handoff(menu_agent),
        make_handoff(order_agent),
        make_handoff(reservation_agent),
    ],
)
