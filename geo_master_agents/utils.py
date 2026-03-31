import hashlib
import json
import os

import boto3
import requests
from botocore.exceptions import ClientError
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

CF_REST_API_URL = "https://api.cloudflare.com/client/v4/accounts"
CF_ACCOUNT_ID = os.getenv("CF_ACCOUNT_ID")
CF_API_TOKEN = os.getenv("CF_ACCOUNT_API_TOKEN")
BUCKET_NAME = os.getenv("CF_R2_BUCKET_NAME")


def generate_cache_key_for_search(domain, country, years):
    combined_str = f"{domain}_{country}_{years}"
    return hashlib.md5(combined_str.encode()).hexdigest()


def generate_cache_key_for_image(domain, country, year, issue_text):
    combined_str = f"{domain}_{country}_{year}_{issue_text[:20]}"
    return hashlib.md5(combined_str.encode()).hexdigest()


# --- 1. KV (검색 캐싱) ---
def get_kv_cache(cache_key: str):
    url = f"{CF_REST_API_URL}/{CF_ACCOUNT_ID}/storage/kv/namespaces/{os.getenv('CF_KV_NAMESPACE_ID')}/values/{cache_key}"
    headers = {"Authorization": f"Bearer {CF_API_TOKEN}"}
    res = requests.get(url, headers=headers)
    return res.json() if res.status_code == 200 else None


def set_kv_cache(cache_key: str, data: dict):
    url = f"{CF_REST_API_URL}/{CF_ACCOUNT_ID}/storage/kv/namespaces/{os.getenv('CF_KV_NAMESPACE_ID')}/values/{cache_key}"
    headers = {
        "Authorization": f"Bearer {CF_API_TOKEN}",
        "Content-Type": "application/json",
    }
    requests.put(url, headers=headers, data=json.dumps(data))


# --- 2. D1 (메타데이터 저장용 REST API) ---
def insert_image_metadata(user_id: str, prompt: str, image_url: str):
    url = f"{CF_REST_API_URL}/{CF_ACCOUNT_ID}/d1/database/{os.getenv('CF_D1_DATABASE_ID')}/query"
    headers = {
        "Authorization": f"Bearer {CF_API_TOKEN}",
        "Content-Type": "application/json",
    }
    sql = "INSERT INTO image_gallery (user_id, prompt, image_url) VALUES (?, ?, ?)"
    requests.post(
        url, headers=headers, json={"sql": sql, "params": [user_id, prompt, image_url]}
    )


# --- 3. R2 (이미지 업로드) ---
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
