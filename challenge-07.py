import asyncio
import os

import dotenv
import streamlit as st
from agents import (
    InputGuardrailTripwireTriggered, 
    OutputGuardrailTripwireTriggered,
    Runner, 
    SQLiteSession, 
)
from openai import OpenAI

from restaurant_agents.factory import triage_agent
from restaurant_agents.models import UserContext

dotenv.load_dotenv()

# 1. Streamlit Secrets에서 먼저 찾고, 없으면 환경변수에서 찾음
openai_api_key = st.secrets.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")

if not openai_api_key:
    st.error("OpenAI API Key가 설정되지 않았습니다. Secrets 설정을 확인해주세요.")
    st.stop()

# 클라이언트 초기화 시 키 전달
client = OpenAI(api_key=openai_api_key)
# client = OpenAI()


user_context = UserContext(
    customer_id=1,
    name="홍길동",
    mobile="010-1234-5678",
    tier="gold",
)

if "session" not in st.session_state:
    st.session_state["session"] = SQLiteSession(
        "chat-history",
        "restaurant-operation-agent.db",
    )
session = st.session_state["session"]

if "agent" not in st.session_state:
    st.session_state["agent"] = triage_agent


async def paint_history():
    messages = await session.get_items()
    for message in messages:
        if "role" in message:
            with st.chat_message(message["role"]):
                if message["role"] == "user":
                    st.write(message['content'])
                else:
                    if message["type"] == "message":
                        if message["content"][0]["text"]:
                            agent_name = st.session_state["agent"].name.split(" ")[0]
                            st.write(f"{agent_name}: {message['content'][0]['text']}")


asyncio.run(paint_history())


async def run_agent(message):
    with st.chat_message("ai"):
        # 초기 에이전트 이름 표시를 위한 placeholder
        header_placeholder = st.empty()
        text_placeholder = st.empty()
        response = ""

        # 현재 에이전트 표시
        current_agent = st.session_state["agent"]
        header_placeholder.markdown(f"**🤖 {current_agent.name}**")
        st.session_state["text_placeholder"] = text_placeholder

        try:
            stream = Runner.run_streamed(
                st.session_state["agent"],
                message,
                session=session,
                context=user_context,
            )

            async for event in stream.stream_events():
                if event.type == "raw_response_event":
                    if event.data.type == "response.output_text.delta":
                        response += event.data.delta
                        text_placeholder.write(response)

                elif event.type == "agent_updated_stream_event":
                    new_agent = event.new_agent
                    if st.session_state["agent"].name != event.new_agent.name:
                        # 1. 이전 에이전트의 최종 답변 확정
                        text_placeholder.write(response)

                        # 2. Handoff 구분선 및 알림
                        st.markdown(
                            f"--- \n> 🔄 **{new_agent.name}**에게 업무를 인계합니다..."
                        )

                        # 3. 세션 상태 업데이트 및 새 UI 준비
                        st.session_state["agent"] = new_agent
                        response = ""
                        text_placeholder = st.empty()
                        st.session_state["text_placeholder"] = text_placeholder

        except InputGuardrailTripwireTriggered:
            st.write("I can't help you with that.")

        except OutputGuardrailTripwireTriggered:
            st.write("I can't show you that answer.")
            st.session_state["text_placeholder"].empty()


st.set_page_config(
    page_title="::: 이탈리안 레스토랑 :::",
    page_icon="🍕",
)
st.title("🍕 이탈리안 레스토랑")

message = st.chat_input("안녕하세요 이탈리안 레스토랑 입니다. 메뉴/주문/예약 관련하여 문의해 주세요. 예시: '오늘의 스페셜 메뉴가 뭐야?', '저녁 7시에 4명 예약할 수 있을까?', '마르게리따 피자 주문하고 싶어'")

if message:
    with st.chat_message("human"):
        st.write(message)
    asyncio.run(run_agent(message))


with st.sidebar:
    st.write("## Agent Session History")
    reset = st.button("Reset memory")
    if reset:
        asyncio.run(session.clear_session())
    st.write(asyncio.run(session.get_items()))
