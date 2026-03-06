"""샘플 투자 전략 리포트를 슬랙으로 전송"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from slack_sdk.web.async_client import AsyncWebClient

SAMPLE_REPORT = """*투자 전략 리포트* | 2026-03-06 09:00 오전
========================================

*[핵심 뉴스 & 시그널]*

1. *연준 3월 FOMC 동결 전망 강화, 6월 인하 기대 유지*
   - 내용: 파월 의장이 "데이터 의존적 접근"을 재확인. 시장은 6월 25bp 인하를 65% 확률로 반영 중
   - 영향 섹터: 금융, 부동산, 성장주 전반
   - 시장 영향: 중립~긍정 / 금리 인하 기대가 유지되면서 성장주에 우호적 환경 지속

2. *엔비디아 GTC 2026 앞두고 차세대 GPU "Rubin Ultra" 스펙 유출*
   - 내용: HBM4 탑재, 학습 성능 기존 대비 3배. 대만 TSMC 3nm 공정 확정. 양산은 2026 Q4 예상
   - 영향 섹터: AI 반도체, HBM(SK하이닉스/삼성전자), 장비(ASML/도쿄일렉트론)
   - 시장 영향: 긍정 / AI 인프라 투자 사이클 장기화 신호

3. *중국 양회 폐막 - GDP 5% 목표, 부양책 기대 이하*
   - 내용: 재정적자율 3.0%, 특별국채 1조위안. 시장 기대(1.5조) 하회. 내수 소비 부양 구체안 부족
   - 영향 섹터: 중국 소비재, 원자재, 한국 수출주(화학/철강)
   - 시장 영향: 부정 / 중국 수요 회복 지연 → 원자재 약세, 한국 수출주 부담

4. *국제유가 WTI $72→$68 급락, OPEC+ 증산 합의*
   - 내용: 사우디 주도로 4월부터 일 50만배럴 증산. 러시아-우크라이나 휴전 기대도 반영
   - 영향 섹터: 정유/화학(부정), 항공/해운(긍정), 신재생에너지(중립)
   - 시장 영향: 혼조 / 에너지 섹터 약세 vs 운송·소비 섹터 수혜

5. *한국 2월 수출 +8.2% YoY, 반도체 +32% 역대급*
   - 내용: AI 서버용 HBM·DDR5 수출이 견인. 대중국 수출은 -2.1%로 여전히 부진
   - 영향 섹터: 반도체(SK하이닉스, 삼성전자), IT 하드웨어
   - 시장 영향: 긍정 / 반도체 수출 호조가 코스피 지지

*[섹터별 영향 분석]*

| 섹터 | 방향 | 근거 |
|------|------|------|
| AI 반도체 | :arrow_up: 상승 | 엔비디아 신규 GPU + 한국 HBM 수출 호조 |
| 금융 | :arrow_right: 보합 | 금리 동결 지속, 인하 기대는 긍정적이나 단기 모멘텀 제한 |
| 정유/화학 | :arrow_down: 하락 | 유가 급락 + 중국 부양 기대 이하 |
| 항공/해운 | :arrow_up: 상승 | 유가 하락 → 연료비 절감 수혜 |
| 중국 관련 수출주 | :arrow_down: 약세 | 양회 부양책 실망 → 수요 회복 지연 |
| 바이오/헬스케어 | :arrow_right: 중립 | 특별 촉매 부재, 개별 종목 장세 |

*[투자 전략 제안]*

1. *AI 반도체 비중 확대*
   - 대상: SK하이닉스, 한미반도체, TIGER 미국필라델피아반도체나스닥 ETF
   - 액션: 비중 확대 (현재 비중 대비 +5~10%)
   - 근거: HBM 수출 역대급 + 엔비디아 차세대 GPU 수요 확인. 2026 하반기까지 실적 가시성 높음
   - 리스크: 엔비디아 GTC에서 예상 하회 시 단기 차익실현 가능

2. *항공주 트레이딩 매수*
   - 대상: 대한항공, 제주항공
   - 액션: 단기 매수 (2~4주 보유)
   - 근거: 유가 $68 하락 + 봄 여행 시즌. 연료비 하락분이 1Q 실적에 반영
   - 리스크: 유가 반등 시 빠르게 청산 필요

3. *정유/화학 비중 축소*
   - 대상: S-Oil, 롯데케미칼
   - 액션: 비중 축소 또는 관망
   - 근거: OPEC+ 증산 + 중국 수요 부진 이중 악재
   - 리스크: 지정학 리스크 재부각 시 유가 급반등 가능성

4. *미국 성장주 ETF 분할매수*
   - 대상: QQQ, TIGER 미국나스닥100
   - 액션: 3회 분할매수 (이번 주 1차)
   - 근거: 6월 금리 인하 기대 유지 + AI 모멘텀. 조정 시 매수 기회
   - 리스크: 인플레이션 재반등 → 인하 지연 시나리오

*[오늘의 한줄 요약]*
AI 반도체는 여전히 강하고, 유가 하락이 새로운 기회를 열어주는 국면 - 섹터 로테이션에 주목하라.
"""

CHANNEL = "ai-invest"


async def main():
    token = os.environ.get("SLACK_BOT_TOKEN")
    if not token:
        print("ERROR: SLACK_BOT_TOKEN not set in .env")
        sys.exit(1)

    client = AsyncWebClient(token=token)

    # resolve channel name -> id
    result = await client.conversations_list(types="public_channel")
    channel_id = None
    for ch in result["channels"]:
        if ch["name"] == CHANNEL:
            channel_id = ch["id"]
            break

    if not channel_id:
        print(f"ERROR: Channel '{CHANNEL}' not found")
        sys.exit(1)

    await client.chat_postMessage(
        channel=channel_id,
        text=SAMPLE_REPORT,
        unfurl_links=False,
    )
    print(f"Sample report sent to #{CHANNEL}")


if __name__ == "__main__":
    asyncio.run(main())
