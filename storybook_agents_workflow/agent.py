from typing import Optional

from dotenv import load_dotenv
from google.adk.agents import Agent, ParallelAgent, SequentialAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.models.lite_llm import LiteLlm
from google.genai import types

from .models import StoryState
from .prompts import STORY_WRITER_PROMPT
from .tools import (
    generate_single_image,
    get_final_markdown,
    save_story_pages,
)

load_dotenv()

# LLM 모델 설정 (Gemini 또는 OpenAI 선택)
ADK_DIV = "openai"
MODEL = LiteLlm(
    "gemini/gemini-2.0-flash" if ADK_DIV == "gemini" else "openai/gpt-4o-mini"
)


# Callbacks (진행 상황 표시기)
def writer_callback(**kwargs):
    print("\n⏳ [진행 상황] 스토리 작성 중...")

    # kwargs에서 llm_request 객체를 안전하게 꺼내옵니다.
    llm_request = kwargs.get("llm_request")

    # ✨ 핵심 수정: .content 대신 .contents 속성이 있는지 확인하고 접근합니다.
    if llm_request and hasattr(llm_request, "contents"):
        # 필요하다면 여기서 첫 번째 메시지의 텍스트를 출력해볼 수 있습니다.
        # print(f"입력: {llm_request.contents[0].parts[0].text}")
        pass

    # 프레임워크가 다음 단계로 진행할 수 있도록 반드시 llm_request를 반환해야 합니다.
    return llm_request


def make_illustrator_callback(page_num):
    def callback(**kwargs):
        print(f"⏳ [진행 상황] 이미지 {page_num}/5 생성 중...")
        return kwargs.get("llm_request")

    return callback


def formatter_callback(**kwargs):
    print("\n✅ [진행 상황] 최종 동화책 편집 중...")
    return kwargs.get("llm_request")


# Callbacks for progress tracking
def on_story_start(callback_context: CallbackContext) -> Optional[types.Content]:
    print("📝 Writing story...")
    return None


def on_story_done(callback_context: CallbackContext) -> Optional[types.Content]:
    story = callback_context.state.to_dict().get("story_output", {})
    title = story.get("title", "Untitled")
    print(f"✅ Story written: {title}")
    return None


def on_illustrations_start(
    callback_context: CallbackContext,
) -> Optional[types.Content]:
    print("🎨 Generating all illustrations in parallel...")
    return None


def on_illustrations_done(callback_context: CallbackContext) -> Optional[types.Content]:
    print("✅ All illustrations complete!")
    return None


# 서브 에이전트 전용 State 조작 도구들
writer_agent = Agent(
    name="StoryWriterAgent",
    model=MODEL,
    description="주어진 테마로 동화책 스토리를 기획하고 작성하는 에이전트입니다.",
    instruction="당신은 동화 작가입니다. 추가적인 계획을 세우지 말고 'save_story_pages' 도구를 사용하여 스토리를 저장한 뒤 즉시 'FINISH'라고 말하며 작업을 끝내세요. "
    + STORY_WRITER_PROMPT
    + "\n스토리를 모두 작성한 후, 반드시 'save_story_pages' 도구를 호출하여 데이터를 저장하세요."  # 지시사항 간소화
    + "\n도구 호출이 '성공'하면 더 이상 말하지 말고 즉시 작업을 종료하세요.",
    tools=[save_story_pages],  # State 쓰기 권한 부여
    output_schema=StoryState,
    output_key="story_output",
    # before_model_callback=writer_callback,
    before_agent_callback=on_story_start,
    after_agent_callback=on_story_done,
)

# Parallel Illustrator 에이전트들 (1~5페이지 각각 담당)
illustrator_agents = []
for i in range(1, 6):
    agent = Agent(
        name=f"IllustratorAgent_Page_{i}",
        model=MODEL,
        description=f"{i}페이지 삽화 생성",
        instruction=f"당신은 {i}페이지 삽화가입니다. 다른 생각은 하지 말고 'generate_single_image' 도구에 page_number={i}를 전달하여 이미지를 생성하고 즉시 종료하세요.",
        tools=[generate_single_image],
        # before_model_callback=make_illustrator_callback(i),
    )
    illustrator_agents.append(agent)

# ✨ 5개의 삽화가 에이전트를 하나로 묶어 동시에 실행시키는 ParallelAgent
parallel_illustrator = ParallelAgent(
    name="ParallelIllustrator",
    description="5개의 페이지 삽화를 동시에 생성합니다.",
    sub_agents=illustrator_agents,
    before_agent_callback=on_illustrations_start,
    after_agent_callback=on_illustrations_done,
)

# Formatter 에이전트 (최종 조립)
formatter_agent = Agent(
    name="StoryFormatterAgent",
    model=MODEL,
    description="완성된 동화책을 출력합니다.",
    instruction="추가적인 설명 없이 'get_final_markdown' 도구를 호출하여 최종 완성된 마크다운을 획득하고 사용자에게 그대로 출력하세요.",
    tools=[get_final_markdown],
    # before_model_callback=formatter_callback,
)

# Writer -> Parallel -> Formatter 순으로 강제 실행
storybook_workflow = SequentialAgent(
    name="StoryBookWorkflow",
    description="동화책 제작 파이프라인",
    sub_agents=[writer_agent, parallel_illustrator, formatter_agent],
)

# adk web 엔트리 포인트
root_agent = storybook_workflow
