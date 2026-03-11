"""
Claude Vision 기반 영상 프레임 분석 엔진
- 캡처된 프레임을 Claude Vision API로 분석
- 물체 감지, 행동 인식, 안전 이벤트 추출
- 구조화된 JSON 결과 반환
"""

import json
import logging
from datetime import datetime
from typing import Optional

import anthropic

from config import settings
from core.models import (
    AlertLevel,
    ChildAction,
    DetectedObject,
    FrameAnalysis,
    SafetyEvent,
)

logger = logging.getLogger("babymind.analyzer")

# 분석 프롬프트 (한국어)
FRAME_ANALYSIS_PROMPT = """당신은 육아 AI 전문가입니다. CCTV 프레임 이미지를 분석하여 아이의 활동을 관찰합니다.

## 아이 정보
- 이름: {child_name}
- 나이: {child_age_months}개월

## 분석 요청
이 CCTV 프레임을 분석하여 다음 정보를 JSON으로 반환해주세요:

```json
{{
  "scene_summary": "장면을 한 문장으로 설명",
  "child_detected": true/false,
  "child_position": "화면 내 아이의 위치 (예: 중앙, 좌측)",
  "child_posture": "자세 (서있음/앉아있음/누워있음/걷고있음/뛰고있음)",
  "child_emotion": "감정 상태 추정 (즐거움/집중/평온/불안/울음)",
  "objects": [
    {{"name": "물체명", "category": "장난감|가구|사람|기타", "confidence": 0.9, "location": "위치"}}
  ],
  "actions": [
    {{"action": "행동 설명", "body_part": "관련 신체부위", "motor_type": "fine_motor|gross_motor", "intensity": "low|normal|high"}}
  ],
  "toy_interactions": {{
    "장난감명": 0.8
  }},
  "safety_events": [
    {{"event_type": "이벤트유형", "severity": "info|warning|danger", "description": "설명", "location": "위치"}}
  ],
  "special_events": ["특별한 순간이 있으면 기록"]
}}
```

## 분석 가이드라인
1. **장난감 상호작용**: 아이가 직접 만지거나 가까이서 응시하는 장난감의 상호작용 강도를 0~1로 평가
2. **운동 발달**: 소근육(블록 쌓기, 물건 집기)과 대근육(걷기, 뛰기, 미끄럼틀) 구분
3. **안전**: 위험한 행동(높은 곳 오르기, 날카로운 물체, 주방 접근)은 반드시 safety_events에 기록
4. **특별한 순간**: 첫 걸음마, 새로운 행동, 환하게 웃는 얼굴 등 기록할 가치가 있는 순간
5. **아이가 없는 경우**: child_detected를 false로 설정하고 장면만 요약

반드시 유효한 JSON만 반환하세요. 다른 텍스트를 포함하지 마세요."""


class VisionAnalyzer:
    """Claude Vision API를 사용한 프레임 분석기"""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or settings.ANTHROPIC_API_KEY
        self.model = model or settings.VISION_MODEL
        self.client = anthropic.Anthropic(api_key=self.api_key)
        self._analysis_count = 0
        self._error_count = 0

    async def analyze_frame(
        self,
        frame_b64: str,
        previous_context: Optional[str] = None,
    ) -> Optional[FrameAnalysis]:
        """
        프레임 이미지를 분석하여 구조화된 결과 반환

        Args:
            frame_b64: base64 인코딩된 JPEG 이미지
            previous_context: 이전 분석 컨텍스트 (연속성 유지)

        Returns:
            FrameAnalysis 객체 또는 None (실패 시)
        """
        try:
            prompt = FRAME_ANALYSIS_PROMPT.format(
                child_name=settings.CHILD_NAME,
                child_age_months=settings.CHILD_AGE_MONTHS,
            )

            # 이전 컨텍스트가 있으면 추가 (연속 분석 시 일관성)
            if previous_context:
                prompt += f"\n\n## 이전 프레임 분석 요약\n{previous_context}"

            messages = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": frame_b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": prompt,
                        },
                    ],
                }
            ]

            response = self.client.messages.create(
                model=self.model,
                max_tokens=2000,
                messages=messages,
            )

            # 응답 파싱
            raw_text = response.content[0].text.strip()

            # JSON 블록 추출 (```json ... ``` 형식 처리)
            if "```json" in raw_text:
                raw_text = raw_text.split("```json")[1].split("```")[0].strip()
            elif "```" in raw_text:
                raw_text = raw_text.split("```")[1].split("```")[0].strip()

            data = json.loads(raw_text)

            # FrameAnalysis 모델로 변환
            analysis = self._parse_analysis(data)
            self._analysis_count += 1

            logger.info(
                f"프레임 분석 완료 #{self._analysis_count}: "
                f"아이감지={analysis.child_detected}, "
                f"물체={len(analysis.objects)}개, "
                f"행동={len(analysis.actions)}개, "
                f"안전이벤트={len(analysis.safety_events)}개"
            )

            return analysis

        except json.JSONDecodeError as e:
            self._error_count += 1
            logger.error(f"분석 결과 JSON 파싱 실패: {e}")
            return None
        except anthropic.APIError as e:
            self._error_count += 1
            logger.error(f"Claude API 오류: {e}")
            return None
        except Exception as e:
            self._error_count += 1
            logger.error(f"프레임 분석 오류: {e}")
            return None

    def _parse_analysis(self, data: dict) -> FrameAnalysis:
        """API 응답 딕셔너리를 FrameAnalysis 모델로 변환"""
        objects = []
        for obj in data.get("objects", []):
            objects.append(DetectedObject(
                name=obj.get("name", ""),
                category=obj.get("category", "기타"),
                confidence=obj.get("confidence", 0.0),
                location=obj.get("location", ""),
            ))

        actions = []
        for act in data.get("actions", []):
            actions.append(ChildAction(
                action=act.get("action", ""),
                body_part=act.get("body_part", ""),
                motor_type=act.get("motor_type", ""),
                intensity=act.get("intensity", "normal"),
            ))

        safety_events = []
        for evt in data.get("safety_events", []):
            severity_map = {
                "info": AlertLevel.INFO,
                "warning": AlertLevel.WARNING,
                "danger": AlertLevel.DANGER,
            }
            safety_events.append(SafetyEvent(
                event_type=evt.get("event_type", ""),
                severity=severity_map.get(evt.get("severity", "warning"), AlertLevel.WARNING),
                description=evt.get("description", ""),
                location=evt.get("location", ""),
            ))

        return FrameAnalysis(
            timestamp=datetime.now(),
            scene_summary=data.get("scene_summary", ""),
            child_detected=data.get("child_detected", False),
            child_position=data.get("child_position", ""),
            child_posture=data.get("child_posture", ""),
            child_emotion=data.get("child_emotion", ""),
            objects=objects,
            actions=actions,
            toy_interactions=data.get("toy_interactions", {}),
            safety_events=safety_events,
            special_events=data.get("special_events", []),
        )

    async def generate_daily_summary(
        self,
        analyses: list[FrameAnalysis],
    ) -> str:
        """하루 동안의 분석 결과를 종합하여 일일 리포트 생성"""
        if not analyses:
            return "오늘은 분석된 데이터가 없습니다."

        # 통계 집계
        toy_total_time: dict[str, int] = {}
        actions_list: list[str] = []
        safety_alerts: list[str] = []
        special_moments: list[str] = []

        for a in analyses:
            for toy, score in a.toy_interactions.items():
                if score > 0.3:  # 의미 있는 상호작용만
                    toy_total_time[toy] = toy_total_time.get(toy, 0) + 1
            for act in a.actions:
                actions_list.append(act.action)
            for evt in a.safety_events:
                safety_alerts.append(f"[{evt.severity}] {evt.description}")
            special_moments.extend(a.special_events)

        summary_data = {
            "총_분석_프레임": len(analyses),
            "장난감_사용_빈도": toy_total_time,
            "주요_활동": list(set(actions_list))[:10],
            "안전_알림": safety_alerts,
            "특별한_순간": special_moments,
        }

        # Claude로 자연어 리포트 생성
        prompt = f"""다음은 오늘 {settings.CHILD_NAME}({settings.CHILD_AGE_MONTHS}개월)의 하루 CCTV 분석 데이터입니다.
부모에게 보내는 따뜻하고 유익한 일일 리포트를 작성해주세요.

데이터: {json.dumps(summary_data, ensure_ascii=False)}

리포트 형식:
1. 오늘의 하이라이트 (2~3줄)
2. 장난감 사용 요약
3. 발달 관찰 포인트
4. 안전 관련 사항 (있는 경우만)
5. 내일을 위한 한마디

따뜻하고 전문적인 어조로, 한국어로 작성해주세요."""

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1500,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text
        except Exception as e:
            logger.error(f"일일 리포트 생성 실패: {e}")
            return f"일일 리포트 자동 생성 실패. 원본 데이터: {json.dumps(summary_data, ensure_ascii=False)}"

    @property
    def stats(self) -> dict:
        return {
            "total_analyses": self._analysis_count,
            "total_errors": self._error_count,
            "success_rate": (
                self._analysis_count / (self._analysis_count + self._error_count) * 100
                if (self._analysis_count + self._error_count) > 0
                else 0
            ),
        }
