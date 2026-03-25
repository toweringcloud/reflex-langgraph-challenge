# Geo Master Agent 설계도

## 1. 에이전트 개요

- **이름**: 지오 마스터 에이전트
- **목적**: 국가 간 지정학적 이슈를 분석하고 타임라인 카툰 스토리를 생성
- **핵심 기능**:
  1. 지정학적 이슈 국가 추출
  2. 타임라인 카툰 텍스트 및 프롬프트 생성
  3. 타임라인 카툰 이미지 생성 및 출력

## 2. 그래프 구조 (Graph Structure)

- **State**: `input_country`, `related_countries`, `timeline_story`
- **Nodes**:
  - `find_issues`: 입력된 국가와 관련된 최근 100년 내 이슈 국가 검색
  - `create_cartoon`: 이슈를 타임라인 카툰 형식의 텍스트로 변환
- **Edges**: `START` -> `find_issues` -> `create_cartoon` -> `END`
