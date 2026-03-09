import asyncio
import base64
import copy
import os

import dotenv
import streamlit as st
from agents import (
    Agent,
    FileSearchTool,
    ImageGenerationTool,
    Runner,
    SQLiteSession,
    WebSearchTool,
)
from openai import OpenAI

dotenv.load_dotenv()


client = OpenAI()
VECTOR_STORE_ID = os.environ["OPENAI_VECTOR_STORE_ID"]


# action 필드만 제거하는 커스텀 세션 (by gamelulu1004 in nomadcoders)
class FilteredSQLiteSession(SQLiteSession):
    """action 필드만 제거하고 모든 메시지는 유지하는 SQLite 세션"""

    def __init__(self, session_id: str, database: str):
        """부모 클래스 초기화"""
        super().__init__(session_id, database)

    def _remove_action_recursive(self, obj):
        """재귀적으로 action 필드 제거"""
        if isinstance(obj, dict):
            # action 필드 제거
            cleaned = {k: v for k, v in obj.items() if k != "action"}
            # 재귀적으로 모든 값 처리
            return {k: self._remove_action_recursive(v) for k, v in cleaned.items()}
        elif isinstance(obj, list):
            return [self._remove_action_recursive(item) for item in obj]
        else:
            return obj

    async def get_items(self):
        items = await super().get_items()
        # action 필드만 제거하고 모든 메시지 유지
        cleaned_items = [
            self._remove_action_recursive(copy.deepcopy(item)) for item in items
        ]
        return cleaned_items


if "agent" not in st.session_state:
    st.session_state["agent"] = Agent(
        name="Life Coach Agent",
        instructions="""
        You are a helpful assistant of life coaching field.

        You have access to the following tools:
            - Web Search Tool: Use this tool when the user asks about motivation contents, self-development tips or habit formation guides. Or when you think you don't know the answer, try searching for it in the web first.
            - File Search Tool: Use this tool when the user asks a question about life goals, personal missions related to themselves or questions about their own specific document files the user uploaded.
            - Image Generation Tool: Use this tool when the user asks for visualization of concepts, ideas, or when they request inspirational images related to vision board or motivation.
        """,
        model="gpt-4o-mini",
        tools=[
            WebSearchTool(),
            FileSearchTool(
                vector_store_ids=[VECTOR_STORE_ID],
                max_num_results=3,
            ),
            ImageGenerationTool(
                tool_config={
                    "type": "image_generation",
                    "model": "gpt-image-1-mini",
                    "quality": "medium",
                    "output_format": "jpeg",
                    "partial_images": 1,
                }
            ),
        ],
    )
agent = st.session_state["agent"]

if "session" not in st.session_state:
    st.session_state["session"] = FilteredSQLiteSession(
        "chat-history",
        "life-coach-agent.db",
    )
session = st.session_state["session"]


async def paint_history():
    messages = await session.get_items()

    for message in messages:
        if "role" in message:
            with st.chat_message(message["role"]):
                if message["role"] == "user":
                    st.write(message["content"])
                else:
                    if message["type"] == "message":
                        st.write(message["content"][0]["text"])

        if "type" in message:
            message_type = message["type"]

            if message_type == "web_search_call":
                with st.chat_message("ai"):
                    st.write("🔍 Searched the web...")

            elif message_type == "file_search_call":
                with st.chat_message("ai"):
                    st.write("🗂️ Searched your files...")

            elif message_type == "image_generation_call":
                image = base64.b64decode(message["result"])
                with st.chat_message("ai"):
                    st.write("🎨 Generated the image you ask...")
                    st.image(image)


asyncio.run(paint_history())


def update_status(status_container, event):
    status_messages = {
        "response.web_search_call.in_progress": (
            "🔍 Starting web search...",
            "running",
        ),
        "response.web_search_call.searching": (
            "🔍 Web search in progress...",
            "running",
        ),
        "response.web_search_call.completed": (
            "✅ Web search completed.",
            "complete",
        ),
        "response.file_search_call.in_progress": (
            "🗂️ Starting file search...",
            "running",
        ),
        "response.file_search_call.searching": (
            "🗂️ File search in progress...",
            "running",
        ),
        "response.file_search_call.completed": (
            "✅ File search completed.",
            "complete",
        ),
        "response.image_generation_call.in_progress": (
            "🎨 Starting image generation...",
            "running",
        ),
        "response.image_generation_call.generating": (
            "🎨 Drawing image in progress...",
            "running",
        ),
        "response.image_generation_call.completed": (
            "✅ Image Generation completed.",
            "complete",
        ),
        "response.completed": (" ", "complete"),
    }

    if event in status_messages:
        label, state = status_messages[event]
        status_container.update(label=label, state=state)


async def run_agent(message):
    with st.chat_message("ai"):
        status_container = st.status("⏳", expanded=False)
        image_placeholder = st.empty()
        text_placeholder = st.empty()
        response = ""

        st.session_state["image_placeholder"] = image_placeholder
        st.session_state["text_placeholder"] = text_placeholder

        stream = Runner.run_streamed(
            agent,
            message,
            session=session,
        )

        async for event in stream.stream_events():
            if event.type == "raw_response_event":
                update_status(status_container, event.data.type)

                if event.data.type == "response.output_text.delta":
                    response += event.data.delta
                    text_placeholder.write(response)

                elif event.data.type == "response.image_generation_call.partial_image":
                    image = base64.b64decode(event.data.partial_image_b64)
                    image_placeholder.image(image)


prompt = st.chat_input(
    "Write a message for your assistant",
    accept_file=True,
    file_type=[
        "txt",
        "jpg",
        "jpeg",
        "png",
    ],
)

if prompt:
    if "image_placeholder" in st.session_state:
        st.session_state["image_placeholder"].empty()
    if "text_placeholder" in st.session_state:
        st.session_state["text_placeholder"].empty()

    for file in prompt.files:
        if file.type.startswith("text/"):
            with st.chat_message("ai"):
                with st.status("⏳ Uploading file...") as status:
                    uploaded_file = client.files.create(
                        file=(file.name, file.getvalue()),
                        purpose="user_data",
                    )
                    status.update(label="⏳ Attaching file...")
                    client.vector_stores.files.create(
                        vector_store_id=VECTOR_STORE_ID,
                        file_id=uploaded_file.id,
                    )
                    status.update(label="✅ File uploaded", state="complete")

        elif file.type.startswith("image/"):
            with st.status("⏳ Uploading image...") as status:
                file_bytes = file.getvalue()
                base64_data = base64.b64encode(file_bytes).decode("utf-8")
                data_uri = f"data:{file.type};base64,{base64_data}"
                asyncio.run(
                    session.add_items(
                        [
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "input_image",
                                        "detail": "auto",
                                        "image_url": data_uri,
                                    }
                                ],
                            }
                        ]
                    )
                )
                status.update(label="✅ Image uploaded", state="complete")
            with st.chat_message("human"):
                st.image(data_uri)

    if prompt.text:
        with st.chat_message("human"):
            st.write(prompt.text)
        asyncio.run(run_agent(prompt.text))


with st.sidebar:
    st.write("## Life Coach Agent")
    reset = st.button("Reset memory")
    if reset:
        asyncio.run(session.clear_session())
    st.write(asyncio.run(session.get_items()))
