#!/bin/bash
# AI 에이전트 실행 스크립트
cd "$(dirname "$0")"

# 가상환경 없으면 생성
if [ ! -d "venv" ]; then
    echo "가상환경 생성 중..."
    python3 -m venv venv
fi

# 가상환경 활성화
source venv/bin/activate

# 패키지 설치
pip install -r requirements.txt -q

# .env 확인
if [ ! -f ".env" ]; then
    echo "❌ .env 파일이 없습니다. .env.example을 복사해서 설정해주세요:"
    echo "   cp .env.example .env"
    exit 1
fi

echo "🚀 AI 에이전트 시스템을 시작합니다..."
python3 orchestrator.py
