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


# 지리적 메타데이터 딕셔너리 (Alpha-2 코드 기준)
GEO_METADATA = {
    "AD": {"lat": 42.5462, "lon": 1.6015, "zoom": 9},  # 안도라
    "AE": {"lat": 23.4241, "lon": 53.8478, "zoom": 5},  # 아랍에미리트
    "AF": {"lat": 33.9391, "lon": 67.7100, "zoom": 5},  # 아프가니스탄
    "AG": {"lat": 17.0608, "lon": -61.7964, "zoom": 9},  # 앤티가 바부다
    "AI": {"lat": 18.2206, "lon": -63.0686, "zoom": 10},  # 앵귈라
    "AL": {"lat": 41.1533, "lon": 20.1683, "zoom": 6},  # 알바니아
    "AM": {"lat": 40.0691, "lon": 45.0382, "zoom": 6},  # 아르메니아
    "AO": {"lat": -11.2027, "lon": 17.8739, "zoom": 4},  # 앙골라
    "AQ": {"lat": -75.2509, "lon": -0.0714, "zoom": 2},  # 남극
    "AR": {"lat": -38.4161, "lon": -63.6167, "zoom": 3},  # 아르헨티나
    "AS": {"lat": -14.2710, "lon": -170.1322, "zoom": 9},  # 아메리칸사모아
    "AT": {"lat": 47.5162, "lon": 14.5501, "zoom": 6},  # 오스트리아
    "AU": {"lat": -25.2744, "lon": 133.7751, "zoom": 3},  # 호주
    "AW": {"lat": 12.5211, "lon": -69.9683, "zoom": 10},  # 아루바
    "AX": {"lat": 60.1282, "lon": 19.9067, "zoom": 8},  # 올란드 제도
    "AZ": {"lat": 40.1431, "lon": 47.5769, "zoom": 6},  # 아제르바이잔
    "BA": {"lat": 43.9159, "lon": 17.6791, "zoom": 6},  # 보스니아 헤르체고비나
    "BB": {"lat": 13.1939, "lon": -59.5432, "zoom": 10},  # 바베이도스
    "BD": {"lat": 23.6850, "lon": 90.3563, "zoom": 6},  # 방글라데시
    "BE": {"lat": 50.5039, "lon": 4.4699, "zoom": 6},  # 벨기에
    "BF": {"lat": 12.2383, "lon": -1.5616, "zoom": 5},  # 부르키나파소
    "BG": {"lat": 42.7339, "lon": 25.4858, "zoom": 6},  # 불가리아
    "BH": {"lat": 25.9304, "lon": 50.6378, "zoom": 9},  # 바레인
    "BI": {"lat": -3.3731, "lon": 29.9189, "zoom": 7},  # 부룬디
    "BJ": {"lat": 9.3077, "lon": 2.3158, "zoom": 6},  # 베냉
    "BL": {"lat": 17.9000, "lon": -62.8333, "zoom": 10},  # 생바르텔레미
    "BM": {"lat": 32.3214, "lon": -64.7574, "zoom": 10},  # 버뮤다
    "BN": {"lat": 4.5353, "lon": 114.7277, "zoom": 8},  # 브루나이
    "BO": {"lat": -16.2902, "lon": -63.5887, "zoom": 4},  # 볼리비아
    "BQ": {"lat": 12.1784, "lon": -68.2385, "zoom": 10},  # 카리브 네덜란드
    "BR": {"lat": -14.2350, "lon": -51.9253, "zoom": 3},  # 브라질
    "BS": {"lat": 25.0343, "lon": -77.3963, "zoom": 6},  # 바하마
    "BT": {"lat": 27.5142, "lon": 90.4336, "zoom": 7},  # 부탄
    "BW": {"lat": -22.3285, "lon": 24.6849, "zoom": 5},  # 보츠와나
    "BY": {"lat": 53.7098, "lon": 27.9534, "zoom": 5},  # 벨라루스
    "BZ": {"lat": 17.1899, "lon": -88.4976, "zoom": 7},  # 벨리즈
    "CA": {"lat": 56.1304, "lon": -106.3468, "zoom": 2},  # 캐나다
    "CC": {"lat": -12.1642, "lon": 96.8710, "zoom": 10},  # 코코스 제도
    "CD": {"lat": -4.0383, "lon": 21.7587, "zoom": 4},  # 콩고민주공화국
    "CF": {"lat": 6.6111, "lon": 20.9394, "zoom": 5},  # 중앙아프리카공화국
    "CG": {"lat": -0.2280, "lon": 15.8277, "zoom": 5},  # 콩고공화국
    "CH": {"lat": 46.8182, "lon": 8.2275, "zoom": 6},  # 스위스
    "CI": {"lat": 7.5400, "lon": -5.5471, "zoom": 5},  # 코트디부아르
    "CK": {"lat": -21.2367, "lon": -159.7777, "zoom": 9},  # 쿡 제도
    "CL": {"lat": -35.6751, "lon": -71.5430, "zoom": 3},  # 칠레
    "CM": {"lat": 7.3697, "lon": 12.3547, "zoom": 5},  # 카메룬
    "CN": {"lat": 35.8617, "lon": 104.1954, "zoom": 3},  # 중국
    "CO": {"lat": 4.5709, "lon": -74.2973, "zoom": 4},  # 콜롬비아
    "CR": {"lat": 9.7489, "lon": -83.7534, "zoom": 6},  # 코스타리카
    "CU": {"lat": 21.5218, "lon": -77.7812, "zoom": 5},  # 쿠바
    "CV": {"lat": 16.0021, "lon": -24.0132, "zoom": 6},  # 카보베르데
    "CW": {"lat": 12.1696, "lon": -68.9900, "zoom": 10},  # 퀴라소
    "CX": {"lat": -10.4475, "lon": 105.6904, "zoom": 10},  # 크리스마스 섬
    "CY": {"lat": 35.1264, "lon": 33.4299, "zoom": 8},  # 키프로스
    "CZ": {"lat": 49.8175, "lon": 15.4730, "zoom": 6},  # 체코
    "DE": {"lat": 51.1657, "lon": 10.4515, "zoom": 5},  # 독일
    "DJ": {"lat": 11.8251, "lon": 42.5903, "zoom": 7},  # 지부티
    "DK": {"lat": 56.2639, "lon": 9.5018, "zoom": 6},  # 덴마크
    "DM": {"lat": 15.4150, "lon": -61.3710, "zoom": 9},  # 도미니카
    "DO": {"lat": 18.7357, "lon": -70.1627, "zoom": 6},  # 도미니카 공화국
    "DZ": {"lat": 28.0339, "lon": 1.6596, "zoom": 4},  # 알제리
    "EC": {"lat": -1.8312, "lon": -78.1834, "zoom": 5},  # 에콰도르
    "EE": {"lat": 58.5953, "lon": 25.0136, "zoom": 6},  # 에스토니아
    "EG": {"lat": 26.8206, "lon": 30.8025, "zoom": 4},  # 이집트
    "EH": {"lat": 24.2155, "lon": -12.8858, "zoom": 5},  # 서사하라
    "ER": {"lat": 15.1794, "lon": 39.7823, "zoom": 6},  # 에리트레아
    "ES": {"lat": 40.4637, "lon": -3.7492, "zoom": 5},  # 스페인
    "ET": {"lat": 9.1450, "lon": 40.4897, "zoom": 5},  # 에티오피아
    "FI": {"lat": 61.9241, "lon": 25.7482, "zoom": 4},  # 핀란드
    "FJ": {"lat": -16.5782, "lon": 179.4144, "zoom": 6},  # 피지
    "FK": {"lat": -51.7963, "lon": -59.5236, "zoom": 6},  # 포클랜드 제도
    "FM": {"lat": 7.4256, "lon": 150.5508, "zoom": 5},  # 미크로네시아
    "FO": {"lat": 61.8926, "lon": -6.9118, "zoom": 8},  # 페로 제도
    "FR": {"lat": 46.2276, "lon": 2.2137, "zoom": 5},  # 프랑스
    "GA": {"lat": -0.8037, "lon": 11.6094, "zoom": 5},  # 가봉
    "GB": {"lat": 55.3781, "lon": -3.4360, "zoom": 5},  # 영국
    "GD": {"lat": 12.1165, "lon": -61.6790, "zoom": 10},  # 그레나다
    "GE": {"lat": 42.3154, "lon": 43.3569, "zoom": 6},  # 조지아
    "GF": {"lat": 3.9339, "lon": -53.1258, "zoom": 6},  # 프랑스령 기아나
    "GG": {"lat": 49.4657, "lon": -2.5853, "zoom": 10},  # 건지
    "GH": {"lat": 7.9465, "lon": -1.0232, "zoom": 5},  # 가나
    "GI": {"lat": 36.1408, "lon": -5.3536, "zoom": 12},  # 지브롤터
    "GL": {"lat": 71.7069, "lon": -42.6043, "zoom": 2},  # 그린란드
    "GM": {"lat": 13.4432, "lon": -15.3101, "zoom": 7},  # 감비아
    "GN": {"lat": 9.9456, "lon": -9.6966, "zoom": 5},  # 기니
    "GP": {"lat": 16.2650, "lon": -61.5510, "zoom": 9},  # 과들루프
    "GQ": {"lat": 1.6508, "lon": 10.2679, "zoom": 6},  # 적도 기니
    "GR": {"lat": 39.0742, "lon": 21.8243, "zoom": 5},  # 그리스
    "GS": {"lat": -54.4296, "lon": -36.5879, "zoom": 5},  # 사우스조지아
    "GT": {"lat": 15.7835, "lon": -90.2308, "zoom": 6},  # 과테말라
    "GU": {"lat": 13.4443, "lon": 144.7937, "zoom": 9},  # 괌
    "GW": {"lat": 11.8037, "lon": -15.1804, "zoom": 7},  # 기니비사우
    "GY": {"lat": 4.8604, "lon": -58.9302, "zoom": 5},  # 가이아나
    "HK": {"lat": 22.3964, "lon": 114.1095, "zoom": 10},  # 홍콩
    "HM": {"lat": -53.0818, "lon": 73.5042, "zoom": 8},  # 허드 맥도널드 제도
    "HN": {"lat": 15.2000, "lon": -86.2419, "zoom": 6},  # 온두라스
    "HR": {"lat": 45.1000, "lon": 15.2000, "zoom": 6},  # 크로아티아
    "HT": {"lat": 18.9712, "lon": -72.2852, "zoom": 7},  # 아이티
    "HU": {"lat": 47.1625, "lon": 19.5033, "zoom": 6},  # 헝가리
    "ID": {"lat": -0.7893, "lon": 113.9213, "zoom": 4},  # 인도네시아
    "IE": {"lat": 53.1424, "lon": -7.6921, "zoom": 6},  # 아일랜드
    "IL": {"lat": 31.0461, "lon": 34.8516, "zoom": 6},  # 이스라엘
    "IM": {"lat": 54.2361, "lon": -4.5481, "zoom": 9},  # 맨섬
    "IN": {"lat": 20.5937, "lon": 78.9629, "zoom": 4},  # 인도
    "IO": {"lat": -6.3432, "lon": 71.8765, "zoom": 5},  # 영국령 인도양 지역
    "IQ": {"lat": 33.2232, "lon": 43.6793, "zoom": 5},  # 이라크
    "IR": {"lat": 32.4279, "lon": 53.6880, "zoom": 4},  # 이란
    "IS": {"lat": 64.9631, "lon": -19.0208, "zoom": 5},  # 아이슬란드
    "IT": {"lat": 41.8719, "lon": 12.5674, "zoom": 5},  # 이탈리아
    "JE": {"lat": 49.2144, "lon": -2.1312, "zoom": 10},  # 저지
    "JM": {"lat": 18.1096, "lon": -77.2975, "zoom": 8},  # 자메이카
    "JO": {"lat": 31.2400, "lon": 36.5100, "zoom": 6},  # 요르단
    "JP": {"lat": 36.2048, "lon": 138.2529, "zoom": 5},  # 일본
    "KE": {"lat": -0.0236, "lon": 37.9062, "zoom": 5},  # 케냐
    "KG": {"lat": 41.2044, "lon": 74.7661, "zoom": 5},  # 키르기스스탄
    "KH": {"lat": 12.5657, "lon": 104.9910, "zoom": 6},  # 캄보디아
    "KI": {"lat": -3.3704, "lon": -168.7340, "zoom": 5},  # 키리바시
    "KM": {"lat": -11.8750, "lon": 43.8722, "zoom": 8},  # 코모로
    "KN": {"lat": 17.3578, "lon": -62.7830, "zoom": 10},  # 세인트키츠 네비스
    "KP": {"lat": 40.3399, "lon": 127.5101, "zoom": 6},  # 북한
    "KR": {"lat": 35.9078, "lon": 127.7669, "zoom": 6},  # 대한민국
    "KW": {"lat": 29.3117, "lon": 47.4818, "zoom": 7},  # 쿠웨이트
    "KY": {"lat": 19.3133, "lon": -81.2546, "zoom": 9},  # 케이맨 제도
    "KZ": {"lat": 48.0196, "lon": 66.9237, "zoom": 3},  # 카자흐스탄
    "LA": {"lat": 19.8563, "lon": 102.4955, "zoom": 5},  # 라오스
    "LB": {"lat": 33.8547, "lon": 35.8623, "zoom": 7},  # 레바논
    "LC": {"lat": 13.9094, "lon": -60.9789, "zoom": 9},  # 세인트루시아
    "LI": {"lat": 47.1660, "lon": 9.5554, "zoom": 9},  # 리히텐슈타인
    "LK": {"lat": 7.8731, "lon": 80.7718, "zoom": 6},  # 스리랑카
    "LR": {"lat": 6.4281, "lon": -9.4295, "zoom": 6},  # 라이베리아
    "LS": {"lat": -29.6100, "lon": 28.2336, "zoom": 7},  # 레소토
    "LT": {"lat": 55.1694, "lon": 23.8813, "zoom": 6},  # 리투아니아
    "LU": {"lat": 49.8153, "lon": 6.1296, "zoom": 8},  # 룩셈부르크
    "LV": {"lat": 56.8796, "lon": 24.6032, "zoom": 6},  # 라트비아
    "LY": {"lat": 26.3351, "lon": 17.2283, "zoom": 4},  # 리비아
    "MA": {"lat": 31.7917, "lon": -7.0926, "zoom": 5},  # 모로코
    "MC": {"lat": 43.7384, "lon": 7.4246, "zoom": 12},  # 모나코
    "MD": {"lat": 47.4116, "lon": 28.3699, "zoom": 6},  # 몰도바
    "ME": {"lat": 42.7087, "lon": 19.3744, "zoom": 7},  # 몬테네그로
    "MF": {"lat": 18.0708, "lon": -63.0501, "zoom": 10},  # 생마르탱
    "MG": {"lat": -18.7669, "lon": 46.8691, "zoom": 5},  # 마다가스카르
    "MH": {"lat": 7.1315, "lon": 171.1845, "zoom": 6},  # 마셜 제도
    "MK": {"lat": 41.6086, "lon": 21.7453, "zoom": 7},  # 북마케도니아
    "ML": {"lat": 17.5707, "lon": -3.9962, "zoom": 4},  # 말리
    "MM": {"lat": 21.9162, "lon": 95.9560, "zoom": 5},  # 미얀마
    "MN": {"lat": 46.8625, "lon": 103.8467, "zoom": 4},  # 몽골
    "MO": {"lat": 22.1987, "lon": 113.5439, "zoom": 11},  # 마카오
    "MP": {"lat": 15.0979, "lon": 145.6739, "zoom": 8},  # 북마리아나 제도
    "MQ": {"lat": 14.6415, "lon": -61.0242, "zoom": 9},  # 마르티니크
    "MR": {"lat": 21.0079, "lon": -10.9408, "zoom": 4},  # 모리타니
    "MS": {"lat": 16.7425, "lon": -62.1874, "zoom": 10},  # 몬트세랫
    "MT": {"lat": 35.9375, "lon": 14.3754, "zoom": 9},  # 몰타
    "MU": {"lat": -20.3484, "lon": 57.5522, "zoom": 9},  # 모리셔스
    "MV": {"lat": 3.2028, "lon": 73.2207, "zoom": 6},  # 몰디브
    "MW": {"lat": -13.2543, "lon": 34.3015, "zoom": 6},  # 말라위
    "MX": {"lat": 23.6345, "lon": -102.5528, "zoom": 4},  # 멕시코
    "MY": {"lat": 4.2105, "lon": 101.9758, "zoom": 5},  # 말레이시아
    "MZ": {"lat": -18.6657, "lon": 35.5296, "zoom": 5},  # 모잠비크
    "NA": {"lat": -22.9576, "lon": 18.4904, "zoom": 4},  # 나미비아
    "NC": {"lat": -20.9043, "lon": 165.6180, "zoom": 6},  # 뉴칼레도니아
    "NE": {"lat": 17.6078, "lon": 8.0817, "zoom": 4},  # 니제르
    "NF": {"lat": -29.0408, "lon": 167.9547, "zoom": 10},  # 노퍽섬
    "NG": {"lat": 9.0820, "lon": 8.6753, "zoom": 5},  # 나이지리아
    "NI": {"lat": 12.8654, "lon": -85.2072, "zoom": 6},  # 니카라과
    "NL": {"lat": 52.1326, "lon": 5.2913, "zoom": 6},  # 네덜란드
    "NO": {"lat": 60.4720, "lon": 8.4689, "zoom": 4},  # 노르웨이
    "NP": {"lat": 28.3949, "lon": 84.1240, "zoom": 6},  # 네팔
    "NR": {"lat": -0.5228, "lon": 166.9315, "zoom": 11},  # 나우루
    "NU": {"lat": -19.0544, "lon": -169.8672, "zoom": 10},  # 니우에
    "NZ": {"lat": -40.9006, "lon": 174.8860, "zoom": 5},  # 뉴질랜드
    "OM": {"lat": 21.5126, "lon": 55.9233, "zoom": 5},  # 오만
    "PA": {"lat": 8.5380, "lon": -80.7821, "zoom": 6},  # 파나마
    "PE": {"lat": -9.1900, "lon": -75.0152, "zoom": 4},  # 페루
    "PF": {"lat": -17.6797, "lon": -149.4068, "zoom": 4},  # 프랑스령 폴리네시아
    "PG": {"lat": -6.3150, "lon": 143.9555, "zoom": 5},  # 파푸아뉴기니
    "PH": {"lat": 12.8797, "lon": 121.7740, "zoom": 5},  # 필리핀
    "PK": {"lat": 30.3753, "lon": 69.3451, "zoom": 5},  # 파키스탄
    "PL": {"lat": 51.9194, "lon": 19.1451, "zoom": 5},  # 폴란드
    "PM": {"lat": 46.9419, "lon": -56.2711, "zoom": 9},  # 생피에르 미클롱
    "PN": {"lat": -24.3768, "lon": -128.3242, "zoom": 10},  # 핏케언 제도
    "PR": {"lat": 18.2208, "lon": -66.5901, "zoom": 8},  # 푸에르토리코
    "PS": {"lat": 31.9522, "lon": 35.2332, "zoom": 8},  # 팔레스타인
    "PT": {"lat": 39.3999, "lon": -8.2245, "zoom": 6},  # 포르투갈
    "PW": {"lat": 7.5150, "lon": 134.5825, "zoom": 9},  # 팔라우
    "PY": {"lat": -23.4425, "lon": -58.4438, "zoom": 5},  # 파라과이
    "QA": {"lat": 25.3548, "lon": 51.1839, "zoom": 8},  # 카타르
    "RE": {"lat": -21.1151, "lon": 55.5364, "zoom": 8},  # 레위니옹
    "RO": {"lat": 45.9432, "lon": 24.9668, "zoom": 6},  # 루마니아
    "RS": {"lat": 44.0165, "lon": 21.0059, "zoom": 6},  # 세르비아
    "RU": {"lat": 61.5240, "lon": 105.3188, "zoom": 2},  # 러시아
    "RW": {"lat": -1.9403, "lon": 29.8739, "zoom": 7},  # 르완다
    "SA": {"lat": 23.8859, "lon": 45.0792, "zoom": 4},  # 사우디아라비아
    "SB": {"lat": -9.6457, "lon": 160.1562, "zoom": 6},  # 솔로몬 제도
    "SC": {"lat": -4.6796, "lon": 55.4920, "zoom": 8},  # 세이셸
    "SD": {"lat": 12.8628, "lon": 30.2176, "zoom": 4},  # 수단
    "SE": {"lat": 60.1282, "lon": 18.6435, "zoom": 4},  # 스웨덴
    "SG": {"lat": 1.3521, "lon": 103.8198, "zoom": 10},  # 싱가포르
    "SH": {"lat": -15.9650, "lon": -5.7089, "zoom": 7},  # 세인트헬레나
    "SI": {"lat": 46.1512, "lon": 14.9955, "zoom": 7},  # 슬로베니아
    "SJ": {"lat": 77.5536, "lon": 23.6703, "zoom": 3},  # 스발바르 얀마옌
    "SK": {"lat": 48.6690, "lon": 19.6990, "zoom": 6},  # 슬로바키아
    "SL": {"lat": 8.4606, "lon": -11.7799, "zoom": 6},  # 시에라리온
    "SM": {"lat": 43.9424, "lon": 12.4578, "zoom": 10},  # 산마리노
    "SN": {"lat": 14.4974, "lon": -14.4524, "zoom": 6},  # 세네갈
    "SO": {"lat": 5.1521, "lon": 46.1996, "zoom": 5},  # 소말리아
    "SR": {"lat": 3.9193, "lon": -56.0278, "zoom": 6},  # 수리남
    "SS": {"lat": 6.8770, "lon": 31.3070, "zoom": 5},  # 남수단
    "ST": {"lat": 0.1864, "lon": 6.6131, "zoom": 9},  # 상투메 프린시페
    "SV": {"lat": 13.7942, "lon": -88.8965, "zoom": 7},  # 엘살바도르
    "SX": {"lat": 18.0425, "lon": -63.0548, "zoom": 11},  # 신트마르턴
    "SY": {"lat": 34.8021, "lon": 38.9968, "zoom": 6},  # 시리아
    "SZ": {"lat": -26.5225, "lon": 31.4659, "zoom": 7},  # 에스와티니
    "TC": {"lat": 21.6940, "lon": -71.7979, "zoom": 8},  # 터크스 케이커스
    "TD": {"lat": 15.4542, "lon": 18.7322, "zoom": 4},  # 차드
    "TF": {"lat": -49.2804, "lon": 69.3486, "zoom": 4},  # 프랑스령 남부
    "TG": {"lat": 8.6195, "lon": 0.8248, "zoom": 6},  # 토고
    "TH": {"lat": 15.8700, "lon": 100.9925, "zoom": 5},  # 태국
    "TJ": {"lat": 38.8610, "lon": 71.2761, "zoom": 6},  # 타지키스탄
    "TK": {"lat": -8.9674, "lon": -171.8559, "zoom": 9},  # 토켈라우
    "TL": {"lat": -8.8742, "lon": 125.7275, "zoom": 7},  # 동티모르
    "TM": {"lat": 38.9697, "lon": 59.5563, "zoom": 5},  # 투르크메니스탄
    "TN": {"lat": 33.8869, "lon": 9.5375, "zoom": 5},  # 튀니지
    "TO": {"lat": -21.1790, "lon": -175.1982, "zoom": 8},  # 통가
    "TR": {"lat": 38.9637, "lon": 35.2433, "zoom": 5},  # 튀르키예
    "TT": {"lat": 10.6918, "lon": -61.2225, "zoom": 8},  # 트리니다드 토바고
    "TV": {"lat": -7.1095, "lon": 177.6493, "zoom": 10},  # 투발루
    "TW": {"lat": 23.6978, "lon": 120.9605, "zoom": 6},  # 대만
    "TZ": {"lat": -6.3690, "lon": 34.8888, "zoom": 5},  # 탄자니아
    "UA": {"lat": 48.3794, "lon": 31.1656, "zoom": 5},  # 우크라이나
    "UG": {"lat": 1.3733, "lon": 32.2903, "zoom": 6},  # 우간다
    "UM": {"lat": 19.3000, "lon": 166.6000, "zoom": 4},  # 미국령 군소 제도
    "US": {"lat": 37.0902, "lon": -95.7129, "zoom": 3},  # 미국
    "UY": {"lat": -32.5228, "lon": -55.7658, "zoom": 6},  # 우루과이
    "UZ": {"lat": 41.3775, "lon": 64.5853, "zoom": 5},  # 우즈베키스탄
    "VA": {"lat": 41.9029, "lon": 12.4534, "zoom": 13},  # 바티칸 시국
    "VC": {"lat": 13.2528, "lon": -61.1971, "zoom": 10},  # 세인트빈센트 그레나딘
    "VE": {"lat": 9.0820, "lon": -66.1873, "zoom": 5},  # 베네수엘라
    "VG": {"lat": 18.4207, "lon": -64.6400, "zoom": 10},  # 영국령 버진아일랜드
    "VI": {"lat": 18.3358, "lon": -64.8963, "zoom": 10},  # 미국령 버진아일랜드
    "VN": {"lat": 14.0583, "lon": 108.2772, "zoom": 5},  # 베트남
    "VU": {"lat": -15.3767, "lon": 166.9592, "zoom": 6},  # 바누아투
    "WF": {"lat": -13.7688, "lon": -177.1561, "zoom": 9},  # 왈리스 푸투나
    "WS": {"lat": -13.7590, "lon": -172.1046, "zoom": 8},  # 사모아
    "YE": {"lat": 15.5527, "lon": 48.5164, "zoom": 5},  # 예멘
    "YT": {"lat": -12.8275, "lon": 45.1662, "zoom": 9},  # 마요트
    "ZA": {"lat": -30.5595, "lon": 22.9375, "zoom": 5},  # 남아프리카 공화국
    "ZM": {"lat": -13.1339, "lon": 27.8493, "zoom": 5},  # 잠비아
    "ZW": {"lat": -19.0154, "lon": 29.1549, "zoom": 5},  # 짐바브웨
}

GEO_ALIASES = {
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

GEO_ALIASES_REVERSE = {
    "Korea, Republic of": "한국",
    "Democratic People's Republic of": "북한",
    "United States": "미국",
    "United Kingdom": "영국",
    "Russian Federation": "러시아",
    "Australia": "호주",
    "New Zealand": "뉴질랜드",
    "Switzerland": "스위스",
}


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
    if res.status_code == 200:
        # res.json() 대신 res.text를 가져와서 json.loads()로 변환!
        try:
            return json.loads(res.text)
        except json.JSONDecodeError:
            return res.text  # 만약 단순 문자열인 경우 대비
    return None


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
