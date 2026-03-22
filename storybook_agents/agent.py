from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools.agent_tool import AgentTool

from .prompts import ILLUSTRATOR_PROMPT, STORY_WRITER_PROMPT
from .tools import (
    generate_all_images,
    get_final_markdown,
    save_story_pages,
    set_story_theme,
)

load_dotenv()

# 1. LLM 모델 설정 (Gemini 또는 OpenAI 선택)
ADK_DIV = "openai"
MODEL = LiteLlm(
    "gemini/gemini-2.0-flash" if ADK_DIV == "gemini" else "openai/gpt-4o-mini"
)


# 2. 서브 에이전트 전용 State 조작 도구들
writer_agent = Agent(
    name="StoryWriterAgent",
    description="주어진 테마로 동화책 스토리를 기획하고 작성하는 에이전트입니다.",
    instruction=STORY_WRITER_PROMPT
    + "\n스토리를 모두 작성한 후, 반드시 'save_story_pages' 도구를 호출하여 데이터를 저장하세요."  # 지시사항 간소화
    + "\n도구 호출이 '성공'하면 더 이상 말하지 말고 즉시 작업을 종료하세요.",
    model=MODEL,
    output_key="writer_agent_output",
    tools=[save_story_pages],  # State 쓰기 권한 부여
)

illustrator_agent = Agent(
    name="IllustratorAgent",
    description="작성된 스토리를 바탕으로 삽화를 그리는 에이전트입니다.",
    instruction=ILLUSTRATOR_PROMPT
    + "\n순서:\n1. 'get_current_story'로 스토리를 읽습니다.\n2. 각 페이지의 visual_description을 사용하여 'generate_and_save_image' 도구로 이미지를 모두 생성하세요.",
    model=MODEL,
    output_key="illustrator_agent_output",
    tools=[generate_all_images],  # State 읽기/수정 권한 부여
)


# 3. Manager 에이전트 정의 (오케스트레이터)
manager_agent = Agent(
    name="StorybookManager",
    description="동화책 제작 전체 파이프라인을 총괄하는 매니저입니다.",
    instruction="""
    사용자의 동화책 테마를 받으면 다음 순서를 엄격히 따르세요:
    1. 입력받은 테마를 StoryWriterAgent에게 전달하여 작업을 지시합니다.
    2. 작성 완료 피드백을 받으면, IllustratorAgent에게 삽화 생성을 지시합니다.
    3. 두 에이전트의 작업이 모두 끝나면 'get_final_markdown' 도구를 호출하여 최종 마크다운을 획득하고 사용자에게 출력하세요.""",
    model=MODEL,
    tools=[
        set_story_theme,
        AgentTool(agent=writer_agent),
        AgentTool(agent=illustrator_agent),
        get_final_markdown,
    ],
)

# adk web 엔트리 포인트
root_agent = manager_agent
