import streamlit as st
from agents import (
    Agent, 
    GuardrailFunctionOutput,
    RunContextWrapper, 
    Runner,
    handoff, 
    input_guardrail,
    output_guardrail,
)
from agents.extensions import handoff_filters

from .instructions import (
    get_triage_instructions, 
    get_menu_instructions, 
    get_order_instructions, 
    get_reservation_instructions,
    get_complaints_instructions,
    get_input_guardrail_instructions,
    get_output_guardrail_instructions,
)
from .models import (
    HandoffData, 
    InputGuardRailOutput, 
    OutputGuardRailOutput,
    UserContext,
)


# 1. 인스턴스 먼저 생성 (Handoff 없이)
triage_agent = Agent(
    name="Triage Agent",
    instructions=get_triage_instructions,
)

menu_agent = Agent(
    name="Menu Agent",
    instructions=get_menu_instructions,
    model="gpt-4o-mini",
)

order_agent = Agent(
    name="Order Agent",
    instructions=get_order_instructions,
    model="gpt-4o-mini",
)

reservation_agent = Agent(
    name="Reservation Agent",
    instructions=get_reservation_instructions,
    model="gpt-4o-mini",
)

complaints_agent = Agent(
    name="Complaints Agent",
    instructions=get_complaints_instructions,
    model="gpt-4o-mini",
)

input_guardrail_agent = Agent(
    name="Input Guardrail Agent",
    instructions=get_input_guardrail_instructions,
    output_type=InputGuardRailOutput,
)

output_guardrail_agent = Agent(
    name="Output Guardrail Agent",
    instructions=get_output_guardrail_instructions,
    output_type=OutputGuardRailOutput,
)


def handle_handoff(
    wrapper: RunContextWrapper[UserContext],
    input_data: HandoffData,
):
    # 메인 채팅창에 토스트 메시지로 표시
    st.toast(f"Handoff: {input_data.to_agent_name} 연결됨", icon="🤝")

    with st.sidebar:
        st.write(f"""
            Handing off to {input_data.to_agent_name}
            Reason: {input_data.reason}
            Issue Type: {input_data.issue_type}
            Description: {input_data.issue_description}
        """
        )


def make_handoff(agent, description=None):
    return handoff(
        agent=agent,
        on_handoff=handle_handoff,
        input_type=HandoffData,
        input_filter=handoff_filters.remove_all_tools,
        # '오직'과 '일치할 때만'을 강조하여 무분별한 토스를 방지
        tool_description_override=(
            f"사용자의 요청이 **오직** '{description}'와(과) 명확히 일치할 때만 호출하세요. "
            f"모호하거나 단순한 인사, 확인 질문에는 절대로 이 도구를 사용하지 말고 직접 응답하세요."
        ),
    )


# 2. Handoff Relation 설정
triage_agent.handoffs = [
    make_handoff(
        menu_agent, 
        "사용자가 구체적인 메뉴 이름, 식재료, 혹은 알레르기 정보를 새롭게 질문했을 때만 사용하세요. 단순한 '알겠어'나 '그래' 같은 대답에는 사용하지 마세요."
    ),
    make_handoff(
        order_agent, 
        "사용자가 특정 음식을 주문하겠다고 확언하거나, 결제 방법을 묻는 등 구매 의사가 확실할 때만 사용하세요."
    ),
    make_handoff(
        reservation_agent, 
        "예약 가능 여부 확인, 신규 예약 생성, 혹은 기존 예약의 변경/취소를 명시적으로 요청했을 때만 사용하세요."
    ),
    make_handoff(
        complaints_agent, 
        "사용자가 서비스나 음식에 대해 명확한 불만, 항의, 실망감을 표현할 때만 사용하세요."
    ),
]

menu_agent.handoffs = [
    make_handoff(triage_agent, "현재 에이전트의 전문 업무(메뉴 관리)가 완전히 종결되었거나, 사용자가 완전히 새로운 주제를 꺼내어 더 이상 답변할 수 없을 때만 호출하세요. 상담을 마무리하는 중이라면 호출하지 말고 직접 끝인사를 하세요."),
]

order_agent.handoffs = [
    make_handoff(triage_agent, "현재 에이전트의 전문 업무(주문 관리)가 완전히 종결되었거나, 사용자가 완전히 새로운 주제를 꺼내어 더 이상 답변할 수 없을 때만 호출하세요. 상담을 마무리하는 중이라면 호출하지 말고 직접 끝인사를 하세요."),
]

reservation_agent.handoffs = [
    make_handoff(triage_agent, "현재 에이전트의 전문 업무(예약 관리)가 완전히 종결되었거나, 사용자가 완전히 새로운 주제를 꺼내어 더 이상 답변할 수 없을 때만 호출하세요. 상담을 마무리하는 중이라면 호출하지 말고 직접 끝인사를 하세요."),
]

complaints_agent.handoffs = [
    make_handoff(triage_agent, "현재 에이전트의 전문 업무(컴플레인 이슈대응)가 완전히 종결되었거나, 사용자가 완전히 새로운 주제를 꺼내어 더 이상 답변할 수 없을 때만 호출하세요. 상담을 마무리하는 중이라면 호출하지 말고 직접 끝인사를 하세요."),
]


@input_guardrail
async def off_topic_guardrail(
    wrapper: RunContextWrapper[UserContext],
    agent: Agent[UserContext],
    input: str,
):
    result = await Runner.run(
        input_guardrail_agent,
        input,
        context=wrapper.context,
    )

    return GuardrailFunctionOutput(
        output_info=result.final_output,
        tripwire_triggered=result.final_output.is_off_topic,
    )


@output_guardrail
async def output_audit_guardrail(
    wrapper: RunContextWrapper[UserContext],
    agent: Agent,
    output: str,
):
    result = await Runner.run(
        output_guardrail_agent,
        output,
        context=wrapper.context,
    )

    validation = result.final_output

    triggered = (
        validation.contains_off_topic
        or validation.contains_private_data
    )

    return GuardrailFunctionOutput(
        output_info=validation,
        tripwire_triggered=triggered,
    )


# 3. Input/Output Guardrail 설정
triage_agent.input_guardrails = [off_topic_guardrail]
triage_agent.output_guardrails = [output_audit_guardrail]


# 필요한 에이전트들을 export
__all__ = ["triage_agent", "menu_agent", "order_agent", "reservation_agent", "complaints_agent"]
