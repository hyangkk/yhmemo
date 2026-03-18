"""
서킷 브레이커 패턴 - 외부 API 장애 시 빠른 실패로 시스템 보호

상태: CLOSED (정상) → OPEN (차단) → HALF_OPEN (시험)
"""
import asyncio
import time
import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import Callable, Any
from functools import wraps

logger = logging.getLogger(__name__)

class CircuitState(Enum):
    CLOSED = "closed"      # 정상 - 요청 통과
    OPEN = "open"          # 차단 - 즉시 실패
    HALF_OPEN = "half_open"  # 시험 - 제한적 요청 허용

@dataclass
class CircuitBreaker:
    name: str
    failure_threshold: int = 5       # 연속 실패 N회 시 OPEN
    recovery_timeout: float = 60.0   # OPEN 후 N초 뒤 HALF_OPEN
    half_open_max_calls: int = 1     # HALF_OPEN에서 허용할 시험 요청 수

    # 내부 상태
    state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    failure_count: int = field(default=0, init=False)
    last_failure_time: float = field(default=0.0, init=False)
    half_open_calls: int = field(default=0, init=False)

    def _should_try_reset(self) -> bool:
        """OPEN 상태에서 복구 타임아웃이 지났는지 확인"""
        return time.monotonic() - self.last_failure_time >= self.recovery_timeout

    def record_success(self):
        """성공 기록 → CLOSED로 복귀"""
        self.failure_count = 0
        self.half_open_calls = 0
        if self.state != CircuitState.CLOSED:
            logger.info(f"[CircuitBreaker:{self.name}] 복구 완료 → CLOSED")
        self.state = CircuitState.CLOSED

    def record_failure(self):
        """실패 기록"""
        self.failure_count += 1
        self.last_failure_time = time.monotonic()

        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.OPEN
            logger.warning(f"[CircuitBreaker:{self.name}] HALF_OPEN에서 실패 → OPEN")
        elif self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            logger.warning(f"[CircuitBreaker:{self.name}] 연속 {self.failure_count}회 실패 → OPEN ({self.recovery_timeout}초 후 재시도)")

    def can_execute(self) -> bool:
        """요청 실행 가능 여부"""
        if self.state == CircuitState.CLOSED:
            return True
        if self.state == CircuitState.OPEN:
            if self._should_try_reset():
                self.state = CircuitState.HALF_OPEN
                self.half_open_calls = 0
                logger.info(f"[CircuitBreaker:{self.name}] 복구 타임아웃 경과 → HALF_OPEN")
                return True
            return False
        if self.state == CircuitState.HALF_OPEN:
            return self.half_open_calls < self.half_open_max_calls
        return False

    def get_status(self) -> dict:
        """현재 상태 반환"""
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self.failure_count,
            "last_failure": self.last_failure_time,
        }


class CircuitOpenError(Exception):
    """서킷이 열려있어 요청 차단됨"""
    def __init__(self, breaker_name: str):
        super().__init__(f"서킷 '{breaker_name}' OPEN 상태 - 요청 차단됨")
        self.breaker_name = breaker_name


# 글로벌 서킷 브레이커 레지스트리
_breakers: dict[str, CircuitBreaker] = {}

def get_breaker(name: str, **kwargs) -> CircuitBreaker:
    """이름으로 서킷 브레이커 가져오기 (없으면 생성)"""
    if name not in _breakers:
        _breakers[name] = CircuitBreaker(name=name, **kwargs)
    return _breakers[name]

def get_all_status() -> list[dict]:
    """모든 서킷 브레이커 상태 반환"""
    return [b.get_status() for b in _breakers.values()]

def circuit_protected(breaker_name: str, **breaker_kwargs):
    """데코레이터: 함수에 서킷 브레이커 적용

    Usage:
        @circuit_protected("ls_securities", failure_threshold=3, recovery_timeout=120)
        async def get_stock_price(code: str):
            ...
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            breaker = get_breaker(breaker_name, **breaker_kwargs)
            if not breaker.can_execute():
                raise CircuitOpenError(breaker_name)
            try:
                if breaker.state == CircuitState.HALF_OPEN:
                    breaker.half_open_calls += 1
                result = await func(*args, **kwargs)
                breaker.record_success()
                return result
            except CircuitOpenError:
                raise
            except Exception as e:
                breaker.record_failure()
                raise
        return wrapper
    return decorator
