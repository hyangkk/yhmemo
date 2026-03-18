"""
구조화된 JSON 로깅 시스템

기존 텍스트 로그를 보완하여 JSON 형식 로그도 병행 출력.
향후 OpenTelemetry, Grafana 등 관측성 도구 연동 기반.
"""
import json
import logging
import os
import time
from datetime import datetime, timezone, timedelta
from typing import Any

KST = timezone(timedelta(hours=9))


class StructuredJsonFormatter(logging.Formatter):
    """JSON 형식 로그 포매터"""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(KST).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # 추가 컨텍스트 필드 (extra 딕셔너리)
        for key in ("agent", "event", "duration_ms", "cost_usd",
                     "intent", "user", "channel", "error_type", "circuit"):
            if hasattr(record, key):
                log_entry[key] = getattr(record, key)

        # 예외 정보
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
            }

        return json.dumps(log_entry, ensure_ascii=False, default=str)


class AgentLogger:
    """에이전트 전용 구조화 로거

    Usage:
        log = AgentLogger("quote_agent")
        log.info("명언 전송 완료", event="quote_sent", duration_ms=1234)
        log.error("API 호출 실패", error_type="timeout", circuit="coingecko")
    """

    def __init__(self, name: str):
        self.logger = logging.getLogger(name)
        self.name = name

    def _log(self, level: int, message: str, **extra):
        extra["agent"] = self.name
        self.logger.log(level, message, extra=extra)

    def info(self, message: str, **extra):
        self._log(logging.INFO, message, **extra)

    def warning(self, message: str, **extra):
        self._log(logging.WARNING, message, **extra)

    def error(self, message: str, **extra):
        self._log(logging.ERROR, message, **extra)

    def debug(self, message: str, **extra):
        self._log(logging.DEBUG, message, **extra)


def setup_structured_logging(log_dir: str = None):
    """구조화된 JSON 로깅 핸들러 추가 (기존 텍스트 로깅과 병행)

    JSON 로그는 별도 파일에 기록되어 향후 로그 분석/모니터링 도구에서 파싱 가능.
    """
    if log_dir is None:
        log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "logs")
    os.makedirs(log_dir, exist_ok=True)

    # JSON 로그 파일 핸들러
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    json_handler = logging.FileHandler(
        os.path.join(log_dir, f"structured-{today}.jsonl"),
        encoding="utf-8",
    )
    json_handler.setLevel(logging.INFO)
    json_handler.setFormatter(StructuredJsonFormatter())

    # 루트 로거에 추가 (기존 텍스트 핸들러와 병행)
    logging.getLogger().addHandler(json_handler)

    return json_handler
