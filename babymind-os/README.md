# BabyMind OS - 육아 AI 인텔리전스 CCTV MCP 서비스

Tapo CCTV 영상을 Claude Vision으로 분석하여 아이의 활동, 발달, 안전을 모니터링하고
MCP(Model Context Protocol)를 통해 부모의 AI 에이전트에 데이터를 제공하는 플랫폼.

## 아키텍처

```
Tapo CCTV (RTSP)
    ↓
[Stream Capture] 30초마다 프레임 캡처
    ↓
[Claude Vision] 물체감지 + 행동인식 + 안전감지
    ↓
[Activity Tracker] 통계 집계 + 트렌드 분석
    ↓
┌─────────────────┬──────────────────┐
│ MCP Server      │ Notifications    │
│ (리소스/도구)   │ (이메일/카톡)    │
│ 외부 AI 에이전트│ 부모 직접 알림   │
└─────────────────┴──────────────────┘
```

## 빠른 시작

```bash
# 1. 환경변수 설정
cp .env.example .env
# .env 파일에 Tapo 계정, Anthropic API 키 등 입력

# 2. 의존성 설치
pip install -r requirements.txt

# 3. 모니터링 시작
python main.py

# 4. 단일 이미지 테스트 (개발용)
python main.py --test-frame ./test_image.jpg

# 5. MCP 서버 모드
python main.py --mcp
```

## MCP 리소스

| URI | 설명 |
|-----|------|
| `babymind://activity-log` | 오늘의 활동 로그 |
| `babymind://toy-affinity` | 장난감 선호도 (7일) |
| `babymind://development-report` | 발달 단계 리포트 |
| `babymind://daily-digest` | 일일 종합 요약 |
| `babymind://safety-log` | 안전 이벤트 로그 |
| `babymind://child-profile` | 아이 프로필 |

## MCP 도구

| 도구 | 설명 |
|------|------|
| `get_toy_recommendation` | 나이/관심도 기반 장난감 추천 |
| `get_daily_report` | 일일 리포트 자연어 생성 |
| `trigger_alert` | 부모에게 즉시 알림 발송 |
| `ask_about_child` | "오늘 뭐하고 놀았어?" 등 자연어 질문 |

## 디렉토리 구조

```
babymind-os/
├── main.py                    # 메인 오케스트레이터
├── config/
│   └── settings.py            # 환경변수 및 설정
├── core/
│   ├── stream_capture.py      # Tapo RTSP 스트림 캡처
│   ├── models.py              # 데이터 모델 (Pydantic)
│   └── storage.py             # Supabase 저장소
├── analyzers/
│   ├── vision_analyzer.py     # Claude Vision 분석 엔진
│   └── activity_tracker.py    # 활동 추적 및 통계
├── mcp_server/
│   └── server.py              # MCP 프로토콜 서버
├── notifications/
│   └── notifier.py            # 이메일/카카오톡 알림
├── scripts/
│   └── setup_db.sql           # Supabase 테이블 생성
├── mcp_config.json            # MCP 클라이언트 설정 예시
├── Dockerfile                 # 컨테이너 빌드
└── requirements.txt           # Python 의존성
```
