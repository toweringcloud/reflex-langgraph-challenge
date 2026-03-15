import asyncio

import dotenv
import streamlit as st
from agents import Runner, SQLiteSession
from openai import OpenAI
from restaurant_agents.models import UserContext
from restaurant_agents.triage_agent import triage_agent

dotenv.load_dotenv()


client = OpenAI()


user_context = UserContext(
    customer_id=1,
    name="tommy",
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
                    st.write(f"User: {message['content']}")
                else:
                    if message["type"] == "message":
                        if message["content"][0]["text"]:
                            agent_name = st.session_state["agent"].name.split(" ")[0]
                            st.write(f"{agent_name}: {message['content'][0]['text']}")


asyncio.run(paint_history())


async def run_agent(message):
    with st.chat_message("ai"):
        text_placeholder = st.empty()
        response = ""

        st.session_state["text_placeholder"] = text_placeholder

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
                if st.session_state["agent"].name != event.new_agent.name:
                    st.write(f"[🤖 {event.new_agent.name}로 handoff]")
                    st.session_state["agent"] = event.new_agent
                    text_placeholder = st.empty()
                    st.session_state["text_placeholder"] = text_placeholder
                    response = ""


message = st.chat_input(
    "Write a message for your assistant",
)

if message:
    with st.chat_message("human"):
        st.write(f"User: {message}")
    asyncio.run(run_agent(message))


with st.sidebar:
    st.write("## Restaurant Management Agent")
    reset = st.button("Reset memory")
    if reset:
        asyncio.run(session.clear_session())
    st.write(asyncio.run(session.get_items()))
