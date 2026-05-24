# =====================================================================
# 1. Python Default
# =====================================================================
import base64
import hashlib
import json
import os
from typing import Any, Optional, Sequence, Tuple

# =====================================================================
# 2. Installed Packages
# =====================================================================
import boto3
import pycountry
import requests
from botocore.exceptions import ClientError
from dotenv import load_dotenv
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)

# =====================================================================
# 3. Custom Files
# =====================================================================
from data import GEO_METADATA

# .env 파일 로드
load_dotenv()

CF_REST_API_URL = "https://api.cloudflare.com/client/v4/accounts"
CF_ACCOUNT_ID = os.getenv("CF_ACCOUNT_ID")
CF_API_TOKEN = os.getenv("CF_ACCOUNT_API_TOKEN")
BUCKET_NAME = os.getenv("CF_R2_BUCKET_NAME")


# --- Unique Hash (Cache Key) ---
def generate_cache_key_for_search(domain, country, years):
    combined_str = f"{domain}_{country}_{years}"
    return hashlib.md5(combined_str.encode()).hexdigest()


def generate_cache_key_for_image(domain, country, year, issue_text):
    combined_str = f"{domain}_{country}_{year}_{issue_text[:20]}"
    return hashlib.md5(combined_str.encode()).hexdigest()


# --- KV (Cache Server) ---
def set_kv_cache(cache_key: str, data: dict):
    url = f"{CF_REST_API_URL}/{CF_ACCOUNT_ID}/storage/kv/namespaces/{os.getenv('CF_KV_NAMESPACE_ID')}/values/{cache_key}"
    headers = {
        "Authorization": f"Bearer {CF_API_TOKEN}",
        "Content-Type": "application/json",
    }
    requests.put(url, headers=headers, data=json.dumps(data))


def get_kv_cache(cache_key: str):
    url = f"{CF_REST_API_URL}/{CF_ACCOUNT_ID}/storage/kv/namespaces/{os.getenv('CF_KV_NAMESPACE_ID')}/values/{cache_key}"
    headers = {"Authorization": f"Bearer {CF_API_TOKEN}"}
    res = requests.get(url, headers=headers)
    if res.status_code == 200:
        # res.json() 대신 res.text를 가져와서 json.loads()로 변환!
        try:
            return json.loads(res.text)
        except json.JSONDecodeError:
            return res.text  # 만약 단순 문자열인 경우 대비
    return None


# --- R2 (File Storage) ---
# S3 클라이언트를 R2 엔드포인트에 맞춰 초기화
s3_client = boto3.client(
    "s3",
    endpoint_url=f"https://{CF_ACCOUNT_ID}.r2.cloudflarestorage.com",
    aws_access_key_id=os.getenv("CF_R2_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("CF_R2_SECRET_ACCESS_KEY"),
    region_name="auto",
)


def upload_image_to_r2(file_name: str, image_bytes: bytes) -> str:
    """
    Gemini가 생성한 이미지 바이트(bytes)를 로컬에 저장하지 않고 R2로 바로 업로드합니다.
    """
    s3_client.put_object(
        Bucket=BUCKET_NAME,
        Key=file_name,
        Body=image_bytes,
        ContentType="image/png",
    )
    # public_domain = os.getenv("CF_R2_PUBLIC_DOMAIN")
    public_domain = os.getenv("CF_R2_PUBLIC_GEO_MASTER_URL")
    return f"https://{public_domain}/{file_name}"


def get_image_url(file_name: str, public_domain: str = None) -> str:
    """
    Streamlit UI에 이미지를 띄우기 위한 이미지 URL을 반환합니다.
    """
    # 방법 A: 버킷에 'Custom Domain(퍼블릭 도메인)'을 연결한 경우 (가장 추천)
    if public_domain:
        return f"https://{public_domain}/{file_name}"

    # 방법 B: 프라이빗 버킷인 경우 (Pre-signed URL 생성, 기본 1시간 유효)
    try:
        presigned_url = s3_client.generate_presigned_url(
            ClientMethod="get_object",
            Params={"Bucket": BUCKET_NAME, "Key": file_name},
            ExpiresIn=3600,
        )
        return presigned_url
    except ClientError as e:
        print(f"❌ URL 생성 실패: {e}")
        return ""


# --- D1 (Relational Database) ---
def upsert_user_info(email: str, nickname: str):
    url = f"{CF_REST_API_URL}/{CF_ACCOUNT_ID}/d1/database/{os.getenv('CF_D1_DATABASE_ID')}/query"
    headers = {
        "Authorization": f"Bearer {CF_API_TOKEN}",
        "Content-Type": "application/json",
    }
    sql = """
        INSERT INTO users (email, nickname)
        VALUES (?, ?)
        ON CONFLICT(email) DO UPDATE SET
            nickname = excluded.nickname,
            updated_at = CURRENT_TIMESTAMP
        RETURNING id
    """

    response = requests.post(
        url,
        headers=headers,
        json={"sql": sql, "params": [email, nickname]},
    )

    # 🚨 조용히 실패하는 것을 막기 위한 로깅
    if response.status_code == 200:
        try:
            data = response.json()
            if data.get("success"):
                print(f"✅ [D1 저장 성공] users 테이블 ({email} with {nickname})")
            else:
                print(f"🚨 [D1 쿼리 에러] users 테이블: {data.get('errors')}")

            # Cloudflare D1 REST API 응답 구조 깊숙한 곳에서 id 꺼내기
            upserted_id = data["result"][0]["results"][0]["id"]
            print(f"⚠️ [D1 저장 성공] issue_id: {upserted_id})")
            return upserted_id

        except (KeyError, IndexError):
            print(f"⚠️ ID 추출 실패 (응답 구조 확인 필요): {data}")
            return None
    else:
        print(f"💥 [D1 통신 에러] HTTP {response.status_code}: {response.text}")


def upsert_issue_info(
    domain: str, country: str, year: int, content: str, user_id: int | None = None
):
    url = f"{CF_REST_API_URL}/{CF_ACCOUNT_ID}/d1/database/{os.getenv('CF_D1_DATABASE_ID')}/query"
    headers = {
        "Authorization": f"Bearer {CF_API_TOKEN}",
        "Content-Type": "application/json",
    }
    sql = """
        INSERT INTO issues (domain, country, year, content, user_id)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(domain, country, year) DO UPDATE SET
            content = excluded.content,
            user_id = COALESCE(excluded.user_id, issues.user_id),
            updated_at = CURRENT_TIMESTAMP
        RETURNING id
    """

    response = requests.post(
        url,
        headers=headers,
        json={"sql": sql, "params": [domain, country, year, content, user_id]},
    )

    # 🚨 조용히 실패하는 것을 막기 위한 로깅
    if response.status_code == 200:
        try:
            data = response.json()
            if data.get("success"):
                print(f"✅ [D1 저장 성공] issues 테이블 (issue: {content})")
            else:
                print(f"🚨 [D1 쿼리 에러] issues 테이블: {data.get('errors')}")

            # Cloudflare D1 REST API 응답 구조 깊숙한 곳에서 id 꺼내기
            upserted_id = data["result"][0]["results"][0]["id"]
            print(f"⚠️ [D1 저장 성공] issue_id: {upserted_id})")
            return upserted_id

        except (KeyError, IndexError):
            print(f"⚠️ ID 추출 실패 (응답 구조 확인 필요): {data}")
            return None
    else:
        print(f"🚨 D1 API 호출 에러 ({response.status_code}): {response.text}")
        return None


def insert_cartoon_info(prompt: str, image_url: str, issue_id: int):
    url = f"{CF_REST_API_URL}/{CF_ACCOUNT_ID}/d1/database/{os.getenv('CF_D1_DATABASE_ID')}/query"
    headers = {
        "Authorization": f"Bearer {CF_API_TOKEN}",
        "Content-Type": "application/json",
    }
    sql = "INSERT INTO cartoons (issue_id, prompt, image_url) VALUES (?, ?, ?)"

    response = requests.post(
        url,
        headers=headers,
        json={"sql": sql, "params": [issue_id, prompt, image_url]},
    )

    # 🚨 조용히 실패하는 것을 막기 위한 로깅
    if response.status_code == 200:
        data = response.json()
        if data.get("success"):
            print(f"✅ [D1 저장 성공] cartoons 테이블 (issue_id: {issue_id})")
        else:
            print(f"🚨 [D1 쿼리 에러] cartoons 테이블: {data.get('errors')}")
    else:
        print(f"💥 [D1 통신 에러] HTTP {response.status_code}: {response.text}")


def get_country_map_statistics() -> list:
    """국가별 이슈 검색량 + 카툰 생성량을 DB에서 조회합니다."""

    url = f"{CF_REST_API_URL}/{CF_ACCOUNT_ID}/d1/database/{os.getenv('CF_D1_DATABASE_ID')}/query"
    headers = {
        "Authorization": f"Bearer {CF_API_TOKEN}",
        "Content-Type": "application/json",
    }

    sql = """
    SELECT
        i.country,
        COUNT(DISTINCT i.id) AS search_volume,
        COUNT(c.id) AS generation_volume
    FROM
        issues i
    LEFT JOIN
        cartoons c ON i.id = c.issue_id
    GROUP BY
        i.country
    """

    response = requests.post(
        url,
        headers=headers,
        json={"sql": sql, "params": []},
    )

    data = []
    if response.status_code == 200:
        res_json = response.json()
        if res_json.get("success") and res_json["result"][0]["results"]:
            for row in res_json["result"][0]["results"]:
                country_name = row.get("country", "")
                search_vol = row.get("search_volume", 0)
                gen_vol = row.get("generation_volume", 0)

                if country_name:
                    try:
                        country_obj = pycountry.countries.search_fuzzy(country_name)[0]
                        alpha_2 = country_obj.alpha_2
                    except (LookupError, IndexError):
                        alpha_2 = None

                    if alpha_2 and alpha_2 in GEO_METADATA:
                        geo_info = GEO_METADATA[alpha_2]
                    else:
                        geo_info = {"lat": 20.0, "lon": 0.0, "zoom": 1}

                    data.append(
                        {
                            "country": country_name,
                            "search_volume": search_vol,
                            "generation_volume": gen_vol,
                            "lat": geo_info["lat"],
                            "lon": geo_info["lon"],
                        }
                    )

    return data


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
