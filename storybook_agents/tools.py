import base64
import json
import logging
import os
from pathlib import Path
from typing import List

from dotenv import load_dotenv
from google import genai
from google.adk.tools import ToolContext
from google.genai import types
from openai import OpenAI
from pydantic import BaseModel

from .models import StoryPage, shared_state

load_dotenv()


# ✨ ADK Web의 Artifacts 저장 경로 설정 (프로젝트 루트의 artifacts 폴더)
ARTIFACTS_DIR = Path("artifacts")
ARTIFACTS_DIR.mkdir(exist_ok=True)  # 폴더가 없으면 자동 생성


def generate_image_with_vertex(prompt: str) -> str:
    """Google Vertex AI (Imagen 3)를 사용하여 이미지를 생성합니다."""
    # 환경 변수에 GOOGLE_API_KEY 또는 Vertex AI 자격 증명이 설정되어 있어야 합니다.
    client = genai.Client()
    try:
        result = client.models.generate_images(
            model="imagen-3.0-generate-001",
            prompt=f"A warm, watercolor children's book illustration of: {prompt}",
            config=types.GenerateImagesConfig(
                number_of_images=1, output_mime_type="image/jpeg", aspect_ratio="4:3"
            ),
        )
        # ✨ API가 반환한 원본 바이트 데이터 추출
        return result.generated_images[0].image.image_bytes
    except Exception as e:
        logging.error(f"Error with Vertex AI: {e}")
        return None


def generate_image_with_openai(prompt: str) -> str:
    """OpenAI (GPT Image or DALL-E 3)를 사용하여 이미지를 생성합니다."""
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    try:
        response = client.images.generate(
            model="gpt-image-1-mini",  # gpt-image-1-mini or dall-e-3
            prompt=f"A warm, watercolor children's book illustration of: {prompt}",
            size="1024x1024",
            quality="low",
            n=1,
        )
        # ✨ Base64 문자열을 파이썬 바이트(bytes) 객체로 디코딩
        return base64.b64decode(response.data[0].b64_json)
    except Exception as e:
        logging.error(f"Error with OpenAI: {e}")
        return None


def generate_image_tool(visual_description: str, provider: str) -> str:
    """설정된 provider에 따라 이미지 생성 API를 라우팅합니다."""
    print(f"[{provider.upper()}] 이미지 생성 도구 호출 중...")
    if provider == "openai":
        return generate_image_with_openai(visual_description)
    else:
        return generate_image_with_vertex(visual_description)


def set_story_theme(theme: str) -> str:
    """[Manager 도구] 사용자가 요청한 동화책의 테마를 State에 저장합니다."""
    shared_state.theme = theme
    return f"테마가 '{theme}'(으)로 설정되었습니다. 다음 작업을 진행하세요."


# ✨ 1. OpenAI가 완벽하게 이해할 수 있도록 명시적인 입력 스키마 정의
class SavePagesInput(BaseModel):
    pages: List[StoryPage]


# ✨ 2. List[Dict] 대신 명확한 Pydantic 모델(SavePagesInput)을 받도록 수정
def save_story_pages(data: SavePagesInput) -> str:
    """[Writer 도구] 생성된 스토리(List)를 받아 State에 저장합니다."""
    try:
        # json.loads() 제거: LLM이 이미 리스트 형태로 데이터를 넘겨줍니다.
        # shared_state.pages = [StoryPage(**item) for item in pages_data]
        shared_state.pages = data.pages

        # ✨ LLM이 다음 단계로 넘어가도록 명확한 행동 지침 반환
        return f"성공: {len(shared_state.pages)}페이지 분량의 스토리가 State에 저장되었습니다. 이제 즉시 도구 사용을 멈추고 작업을 종료하세요."
    except Exception as e:
        return f"실패 (데이터 형식을 확인하세요): {e}"


def get_current_story() -> str:
    """[Illustrator 도구] 현재 State에 저장된 스토리 데이터를 가져옵니다."""
    if not shared_state.pages:
        return "아직 작성된 스토리가 없습니다. WriterAgent의 작업이 끝날 때까지 대기하세요."
    return json.dumps([p.dict() for p in shared_state.pages], ensure_ascii=False)


async def generate_all_images(tool_context: ToolContext) -> str:
    """현재 State에 있는 모든 페이지의 삽화를 한 번에 생성하고 ADK Artifact로 저장합니다."""
    if not shared_state.pages:
        return "실패: 스토리가 없습니다. WriterAgent의 작업을 먼저 완료하세요."

    print("\n[Illustrator] 전체 페이지 이미지 생성 및 Artifact 저장 시작...")

    for page in shared_state.pages:
        print(f"--- Page {page.page_number} 이미지 작업 중 ---")

        try:
            # API 호출로 이미지 원본 바이트 데이터 획득 (requests 로직 제거됨)
            image_bytes = generate_image_tool(
                page.visual_description, shared_state.image_provider
            )

            # 방어 로직: API가 실패해서 None이 넘어왔다면 터지지 않고 부드럽게 건너뛰기
            if not image_bytes:
                print(
                    f"❌ Page {page.page_number} 이미지 생성 실패. 저장을 건너뜁니다."
                )
                page.image_url = "[이미지 생성 실패]"
                continue

            # ADK 공식 Artifact 저장 로직 (바이트 데이터를 그대로 밀어넣음)
            filename = f"page_{page.page_number}.png"
            artifact_part = types.Part(
                inline_data=types.Blob(
                    data=image_bytes,
                    mime_type="image/png",
                )
            )

            # ADK가 내부적으로 DB와 파일 시스템을 관리하며 저장해 줍니다.
            version = await tool_context.save_artifact(
                filename=filename, artifact=artifact_part
            )

            # State 업데이트
            page.image_url = filename
            print(f"✅ Artifact 저장 완료: {filename} (버전: {version})")

        except Exception as e:
            print(f"❌ 생성/저장 실패: {e}")
            page.image_url = f"[에러: {e}]"

    return "성공: 모든 페이지의 이미지가 생성되고 ADK Artifacts에 저장되었습니다."


def get_final_markdown() -> str:
    """[Manager 도구] 모든 작업 완료 후, State의 데이터를 조합하여 최종 Markdown을 반환합니다."""
    if not shared_state.pages:
        return "출력할 스토리가 없습니다."

    result_markdown = f"# 📖 동화책: {shared_state.theme}\n\n"
    for page in shared_state.pages:
        result_markdown += f"## Page {page.page_number}\n\n"
        result_markdown += f"{page.text}\n\n"
        result_markdown += f"> **삽화 지시문**: {page.visual_description}\n"
        result_markdown += f"> **생성된 이미지**: {page.image_url}\n\n"
        result_markdown += "---\n"
    return result_markdown
