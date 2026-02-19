# yhmemo - 메모 & 뉴스 아이디어 에이전트

Firebase 기반 실시간 메모 앱과 매 시간 자동으로 주요 뉴스 3개를 수집하여 새로운 아이디어를 도출하는 AI 에이전트입니다.

---

## 뉴스 아이디어 에이전트

### 동작 방식

```
매 시간 정각
    ↓
주요 뉴스 RSS 피드에서 뉴스 3개 수집
(BBC News / Reuters / AP News)
    ↓
Claude AI가 3개 뉴스를 분석·결합
    ↓
새로운 창의적 아이디어 도출
    ↓
news-ideas/ 폴더에 마크다운으로 자동 저장 & 커밋
```

### 결과물 위치

자동 생성된 아이디어는 [`news-ideas/`](./news-ideas/) 폴더에 `YYYY-MM-DD-HH.md` 형식으로 저장됩니다.

### 필요한 GitHub Secrets 설정

저장소의 **Settings → Secrets and variables → Actions** 에서 아래 시크릿을 추가해야 합니다:

| 시크릿 이름 | 설명 |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API 키 ([발급](https://console.anthropic.com/)) |

### 수동 실행

GitHub Actions 탭 → **뉴스 아이디어 에이전트** → **Run workflow** 버튼으로 즉시 실행할 수 있습니다.

---

## 메모 앱

React + TypeScript + Vite + Firebase Firestore 기반의 실시간 메모 앱입니다.

### 주요 기능

- 실시간 Firebase 동기화
- 마크다운 미리보기
- 모바일 반응형 UI (Material UI)
- 메모 생성 / 조회 / 수정 / 삭제

### 로컬 개발 환경 설정

```bash
npm install
npm run dev
```

### 빌드

```bash
npm run build
```

---

## 프로젝트 구조

```
yhmemo/
├── .github/
│   └── workflows/
│       └── news-idea-agent.yml   # 매 시간 실행되는 뉴스 에이전트 워크플로우
├── scripts/
│   └── news_idea_agent.py        # 뉴스 수집 + AI 아이디어 생성 스크립트
├── news-ideas/                   # 자동 생성된 아이디어 저장 폴더
│   └── YYYY-MM-DD-HH.md
└── src/                          # 메모 앱 소스
    ├── components/
    ├── App.tsx
    └── firebase.ts
```
