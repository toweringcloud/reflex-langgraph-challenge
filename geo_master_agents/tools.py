import ast
import base64
import gettext
import io
import json
import logging
import os
from typing import Any, Optional, Sequence, Tuple

import pycountry
import requests
from dotenv import load_dotenv
from google import genai
from google.genai import types
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from langchain_tavily import TavilySearch
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)
from openai import OpenAI
from PIL import Image, ImageDraw, ImageFont
from tenacity import retry, stop_after_attempt, wait_exponential
from utils import (
    generate_cache_key_for_search,
    get_image_url,
    get_kv_cache,
    insert_image_metadata,
    set_kv_cache,
    upload_image_to_r2,
)

# .env 파일 로드
load_dotenv()

# 로깅 설정 (재시도 상황을 터미널에서 보기 위함)
logger = logging.getLogger(__name__)


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


# 지오 마스터 에이전트 전용 LLM 정의
llm = ChatOpenAI(
    model="gpt-4o-mini",
    temperature=0,  # 추론의 일관성을 위해 0으로 설정
    max_retries=2,  # API 호출 실패 시 재시도 횟수
)


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


def get_global_country_map():
    """
    pycountry를 기반으로 '한글/영문/국가코드/통칭 -> 영어 공식 국가명'
    통합 맵핑 딕셔너리를 생성합니다. (대소문자 무시를 위해 모든 키를 소문자로 저장)
    """
    ko_lang = gettext.translation(
        "iso3166-1", pycountry.LOCALES_DIR, languages=["ko"], fallback=True
    )

    country_map = {}
    for country in pycountry.countries:
        # 1. 한국어 이름 매핑
        ko_name = ko_lang.gettext(country.name)
        country_map[ko_name.lower()] = country.name

        # 2. 영어 기본 이름 매핑 (예: "united states", "south korea")
        country_map[country.name.lower()] = country.name

        # 3. 2자리/3자리 국가 코드 매핑 (예: "us", "usa", "kr", "kor")
        country_map[country.alpha_2.lower()] = country.name
        country_map[country.alpha_3.lower()] = country.name

        # 4. 공식 명칭이 따로 있다면 그것도 추가 (예: "republic of korea")
        if hasattr(country, "official_name"):
            country_map[country.official_name.lower()] = country.name

    # 5. 사람들이 자주 쓰는 글로벌 통칭 및 약어 수동 보완
    aliases = {
        "대한민국": "Korea, Republic of",
        "한국": "Korea, Republic of",
        "남한": "Korea, Republic of",
        "south korea": "Korea, Republic of",
        "북한": "Democratic People's Republic of",
        "north korea": "Democratic People's Republic of",
        "미국": "United States",
        "영국": "United Kingdom",
        "러시아": "Russian Federation",
        "호주": "Australia",
        "뉴질랜드": "New Zealand",
        "스위스": "Switzerland",
    }

    # 수동 보완 데이터도 모두 소문자 키로 저장
    for k, v in aliases.items():
        country_map[k.lower()] = v

    return country_map


# Tool 1: 이슈 검색 (Tavily 활용)
def get_refined_issues(domain: str, country: str, years: int, top_n: int = 5) -> list:
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
    row = json.loads(cache_val) if cache_val else None

    if row:
        print(f"\n⚡ [Cache Hit] '{cache_key}' 조건의 캐시된 검색 결과를 불러옵니다.")

        # D1 API에서 첫 번째 컬럼의 값을 가져옵니다.
        raw_data = list(row.values())[0]

        try:
            # 1. 1차 시도: 표준 JSON으로 읽기
            search_results = json.loads(raw_data)
        except json.JSONDecodeError:
            # 2. 2차 시도: 파이썬 리스트 문자열("['이슈1', '이슈2']")로 저장된 경우 복원
            try:
                search_results = ast.literal_eval(raw_data)
            except Exception:
                # 3. 최후의 수단: 알 수 없는 문자열인 경우 에러 방지를 위해 강제 리스트화
                search_results = [raw_data]
    else:
        print(f"\n🌐 [Cache Miss] '{cache_key}' 조건의 데이터를 새로 검색합니다...")
        search_tool = TavilySearch(max_results=10)
        search_query = (
            f"{domain_prompts_en[domain]} of {country} in the last {years} years"
        )
        search_results = search_tool.invoke({"query": search_query})

        # 검색 결과를 JSON 문자열로 변환하여 DB에 저장
        set_kv_cache(cache_key, json.dumps(search_results))

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
    4. 주제와 설명 내용은 반드시 '한글 (영문)' 포맷으로 표현하세요.
    5. 도메인 별로 가치 있는 핵심 이슈 5개(최대)를 선정하세요.

    검색 결과:
    {context}
    """
    response = llm.invoke([HumanMessage(content=prompt)])

    # Step D: 결과 파싱 및 리스트화
    issues = [line.strip() for line in response.content.split("\n") if line.strip()]
    return issues[:10]


# Tool 2a: 이미지 생성 (DALL-E 3 or GPT Image 활용)
def generate_single_image(prompt: str) -> dict:
    """개별 이슈에 대해 이미지를 생성하고 결과를 안전하게 처리합니다."""
    client = OpenAI()

    models = (
        "dall-e-3",
        "gpt-image-1",
        "gpt-image-1-mini",
    )
    selected_model = f"models/{models[2]}"

    try:
        response = client.images.generate(
            model=selected_model,
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
            "model": selected_model,
        }

    except Exception as e:
        # 세이프티 시스템에 의해 차단된 경우 (Error 400 등)
        logging.warning(f"API 에러: {e}")

        return {
            "status": "filtered",
            "fallback_text": "안전 정책 또는 API 오류로 인해 이미지 생성이 차단되었습니다.",
            "reason": f"Safety filters or API error: {e}",
        }


# Tool 2b: 이미지 생성 (Imagen 4 + Pillow Text Overay 활용)
def generate_single_image2(prompt: str) -> dict:
    """
    Imagen으로 배경 이미지를 생성하고, Pillow로 한글 타이틀을 완벽하게 합성합니다.
    """
    client = genai.Client()

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
            "model": f"{selected_model} + Pillow",
        }

    except Exception as e:
        logging.error(f"API 에러: {e}")

        return {
            "status": "filtered",
            "fallback_text": "안전 정책 또는 API 오류로 인해 이미지 생성이 차단되었습니다.",
            "reason": f"Safety filters or API error: {e}",
        }


# Tool 2c: 이미지 생성 (Nano Banana 2 활용) + R2 업로드 + D1 메타데이터 저장
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
def generate_single_image3(prompt: str, user_id: str) -> dict:
    """
    Nano Banana (Gemini Image)를 사용하여 한글이 포함된 고해상도 교육 삽화를 생성합니다.
    """
    client = genai.Client()

    models = (
        "nano-banana-pro-preview",
        "gemini-3.1-pro-image-preview",
        "gemini-3.1-flash-image-preview",
    )
    selected_model = f"models/{models[2]}"

    try:
        # 이미지 생성 (Nano Banana 2) 예시
        response = client.models.generate_content(
            model=selected_model,
            contents=(
                f"A professional historical educational cartoon style illustration of: {prompt}. "
                f"Aspect Ratio: 1:1. Square format. "
                f"Please render the Korean text precisely and beautifully."
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
            insert_image_metadata(user_id, prompt, image_url)

            return {
                "status": "success",
                "file": image_url,
                "model": selected_model,
            }
        else:
            raise ValueError("응답에 이미지 데이터가 포함되어 있지 않습니다.")

    except Exception as e:
        error_msg = str(e)
        logging.error(f"API 에러: {error_msg}")

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


# Cloudflare D1의 REST API와 통신하는 커스텀 클래스
class CloudflareD1Saver(BaseCheckpointSaver):
    def __init__(self):
        super().__init__()
        self.account_id = os.getenv("CF_ACCOUNT_ID")
        self.d1_id = os.getenv("CF_D1_DATABASE_ID")
        self.token = os.getenv("CF_ACCOUNT_API_TOKEN")
        self.base_url = f"https://api.cloudflare.com/client/v4/accounts/{self.account_id}/d1/database/{self.d1_id}/query"
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def _execute_sql(self, sql: str, params: list = []):
        """D1 REST API를 통해 SQL을 실행하는 헬퍼 함수"""
        payload = {"sql": sql, "params": params}
        response = requests.post(self.base_url, headers=self.headers, json=payload)
        res_json = response.json()

        # 🚨 [추가된 디버깅 코드] D1 API가 실패하면 터미널에 빨간색으로 강력하게 에러를 출력합니다!
        if not res_json.get("success"):
            print("\n❌ [D1 DB 에러 발생] SQL 실행 실패!")
            print(f"오류 내용: {res_json.get('errors')}")
            print(f"실행한 쿼리: {sql}\n")

        return res_json

    # --- LangGraph 필수 오버라이드 메서드 ---
    def get_tuple(self, config: dict) -> Optional[CheckpointTuple]:
        thread_id = config["configurable"]["thread_id"]
        checkpoint_id = config["configurable"].get("checkpoint_id")

        if checkpoint_id:
            sql = "SELECT checkpoint, metadata FROM checkpoints WHERE thread_id = ? AND checkpoint_id = ?"
            params = [thread_id, checkpoint_id]
        else:
            sql = "SELECT checkpoint, metadata FROM checkpoints WHERE thread_id = ? ORDER BY checkpoint_id DESC LIMIT 1"
            params = [thread_id]

        res = self._execute_sql(sql, params)

        if res.get("success") and res["result"][0]["results"]:
            row = res["result"][0]["results"][0]

            chk_blob = base64.b64decode(row["checkpoint"])
            meta_blob = base64.b64decode(row["metadata"])

            # 1. Checkpoint 복원 (msgpack 우선 시도)
            try:
                chk = self.serde.loads_typed(("msgpack", chk_blob))
            except Exception:
                chk = self.serde.loads_typed(("json", chk_blob))

            # 2. Metadata 복원 (msgpack 우선 시도)
            try:
                meta = self.serde.loads_typed(("msgpack", meta_blob))
            except Exception:
                meta = self.serde.loads_typed(("json", meta_blob))

            return CheckpointTuple(config, chk, meta)

        return None

    def put(
        self,
        config: dict,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: Any,
    ) -> dict:
        thread_id = config["configurable"]["thread_id"]
        checkpoint_id = checkpoint["id"]

        # 1. dumps_typed는 (타입, 바이트 데이터)를 반환합니다.
        _, chk_blob = self.serde.dumps_typed(checkpoint)
        _, meta_blob = self.serde.dumps_typed(metadata)

        # 🚨 Binary(바이트) 데이터를 안전한 Base64 문자열로 인코딩
        chk_str = base64.b64encode(chk_blob).decode("ascii")
        meta_str = base64.b64encode(meta_blob).decode("ascii")

        sql = """
            INSERT INTO checkpoints (thread_id, checkpoint_id, checkpoint, metadata)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(thread_id, checkpoint_id) DO UPDATE SET
                checkpoint = excluded.checkpoint,
                metadata = excluded.metadata
        """
        params = [thread_id, checkpoint_id, chk_str, meta_str]
        self._execute_sql(sql, params)

        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_id": checkpoint_id,
            }
        }

    def put_writes(
        self, config: dict, writes: Sequence[Tuple[str, Any]], task_id: str
    ) -> None:
        thread_id = config["configurable"]["thread_id"]
        checkpoint_id = config["configurable"]["checkpoint_id"]

        for idx, (channel, value) in enumerate(writes):
            type_, blob = self.serde.dumps_typed(value)

            # 바이트를 Base64 문자열로 인코딩
            blob_str = base64.b64encode(blob).decode("ascii")

            # 🚨 중복 에러(UNIQUE constraint failed) 방지를 위한 UPSERT 구문 적용
            sql = """
                INSERT INTO checkpoint_writes (thread_id, checkpoint_id, task_id, idx, channel, type, blob)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(thread_id, checkpoint_id, task_id, idx) DO UPDATE SET
                    channel = excluded.channel,
                    type = excluded.type,
                    blob = excluded.blob
            """
            params = [thread_id, checkpoint_id, task_id, idx, channel, type_, blob_str]
            self._execute_sql(sql, params)

    def list(self, config: dict, **kwargs):
        """특정 조건의 체크포인트 목록을 반환 (에러 방지를 위해 빈 이터레이터 반환)"""
        yield from []
