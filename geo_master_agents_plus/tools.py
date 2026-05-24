# =====================================================================
# 1. Python Default
# =====================================================================
import ast
import base64
import gettext
import io
import json
import logging
import os

# =====================================================================
# 2. Installed Packages
# =====================================================================
import fal_client
import pycountry
import requests
from dotenv import load_dotenv
from google import genai
from google.genai import types
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from langchain_tavily import TavilySearch
from PIL import Image, ImageDraw, ImageFont
from tenacity import retry, stop_after_attempt, wait_exponential

# =====================================================================
# 3. Custom Files
# =====================================================================
from data import GEO_ALIASES, GEO_METADATA
from services import (
    generate_cache_key_for_search,
    get_image_url,
    get_kv_cache,
    insert_cartoon_info,
    set_kv_cache,
    upload_image_to_r2,
)

# .env 파일 로드
load_dotenv()

# 로깅 설정 (재시도 상황을 터미널에서 보기 위함)
logger = logging.getLogger(__name__)


def get_llm_client():
    """LLM 인스턴스를 반환하는 헬퍼 함수 (필요 시 모델이나 설정을 동적으로 변경 가능)"""
    llm_provider = os.getenv("LLM_PROVIDER")
    llm = None

    if llm_provider == "google":
        # llm = ChatGoogleGenerativeAI(model="gemini-3.5-flash", temperature=0)
        # llm = ChatGoogleGenerativeAI(model="gemini-3.1-flash-lite", temperature=0)
        llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)
    elif llm_provider == "anthropic":
        # llm = ChatAnthropic(model="claude-opus-4.5", temperature=0)
        # llm = ChatAnthropic(model="claude-sonnet-4.5", temperature=0)
        llm = ChatAnthropic(model="claude-haiku-4.5", temperature=0)
    else:
        # llm = ChatOpenAI(model="gpt-5-nano", temperature=0)
        # llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
        llm = ChatOpenAI(model="gpt-3.5-turbo", temperature=0)

    return llm


# 지오 마스터 에이전트 전용 LLM 정의
llm = get_llm_client()


def get_domain_keyword(input: str) -> str:
    """도메인 명을 한글로 리턴해 주는 함수"""
    domain_keywords = {
        "economy": "경제",
        "culture": "문화",
        "education": "교육",
        "science": "과학기술",
        "military": "방산",
    }
    return domain_keywords.get(input, "교육")


def get_country_map():
    """
    pycountry를 기반으로 '한글/영문/국가코드/통칭 -> 영어 공식 국가명'
    통합 맵핑 딕셔너리를 생성합니다. (대소문자 무시를 위해 모든 키를 소문자로 저장)
    """
    ko_lang = gettext.translation(
        "iso3166-1", pycountry.LOCALES_DIR, languages=["ko"], fallback=True
    )

    country_map = {}
    for country in pycountry.countries:
        # 해당 국가의 지리 데이터 가져오기 (없으면 기본값 세팅)
        geo_info = GEO_METADATA.get(
            country.alpha_2, {"lat": 20.0, "lon": 0.0, "zoom": 1}
        )

        # UI나 Pydeck에서 쓰기 좋게 묶어줍니다.
        country_data = {
            "name": country.name,  # 공식 영문명
            "alpha_2": country.alpha_2,  # 2자리 코드
            "lat": geo_info["lat"],
            "lon": geo_info["lon"],
            "zoom": geo_info["zoom"],
        }

        # 한국어 이름 매핑
        ko_name = ko_lang.gettext(country.name)
        country_map[ko_name.lower()] = country_data

        # 영어 기본 이름 매핑 (예: "united states", "south korea")
        country_map[country.name.lower()] = country_data

        # 2자리/3자리 국가 코드 매핑 (예: "us", "usa", "kr", "kor")
        country_map[country.alpha_2.lower()] = country_data
        country_map[country.alpha_3.lower()] = country_data

        # 공식 명칭이 따로 있다면 그것도 추가 (예: "republic of korea")
        if hasattr(country, "official_name"):
            country_map[country.official_name.lower()] = country_data

    # 사람들이 자주 쓰는 글로벌 통칭 및 약어 수동 보완
    for k, v in GEO_ALIASES.items():
        target_key = v.lower()

        # v(예: "United States")를 소문자로 바꿔서 이미 만들어진 딕셔너리가 있는지 찾습니다.
        if target_key in country_map:
            # 문자열이 아니라, 찾아낸 딕셔너리 전체를 연결합니다!
            country_map[k.lower()] = country_map[target_key]
        else:
            # 만약 못 찾는다면 에러 방지용 기본 딕셔너리를 넣어줍니다.
            country_map[k.lower()] = {
                "name": v,
                "alpha_2": "",
                "lat": 20.0,
                "lon": 0.0,
                "zoom": 1,
            }

    return country_map


# Tool 1: 이슈 검색 (Tavily 활용)
def get_refined_issues(
    domain: str,
    country: str,
    years: int,
    top_n: int = 5,
    user_id: int = None,
    language: str = "Korean",
) -> list:
    """
    검색 도구와 LLM을 결합하여 정제된 Top 5 이슈 목록을 반환합니다.
    """
    # Step A: 도메인 프롬프트 정의
    domain_prompts_kr = {
        "economy": "경제 성장, 산업 혁신, 무역 협력, 투자 유치 등 경제적으로 중요한 이슈",
        "culture": "대중문화(음악, 영화, 푸드 등)의 세계적 확산, 전통 문화 교류, 소프트파워 강화, 주요 문화적 성취 등 문화적으로 의미 있는 이슈",
        "education": "교육 교류, 유학 트렌드, 교육 시스템 혁신, 주요 대학 협력 등 교육적으로 가치 있는 이슈",
        "science": "첨단 기술(AI, IT 등) 발전, 우주 탐사, 의료 및 생명공학 혁신, 국제 과학 기술 협력 등 과학기술 분야의 핵심 이슈",
        "military": "국방력 강화, 군사 동맹 및 조약 체결, 첨단 무기 개발 및 수출, 지정학적 안보 등 군사 및 외교적으로 중요한 이슈",
    }
    domain_prompts_en = {
        "economy": "Economic growth, industrial innovation, international trade cooperation, foreign investment attraction, and major economic developments",
        "culture": "Global spread of pop culture (music, film, food, etc.), traditional cultural exchange, strengthening of soft power, and major cultural achievements",
        "education": "International education exchange, academic cooperation, and educational system reforms",
        "science": "Advancements in high-tech (AI, IT, etc.), space exploration, medical and biotech innovations, and international scientific cooperation",
        "military": "Strengthening of defense capabilities, military alliances and treaties, advanced weapons development, and major geopolitical security issues",
    }

    # Step B: Raw 데이터 검색 (캐싱 로직 적용)
    cache_key = generate_cache_key_for_search(domain, country, years)
    cache_val = get_kv_cache(cache_key)

    if isinstance(cache_val, list):
        row = json.loads(cache_val[0]) if len(cache_val) > 0 else None
    else:
        row = cache_val

    search_results = []

    if row:
        print(f"\n⚡ [Cache Hit] '{cache_key}' 조건의 캐시된 검색 결과를 불러옵니다.")

        # 1. 최근 테스트로 인해 리스트 형태로 캐시된 경우 ( [search_results, issue_ids] )
        if isinstance(row, list):
            search_results = row[0]

        # 2. 과거 딕셔너리 형태로 캐시된 경우
        elif isinstance(row, dict):
            try:
                search_results = list(row.values())[0]
            except json.JSONDecodeError:
                # 2차 시도: 파이썬 리스트 문자열("['이슈1', '이슈2']")로 저장된 경우 복원
                try:
                    parsed_data = ast.literal_eval(search_results)
                    search_results = parsed_data[0]
                    # issue_ids = parsed_data[1]
                except Exception:
                    # 3. 최후의 수단: 알 수 없는 문자열인 경우 에러 방지를 위해 강제 리스트화
                    search_results = [search_results]
            except Exception:
                search_results = row

        # 3. 그 외 (정상적인 텍스트나 단일 리스트)
        else:
            search_results = row

    else:
        print(f"\n🌐 [Cache Miss] '{cache_key}' 조건의 데이터를 새로 검색합니다...")
        search_tool = TavilySearch(max_results=10)
        search_query = (
            f"{domain_prompts_en[domain]} of {country} in the last {years} years"
        )
        search_results = search_tool.invoke({"query": search_query})

        # 순수하게 Tavily 검색 결과만 캐싱합니다.
        set_kv_cache(cache_key, search_results)

    # Step C: 검색 결과 정리 with 데이터 타입 체크
    if isinstance(search_results, str):
        context = search_results
    elif isinstance(search_results, dict) and "content" in search_results:
        context = "\n".join([f"- {res.get('content', res)}" for res in search_results])
    elif isinstance(search_results, list):
        # search_results가 딕셔너리의 리스트일 경우 안전하게 파싱
        context = "\n".join(
            [
                f"- {res.get('content', res) if isinstance(res, dict) else res}"
                for res in search_results
            ]
        )
    else:
        context = "\n".join([f"- {res}" for res in search_results])

    # Step D: LLM 필터링 및 요약
    prompt = f"""
    당신은 글로벌 {get_domain_keyword(domain)} 전문가입니다. 
    {country}의 최근 {years}년 동안의 {domain} 관련 검색 결과를 분석하세요.
    {domain_prompts_kr[domain]} 중에서 {top_n}개를 선정해 주세요.

    [출력 규칙]
    1. 반드시 숫자로 시작하는 리스트 형식으로만 응답하세요.
    2. "다음은 이슈 목록입니다"와 같은 서론이나 인사말을 절대로 포함하지 마세요.
    3. 각 이슈는 'n. yyyy: [주제] - [설명]' 포맷을 엄격히 준수하세요.
    4. 주제와 설명 내용은 반드시 {language} 언어 중심으로 표현하세요.
    5. 도메인 별로 가치 있는 핵심 이슈 5개(최대)를 선정하세요.

    검색 결과:
    {context}
    """
    response = llm.invoke([HumanMessage(content=prompt)])

    # Step D: 결과 파싱 및 리스트화
    raw_content = response.content

    # 1. Gemini가 리스트 형태로 반환할 경우 텍스트만 안전하게 추출
    if isinstance(raw_content, list):
        text_content = "\n".join(
            [
                item.get("text", "") if isinstance(item, dict) else str(item)
                for item in raw_content
            ]
        )
    else:
        text_content = str(raw_content)

    # 2. 추출된 문자열을 기반으로 리스트 생성
    issues = [line.strip() for line in text_content.split("\n") if line.strip()]
    return issues[:10]


def log_retry_attempt(retry_state):
    logger.warning(
        f"⚠️ Gemini API 503 지연 발생! {retry_state.attempt_number}번째 재시도 중... "
        f"(대기 시간: {retry_state.idle_for}초)"
    )


def handle_retry_error(retry_state):
    """모든 재시도(4회) 실패 시 호출되는 콜백 함수"""
    # 에이전트가 죽지 않도록, 실패했다는 '상태 정보'를 딕셔너리로 반환합니다.
    return {
        "status": "error",
        "fallback_text": "🚦 구글 서버(Gemini)에 요청이 너무 많아 대기 시간이 초과되었습니다. 1~2분 뒤 다시 시도해 주세요!",
    }


# Tool 1a: 이미지 생성 (FAL API) + D1 메타데이터 저장 -> 한글 텍스트 합성이 필요할 경우, nano banana 모델 선택 권장
def generate_single_image_with_fal(
    prompt: str, issue_id: int, language: str | None = "Korean"
) -> dict:
    """fal.ai를 사용하여 웹툰 이미지를 초고속으로 생성하고 URL을 반환합니다."""

    # 환경 변수가 잘 로드되었는지 안전장치
    if not os.getenv("FAL_API_KEY"):
        print("🚨 FAL_API_KEY 환경 변수가 설정되지 않았습니다.")
        return None

    # fal_client가 자동으로 읽어갈 수 있도록 FAL_KEY 환경변수에 값을 주입합니다.
    # client = fal_client(api_key=os.getenv("FAL_API_KEY"))
    os.environ["FAL_KEY"] = os.getenv("FAL_API_KEY")

    models = (
        "flux/schnell",  # 가성비 최상, 초고속 생성 (1~4 steps 권장)
        "ideogram/v2-turbo",  # 타이포그래피와 포스터 디자인, 텍스트 합성에 세계 최고 수준으로 특화
        "stable-diffusion-3.5-large",  # 이전 SDXL 버전에 비해 텍스트 인코더가 강화
        "nano-banana-2",  # 이전 세대보다 프롬프트 이해도와 다국어 텍스트 렌더링 성능이 대폭 업그레이드
        "nano-banana-pro",  # 구도, 빛의 표현, 아주 복잡한 한글 문장 합성에 영혼을 갈아 넣은 최상위 모델
    )
    selected_model = f"fal-ai/{models[3]}"

    try:
        # 모델에게 '배경 삽화'만 그리도록 명확히 지시하는 프롬프트로 수정합니다.
        prompt = (
            f"A professional historical educational cartoon style illustration of: {prompt}. "
            f"Aspect Ratio: 1:1. Square format. "
            f"Please render the text in {language} precisely and beautifully within the image."
            if language
            else "No text rendering needed."
        )

        # fal_client.subscribe는 대기열(Queue)과 폴링을 자동으로 처리해줍니다.
        # result = client.subscribe(
        result = fal_client.subscribe(
            selected_model,
            arguments={
                "prompt": prompt,
                "image_size": "square_hd",  # 옵션: landscape_4_3, portrait_4_3 등 설정 가능
                "num_inference_steps": 4,  # 속도를 위해 스텝 수를 낮춤 (모델에 따라 다름)
            },
        )

        # 반환된 결과에서 이미지 URL 추출
        image_url = result["images"][0]["url"]

        if image_url:
            insert_cartoon_info(prompt, image_url, issue_id)

            return {
                "status": "success",
                "file": image_url,
                "model": selected_model,
            }
        else:
            raise ValueError("응답에 이미지 데이터가 포함되어 있지 않습니다.")

    except Exception as e:
        error_msg = str(e)
        print(f"⚠️ fal.ai 이미지 생성 실패: {error_msg}")
        return {"status": "error", "fallback_text": error_msg}


# Tool 1b: 이미지 생성 (FAL API + Pillow Text Overay) + R2 업로드 + D1 메타데이터 저장
def generate_single_image2_with_fal(
    prompt: str, issue_id: int, language: str | None = None
) -> dict:
    """fal.ai를 사용하여 웹툰 이미지를 초고속으로 생성하고 URL을 반환합니다."""

    # 환경 변수가 잘 로드되었는지 안전장치
    if not os.getenv("FAL_API_KEY"):
        print("🚨 FAL_API_KEY 환경 변수가 설정되지 않았습니다.")
        return None
    client = fal_client(api_key=os.getenv("FAL_API_KEY"))

    models = (
        "flux/schnell",  # 가성비 최상, 초고속 생성 (1~4 steps 권장)
        "flux/dev",  # 고품질/디테일 특화 (비용/시간 약간 증가)
        "fast-sdxl",  # 매우 빠르고 저렴한 SDXL 기반 모델
        "seedream",  # 일러스트/애니메이션 스타일에 특화
    )
    selected_model = f"fal-ai/{models[0]}"

    try:
        # 모델에게 '배경 삽화'만 그리도록 명확히 지시하는 프롬프트로 수정합니다.
        prompt = (
            f"A professional historical educational cartoon style illustration of: {prompt}. "
            f"Aspect Ratio: 1:1. Square format. "
            f"Please render the text in {language} precisely and beautifully within the image."
            if language
            else "No text rendering needed."
        )

        # fal_client.subscribe는 대기열(Queue)과 폴링을 자동으로 처리해줍니다.
        result = client.subscribe(
            selected_model,
            arguments={
                "prompt": prompt,
                "image_size": "square_hd",  # 옵션: landscape_4_3, portrait_4_3 등 설정 가능
                "num_inference_steps": 4,  # 속도를 위해 스텝 수를 낮춤 (모델에 따라 다름)
            },
        )

        # 반환된 결과에서 이미지 URL 추출
        image_url = result["images"][0]["url"]

        if image_url:
            # --- 한글 텍스트 합성을 위한 로직 추가 ---
            # 1. fal.ai에서 생성된 원본 이미지 다운로드
            img_response = requests.get(image_url)
            img_response.raise_for_status()
            pil_image = Image.open(io.BytesIO(img_response.content))

            # 2. Pillow를 사용하여 한글 텍스트 합성
            draw = ImageDraw.Draw(pil_image)
            try:
                font = ImageFont.truetype("NanumGothic.ttf", 40)
            except IOError:
                # 폰트 파일이 없을 경우 대비 (로컬 환경에 맞춰 폰트명 변경 권장)
                font = ImageFont.load_default()

            title_text = prompt.split(":")[1].strip() if ":" in prompt else prompt[:20]

            # 텍스트 크기 계산 (Pillow 버전에 따른 호환성 처리)
            try:
                w, h = draw.textsize(title_text, font=font)
            except AttributeError:
                left, top, right, bottom = draw.textbbox((0, 0), title_text, font=font)
                w, h = right - left, bottom - top

            W, H = pil_image.size
            # 텍스트 가독성을 위해 흰색 글씨에 검은색 테두리(stroke) 적용
            draw.text(
                ((W - w) / 2, H - h - 30),
                title_text,
                font=font,
                fill="white",
                stroke_width=2,
                stroke_fill="black",
            )

            # 3. 합성된 이미지를 R2에 업로드
            output_buffer = io.BytesIO()
            pil_image.save(output_buffer, format="PNG")
            file_name = f"image_{abs(hash(prompt))}.png"
            upload_image_to_r2(file_name, output_buffer.getvalue())

            # 4. R2 Public URL 가져오기
            final_image_url = get_image_url(
                file_name, public_domain=os.getenv("CF_R2_PUBLIC_GEO_MASTER_URL")
            )

            # 5. 생성된 최종 이미지 URL과 메타데이터를 D1에 저장
            insert_cartoon_info(prompt, final_image_url, issue_id)

            return {
                "status": "success",
                "file": final_image_url,
                "model": f"{selected_model} + Pillow",
            }
        else:
            raise ValueError("응답에 이미지 데이터가 포함되어 있지 않습니다.")

    except Exception as e:
        error_msg = str(e)
        print(f"⚠️ fal.ai 이미지 생성 실패: {error_msg}")
        return {"status": "error", "fallback_text": error_msg}


# Tool 2a: 이미지 생성 (Nano Banana) + R2 업로드 + D1 메타데이터 저장
# ---------------------------------------------------------
# 🚨 총 4번 재시도, 3초/6초/12초 간격으로 점진적 대기
# ---------------------------------------------------------
@retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=2, min=3, max=15),
    after=log_retry_attempt,
    reraise=True,  # 모든 재시도 실패 시 최종 에러 반환
    retry_error_callback=handle_retry_error,  # 👈 실패 시 죽지 않고 대체 값 반환
)
def generate_single_image(
    prompt: str, issue_id: int, language: str | None = "Korean"
) -> dict:
    """
    Nano Banana를 사용하여 한글이 포함된 고해상도 교육 삽화를 생성합니다.
    """
    client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

    models = (
        "nano-banana-pro-preview",
        "gemini-3.1-pro-image-preview",
        "gemini-3.1-flash-image-preview",
        "gemini-2.5-flash-image-preview",
    )
    selected_model = f"models/{models[2]}"

    try:
        # 이미지 생성 (Nano Banana 2) 예시
        response = client.models.generate_content(
            model=selected_model,
            contents=(
                f"A professional historical educational cartoon style illustration of: {prompt}. "
                f"Aspect Ratio: 1:1. Square format. "
                f"Please render the text in {language} precisely and beautifully within the image."
                if language
                else "No text rendering needed."
            ),
        )
        image_part = response.candidates[0].content.parts[0]

        if hasattr(image_part, "inline_data"):
            file_name = f"image_{abs(hash(prompt))}.png"
            image_bytes = image_part.inline_data.data

            # 로컬 저장 대신 R2 업로드 함수 호출
            upload_image_to_r2(file_name, image_bytes)

            # Streamlit이나 UI에 전달할 수 있도록 접근 가능한 URL 생성
            image_url = get_image_url(
                file_name, public_domain=os.getenv("CF_R2_PUBLIC_GEO_MASTER_URL")
            )

            # 생성된 이미지 URL과 메타데이터를 D1에 저장
            insert_cartoon_info(prompt, image_url, issue_id)

            return {
                "status": "success",
                "file": image_url,
                "model": selected_model,
            }
        else:
            raise ValueError("응답에 이미지 데이터가 포함되어 있지 않습니다.")

    except Exception as e:
        error_msg = str(e)
        print(f"⚠️ gemini 이미지 생성 실패: {error_msg}")

        # 💡 503 에러이거나 "고부하(high demand)" 관련 에러일 경우,
        # Exception을 발생(raise)시켜야 tenacity가 "아, 실패했구나! 다시 시도하자"라고 인식합니다.
        if (
            "503" in error_msg
            or "high demand" in error_msg
            or "UNAVAILABLE" in error_msg
        ):
            raise e  # 👈 tenacity에게 재시도를 요청하기 위해 에러를 다시 던집니다.

        # 그 외의 심각한 에러(예: API 키 오류 등)는 재시도하지 않고 바로 실패 반환
        return {"status": "error", "fallback_text": error_msg}


# Tool 2b: 이미지 생성 (Imagen 4 + Pillow Text Overay) + R2 업로드 + D1 메타데이터 저장
def generate_single_image2(
    prompt: str, issue_id: int, language: str | None = None
) -> dict:
    """
    Imagen으로 배경 이미지를 생성하고, Pillow로 한글 타이틀을 완벽하게 합성합니다.
    """
    client = genai.Client(api_key=os.getenv("GOOGLE_VERTEX_API_KEY"))

    models = (
        "imagen-4.0-ultra-generate-001",
        "imagen-4.0-generate-001",
        "imagen-4.0-fast-generate-001",
    )
    selected_model = f"models/{models[2]}"

    try:
        # 1. 모델은 '배경 삽화'만 그립니다. (한글 생성 명령 제외)
        response = client.models.generate_images(
            model=selected_model,
            prompt=(
                f"A professional historical educational cartoon style illustration of: {prompt}. "
                f"Aspect Ratio: 1:1. Square format. "
                f"Please render the text in {language} precisely and beautifully within the image."
                if language
                else "No text rendering needed."
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

        # 합성된 이미지를 R2에 업로드
        output_buffer = io.BytesIO()
        pil_image.save(output_buffer, format="PNG")
        file_name = f"image_{abs(hash(prompt))}.png"
        upload_image_to_r2(file_name, output_buffer.getvalue())

        # R2 Public URL 가져오기
        final_image_url = get_image_url(
            file_name, public_domain=os.getenv("CF_R2_PUBLIC_GEO_MASTER_URL")
        )

        # 생성된 최종 이미지 URL과 메타데이터를 D1에 저장
        insert_cartoon_info(prompt, final_image_url, issue_id)

        return {
            "status": "success",
            "file": final_image_url,
            "model": f"{selected_model} + Pillow",
        }

    except Exception as e:
        logging.error(f"API 에러: {e}")

        return {
            "status": "filtered",
            "fallback_text": "안전 정책 또는 API 오류로 인해 이미지 생성이 차단되었습니다.",
            "reason": f"Safety filters or API error: {e}",
        }


def get_image_base64(img_path):
    """로컬 이미지를 HTML에서 띄우기 위해 Base64로 변환하거나 URL을 그대로 반환합니다."""
    if not img_path:
        return ""
    if img_path.startswith("http"):  # 웹 URL인 경우 그대로 반환
        return img_path
    elif os.path.exists(img_path):  # 로컬 파일인 경우 Base64 인코딩
        with open(img_path, "rb") as f:
            data = f.read()
        return f"data:image/jpeg;base64,{base64.b64encode(data).decode()}"
    return ""


def speech_to_text_with_elevenlabs(audio_file) -> str:
    """ElevenLabs API(Scribe)를 사용하여 음성을 텍스트로 변환(STT)합니다."""
    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        print("ELEVENLABS_API_KEY가 설정되지 않았습니다.")
        return None

    url = "https://api.elevenlabs.io/v1/speech-to-text"
    headers = {"xi-api-key": api_key}
    data = {"model_id": "scribe_v1", "language_code": "ko"}
    files = {"file": ("audio.wav", audio_file, "audio/wav")}

    try:
        response = requests.post(url, headers=headers, data=data, files=files)
        if response.status_code == 200:
            return response.json().get("text")
        else:
            print(f"ElevenLabs STT 에러: {response.text}")
            return None
    except Exception as e:
        print(f"STT 통신 에러: {e}")
        return None


def text_to_speech_with_elevenlabs(text: str) -> bytes:
    """ElevenLabs API를 사용하여 텍스트를 음성(MP3) 바이트로 변환(TTS)합니다."""
    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        return None

    # 원하는 다국어 지원 보이스 ID로 변경 가능 (default: Rachel)
    voice_id = os.getenv("ELEVENLABS_VOICE_ID")
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"

    headers = {
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
        "xi-api-key": api_key,
    }
    data = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
    }

    try:
        response = requests.post(url, json=data, headers=headers)
        if response.status_code == 200:
            return response.content
        return None
    except Exception:
        return None
