import base64
import io
import logging
import os

from dotenv import load_dotenv
from google import genai
from google.genai import types
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from langchain_tavily import TavilySearch
from openai import OpenAI
from PIL import Image, ImageDraw, ImageFont

# .env 파일 로드
load_dotenv()

# 지오 마스터 에이전트 전용 LLM 정의
llm = ChatOpenAI(
    model="gpt-4o-mini",
    temperature=0,  # 추론의 일관성을 위해 0으로 설정
    max_retries=2,  # API 호출 실패 시 재시도 횟수
)


# Tool 1: 교육 이슈 검색 (Tavily 활용)
def get_refined_issues(country: str, years: int):
    """
    검색 도구와 LLM을 결합하여 정제된 Top 5 이슈 목록을 반환합니다.
    """
    # Step A: Raw 데이터 검색
    search_tool = TavilySearch(max_results=10)
    search_query = f"International education exchange, academic cooperation, and educational system reforms of {country} in the last {years} years"
    search_results = search_tool.invoke({"query": search_query})

    # Step B: 검색 결과 텍스트 결합 (데이터 타입 체크 추가)
    # context = "\n".join([f"- {res['content']}" for res in search_results])
    if isinstance(search_results, str):
        context = search_results
    else:
        # 만약 리스트로 반환된다면 기존처럼 처리하되 안전하게 get() 사용
        context = "\n".join(
            [
                f"- {res.get('content', res)}" if isinstance(res, dict) else f"- {res}"
                for res in search_results
            ]
        )

    # Step C: LLM 필터링 및 요약
    prompt = f"""
    당신은 글로벌 교육 전문가입니다. {country}의 최근 {years}년 동안의 교육 관련 검색 결과를 분석하세요.
    국가 간 교육 교류, 유학 트렌드, 교육 시스템 혁신, 주요 대학 협력 등 교육적으로 가치 있는 이슈 5개를 선정해 주세요.
    
    [출력 규칙]
    1. 반드시 숫자로 시작하는 리스트 형식으로만 응답하세요.
    2. "다음은 이슈 목록입니다"와 같은 서론이나 인사말을 절대로 포함하지 마세요.
    3. 각 이슈는 'n. yyyy: [주제명] - [설명]' 포맷을 엄격히 준수하세요.
    4. 교육적으로 가치 있는 핵심 이슈 5개(최대)를 선정하세요.

    검색 결과:
    {context}
    """
    response = llm.invoke([HumanMessage(content=prompt)])

    # Step D: 결과 파싱 및 리스트화
    issues = [line.strip() for line in response.content.split("\n") if line.strip()]
    return issues[:10]


# Tool 2a: 이미지 생성 (DALL-E 3 or GPT Image 활용)
def generate_single_image(prompt: str) -> str:
    """개별 이슈에 대해 이미지를 생성하고 결과를 안전하게 처리합니다."""
    client = OpenAI()

    try:
        response = client.images.generate(
            # model="dall-e-3",
            model="gpt-image-1-mini",
            prompt=(
                f"A professional historical educational cartoon style illustration of: {prompt}. "
                f"Aspect Ratio: 1:1. Square format. "
                f"Please render the Korean text precisely and beautifully."
            ),
            size="1024x1024",
            quality="medium",
            n=1,
        )

        download_dir = "downloads"
        os.makedirs(download_dir, exist_ok=True)
        file_name = f"image_{abs(hash(prompt))}.png"
        file_path = os.path.join(download_dir, file_name)

        image_bytes = base64.b64decode(response.data[0].b64_json)
        with open(file_path, "wb") as f:
            f.write(image_bytes)

        return {
            "status": "success",
            "file": file_name,
            "model": "gpt-image-1-mini",
        }

    except Exception as e:
        # 세이프티 시스템에 의해 차단된 경우 (Error 400 등)
        logging.warning(f"API 에러: {e}")

        return {
            "status": "filtered",
            "fallback_text": "안전 정책상 이미지를 생성할 수 없어 텍스트 요약으로 대체합니다.",
            "reason": "Safety filters or API error",
        }


# Tool 2b: 이미지 생성 (Imagen 4 + Pillow Text Overay 활용)
def generate_single_image2(prompt: str) -> dict:
    """
    Imagen 4로 배경 이미지를 생성하고,
    Pillow로 한글 타이틀을 완벽하게 합성합니다.
    """
    client = genai.Client()

    try:
        # 1. 모델은 '배경 삽화'만 그립니다. (한글 생성 명령 제외)
        response = client.models.generate_images(
            # model="models/imagen-4.0-ultra-generate-001",
            # model="models/imagen-4.0-generate-001",
            model="models/imagen-4.0-fast-generate-001",
            prompt=(
                f"A professional historical educational cartoon style illustration of: {prompt}. "
                f"Aspect Ratio: 1:1. Square format. "
                f"Please render the Korean text precisely and beautifully."
            ),
            config=types.GenerateImagesConfig(
                number_of_images=1,
                output_mime_type="image/png",
            ),
        )

        # 2. 원본 이미지 저장
        download_dir = "downloads"
        os.makedirs(download_dir, exist_ok=True)
        file_name = f"image_{abs(hash(prompt))}.png"
        file_path = os.path.join(download_dir, file_name)

        image_bytes = response.generated_images[0].image.image_bytes
        with open(file_path, "wb") as f:
            f.write(image_bytes)

        # 3. 한글 텍스트 합성 (Pillow)
        pil_image = Image.open(io.BytesIO(image_bytes))
        draw = ImageDraw.Draw(pil_image)
        # 나눔고딕 등 로컬 한글 폰트 경로 설정 (필수)
        font = ImageFont.truetype("NanumGothic.ttf", 30)

        # 이슈 타이틀에서 핵심 문구 추출 (예: "STEM 교육 혁신")
        title_text = prompt.split(":")[1].strip()

        # 이미지 하단 중앙에 깔끔하게 합성
        W, H = pil_image.size
        w, h = draw.textsize(title_text, font=font)
        draw.text(((W - w) / 2, H - h - 20), title_text, font=font, fill="black")

        # 4. 합성된 이미지 저장
        file_name2 = f"image2_{abs(hash(prompt))}.png"
        file_path2 = os.path.join(download_dir, file_name2)
        pil_image.save(file_path2)

        return {
            "status": "success",
            "file": file_name2,
            "model": "Imagen 4 + Pillow",
        }

    except Exception as e:
        logging.error(f"API 에러: {e}")

        return {
            "status": "filtered",
            "fallback_text": prompt,
            "reason": "Safety filters or API error",
        }


# Tool 2c: 이미지 생성 (Nano Banana 2 활용)
def generate_single_image3(prompt: str) -> str:
    """
    Nano Banana 2(Gemini 3 Pro Image)를 사용하여
    한글이 포함된 고해상도 교육 삽화를 생성합니다.
    """
    client = genai.Client()

    try:
        # 이미지 생성 (Nano Banana 2) 예시
        response = client.models.generate_content(
            # model="models/nano-banana-pro-preview",
            model="models/gemini-3.1-flash-image-preview",
            contents=(
                f"A professional historical educational cartoon style illustration of: {prompt}. "
                f"Aspect Ratio: 1:1. Square format. "
                f"Please render the Korean text precisely and beautifully."
            ),
        )
        image_part = response.candidates[0].content.parts[0]

        if hasattr(image_part, "inline_data"):
            download_dir = "downloads"
            os.makedirs(download_dir, exist_ok=True)
            file_name = f"image_{abs(hash(prompt))}.png"
            file_path = os.path.join(download_dir, file_name)

            image_bytes = image_part.inline_data.data
            with open(file_path, "wb") as f:
                f.write(image_bytes)

            return {
                "status": "success",
                "file": file_name,
                "model": "Nano Banana 2",
            }
        else:
            raise ValueError("응답에 이미지 데이터가 포함되어 있지 않습니다.")

    except Exception as e:
        logging.error(f"API 에러: {e}")

        return {
            "status": "filtered",
            "fallback_text": prompt,
            "reason": "Safety filters or API error",
        }
