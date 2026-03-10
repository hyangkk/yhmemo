"""
LS증권 Open API 연동 클라이언트

REST API 기반 국내 주식 시세 조회 및 매매 주문.
공식 문서: https://openapi.ls-sec.co.kr

필수 환경변수:
  LS_APP_KEY      - LS증권 Open API App Key
  LS_APP_SECRET   - LS증권 Open API App Secret
  LS_ACCOUNT_NO   - 계좌번호 (주문 시 필요, 예: "12345678901")
"""

import logging
import os
from datetime import datetime, timezone, timedelta

import httpx

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))
BASE_URL_LIVE = "https://openapi.ls-sec.co.kr:8080"
BASE_URL_PAPER = "https://openapi.ls-sec.co.kr:8080"  # 모의투자도 동일 포트, 앱키로 구분


def is_market_open() -> bool:
    """한국 주식시장 정규장 운영 시간인지 확인 (평일 09:00~15:30 KST)"""
    now = datetime.now(KST)
    # 주말 체크 (0=월, 5=토, 6=일)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=0, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def market_hours_message() -> str:
    """장 마감 시 안내 메시지 생성"""
    now = datetime.now(KST)
    if now.weekday() >= 5:
        return "🕐 주말에는 주식시장이 열리지 않아요. 월요일 09:00에 다시 시도해주세요."
    hour = now.hour
    if hour < 9:
        return "🕐 아직 장이 열리지 않았어요. 정규장은 09:00부터 시작합니다."
    return "🕐 장이 마감됐어요. 정규장은 평일 09:00~15:30입니다. 내일 다시 시도해주세요."


def friendly_error_message(error: Exception) -> str:
    """LS증권 API 에러를 사용자 친화적 메시지로 변환"""
    err_str = str(error) or repr(error)
    err_type = type(error).__name__

    # httpx 타임아웃/연결 에러 (str()이 빈 문자열일 수 있으므로 타입 체크 우선)
    is_timeout = isinstance(error, httpx.TimeoutException) or "timeout" in err_type.lower()
    is_connect = isinstance(error, httpx.ConnectError) or "connect" in err_type.lower()
    if is_timeout or is_connect:
        if not is_market_open():
            return f"{market_hours_message()}\n(모의투자 서버는 장 시간에만 안정적으로 운영됩니다)"
        if is_timeout:
            return "⚠️ LS증권 서버 응답 시간이 초과됐어요. 잠시 후 다시 시도해주세요."
        return "⚠️ LS증권 서버에 연결할 수 없어요. 잠시 후 다시 시도해주세요."

    # httpx HTTP 에러에서 상태코드/본문 추출
    if hasattr(error, 'response') and error.response is not None:
        try:
            body = error.response.json()
            rsp_msg = body.get("rsp_msg", "") or body.get("msg1", "") or body.get("message", "")
        except Exception:
            rsp_msg = error.response.text[:300] if error.response.text else ""

        status = error.response.status_code

        # 인증 에러
        if status == 401:
            return "🔑 인증이 만료됐어요. 잠시 후 다시 시도해주세요."
        # 서버 에러
        if status >= 500:
            if not is_market_open():
                return f"{market_hours_message()}\n(서버 응답: {rsp_msg or status})"
            return f"⚠️ LS증권 서버에 문제가 있어요. 잠시 후 다시 시도해주세요.\n({rsp_msg or status})"
        # 400 에러 - API 거부
        if status == 400:
            if not is_market_open():
                return f"{market_hours_message()}\n(API: {rsp_msg})" if rsp_msg else market_hours_message()
            return f"⚠️ 요청이 거부됐어요: {rsp_msg}" if rsp_msg else f"⚠️ 요청 오류 ({status})"

        # 기타 HTTP 에러 코드 (403, 404, 429 등)
        if rsp_msg:
            if not is_market_open():
                return f"{market_hours_message()}\n(API: {rsp_msg})"
            return f"⚠️ {rsp_msg}"
        # rsp_msg가 없는 기타 HTTP 에러
        if not is_market_open():
            return f"{market_hours_message()}\n(HTTP {status})"
        return f"⚠️ 요청 오류 (HTTP {status})"

    # 네트워크 에러 (문자열 기반 fallback)
    if "connect" in err_str.lower() or "timeout" in err_str.lower():
        if not is_market_open():
            return f"{market_hours_message()}\n(모의투자 서버는 장 시간에만 안정적으로 운영됩니다)"
        return "⚠️ LS증권 서버에 연결할 수 없어요. 잠시 후 다시 시도해주세요."

    # 기타 에러
    if not is_market_open():
        return f"{market_hours_message()}\n(오류: {err_str[:200]})" if err_str else market_hours_message()
    return f"⚠️ 오류가 발생했어요: {err_str[:200]}"


class LSSecuritiesClient:
    """LS증권 Open API REST 클라이언트"""

    def __init__(
        self,
        app_key: str | None = None,
        app_secret: str | None = None,
        account_no: str | None = None,
        paper_trading: bool = True,
    ):
        self.app_key = app_key or os.environ.get("LS_APP_KEY", "")
        self.app_secret = app_secret or os.environ.get("LS_APP_SECRET", "")
        self.account_no = account_no or os.environ.get("LS_ACCOUNT_NO", "")
        self.account_pwd = os.environ.get("LS_ACCOUNT_PWD", "0000")
        self.paper_trading = paper_trading
        self.base_url = BASE_URL_PAPER if paper_trading else BASE_URL_LIVE
        self._access_token = ""
        self._token_expires = datetime.min.replace(tzinfo=KST)
        # 실서버 토큰 (시세 조회 fallback용)
        self._live_token = ""
        self._live_token_expires = datetime.min.replace(tzinfo=KST)
        self._http = httpx.AsyncClient(timeout=15.0, verify=False)
        self._last_balance: dict | None = None
        self._last_balance_time: datetime | None = None
        self._price_cache: dict[str, dict] = {}  # {종목코드: {data, time}}

    @property
    def is_configured(self) -> bool:
        return bool(self.app_key and self.app_secret)

    # ── 인증 ────────────────────────────────────────────

    async def _ensure_token(self):
        """토큰이 없거나 만료됐으면 재발급"""
        now = datetime.now(KST)
        if self._access_token and now < self._token_expires:
            return
        await self._issue_token()

    async def _issue_token(self):
        """접근토큰 발급 (유효기간: 익일 07시)"""
        url = f"{self.base_url}/oauth2/token"
        resp = await self._http.post(
            url,
            headers={"content-type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "client_credentials",
                "appkey": self.app_key,
                "appsecretkey": self.app_secret,
                "scope": "oob",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        self._access_token = data["access_token"]
        # 토큰 유효기간: 익일 07시 (안전하게 당일 자정으로 설정)
        tomorrow = datetime.now(KST).replace(hour=6, minute=50, second=0, microsecond=0)
        if tomorrow < datetime.now(KST):
            tomorrow += timedelta(days=1)
        self._token_expires = tomorrow
        mode = "모의투자" if self.paper_trading else "실전투자"
        logger.info(f"[ls] 접근토큰 발급 완료 ({mode})")

    async def _ensure_live_token(self):
        """실서버 토큰 발급 (시세 조회 fallback용)"""
        now = datetime.now(KST)
        if self._live_token and now < self._live_token_expires:
            return
        url = f"{BASE_URL_LIVE}/oauth2/token"
        resp = await self._http.post(
            url,
            headers={"content-type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "client_credentials",
                "appkey": self.app_key,
                "appsecretkey": self.app_secret,
                "scope": "oob",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        self._live_token = data["access_token"]
        tomorrow = datetime.now(KST).replace(hour=6, minute=50, second=0, microsecond=0)
        if tomorrow < datetime.now(KST):
            tomorrow += timedelta(days=1)
        self._live_token_expires = tomorrow
        logger.info("[ls] 실서버 접근토큰 발급 완료 (시세 조회용)")

    def _auth_header(self, tr_cd: str, tr_cont: str = "N") -> dict:
        """API 요청용 공통 헤더"""
        return {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {self._access_token}",
            "tr_cd": tr_cd,
            "tr_cont": tr_cont,
            "tr_cont_key": "",
        }

    # ── 시세 조회 ────────────────────────────────────────

    async def _fetch_price_from(self, base_url: str, token: str, stock_code: str) -> dict:
        """특정 서버에서 시세 조회"""
        url = f"{base_url}/stock/market-data"
        headers = {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {token}",
            "tr_cd": "t1101",
            "tr_cont": "N",
            "tr_cont_key": "",
        }
        resp = await self._http.post(
            url, headers=headers, json={"t1101InBlock": {"shcode": stock_code}},
        )
        resp.raise_for_status()
        block = resp.json().get("t1101OutBlock", {})
        return {
            "종목명": block.get("hname", ""),
            "현재가": int(block.get("price", 0)),
            "등락부호": block.get("sign", ""),
            "전일대비": int(block.get("change", 0)),
            "등락률": float(block.get("diff", 0)),
            "거래량": int(block.get("volume", 0)),
            "매도호가1": int(block.get("offerho1", 0)),
            "매수호가1": int(block.get("bidho1", 0)),
            "raw": block,
            "cached": False,
        }

    async def get_price(self, stock_code: str) -> dict:
        """주식 현재가 호가 조회 (t1101). 모의서버 실패 시 실서버 fallback.

        Args:
            stock_code: 종목코드 (예: "005930" = 삼성전자)

        Returns:
            dict with price info
        """
        # 1차: 기본 서버 (모의투자 or 실전)
        try:
            await self._ensure_token()
            result = await self._fetch_price_from(self.base_url, self._access_token, stock_code)
            self._price_cache[stock_code] = {"data": result, "time": datetime.now(KST)}
            return result
        except Exception as e:
            logger.warning(f"[ls] 시세 조회 실패 ({stock_code}): {e}")

        # 2차: 모의투자 모드이면 실서버로 fallback (시세는 읽기 전용)
        if self.paper_trading:
            try:
                await self._ensure_live_token()
                result = await self._fetch_price_from(BASE_URL_LIVE, self._live_token, stock_code)
                self._price_cache[stock_code] = {"data": result, "time": datetime.now(KST)}
                logger.info(f"[ls] 실서버 fallback 시세 조회 성공 ({stock_code})")
                return result
            except Exception as e2:
                logger.warning(f"[ls] 실서버 fallback도 실패 ({stock_code}): {e2}")

        # 3차: 캐시
        cached = self._price_cache.get(stock_code)
        if cached:
            result = dict(cached["data"])
            result["cached"] = True
            result["cached_time"] = cached["time"]
            return result

        return {"unavailable": True, "error": e, "종목코드": stock_code}

    async def get_stock_info(self, stock_code: str) -> dict:
        """주식 종목 마스터 조회 (t1102)"""
        await self._ensure_token()
        url = f"{self.base_url}/stock/market-data"
        resp = await self._http.post(
            url,
            headers=self._auth_header("t1102"),
            json={"t1102InBlock": {"shcode": stock_code}},
        )
        resp.raise_for_status()
        return resp.json().get("t1102OutBlock", {})

    # ── 잔고 조회 ────────────────────────────────────────

    async def get_balance(self) -> dict:
        """주식 잔고 조회 (t0424)

        Returns:
            dict with account balance info. 실패 시 캐시된 잔고 반환.
        """
        try:
            await self._ensure_token()
            url = f"{self.base_url}/stock/accno"
            resp = await self._http.post(
                url,
                headers=self._auth_header("t0424"),
                json={
                    "t0424InBlock": {
                        "pession": "0",
                        "chegb": "0",
                        "dangb": "0",
                        "charge": "1",
                        "cts_expcode": "",
                        "accno": self.account_no,
                    }
                },
            )
            resp.raise_for_status()
            data = resp.json()
            summary = data.get("t0424OutBlock", {})
            holdings = data.get("t0424OutBlock1", [])
            result = {
                "summary": {
                    "추정순자산": int(summary.get("sunamt", 0)),
                    "총매입금액": int(summary.get("mamt", 0)),
                    "추정손익": int(summary.get("dtsunik", 0)),
                    "수익률": float(summary.get("sunamt1", 0)),
                },
                "holdings": [
                    {
                        "종목코드": h.get("expcode", ""),
                        "종목명": h.get("jangname", ""),
                        "잔고수량": int(h.get("janqty", 0)),
                        "매입단가": int(h.get("pamt", 0)),
                        "현재가": int(h.get("price", 0)),
                        "평가손익": int(h.get("dtsunik", 0)),
                        "수익률": float(h.get("sunikrt", 0)),
                    }
                    for h in holdings
                ],
                "cached": False,
            }
            # 성공 시 캐시 갱신
            self._last_balance = result
            self._last_balance_time = datetime.now(KST)
            return result
        except Exception as e:
            logger.warning(f"[ls] 잔고 조회 실패: {e}")
            # 실패 시 캐시된 잔고 반환
            if self._last_balance:
                cached = dict(self._last_balance)
                cached["cached"] = True
                cached["cached_time"] = self._last_balance_time
                return cached
            # 캐시도 없으면 빈 결과 + 에러 정보 반환
            return {
                "summary": {},
                "holdings": [],
                "cached": False,
                "unavailable": True,
                "error": e,
            }

    # ── 주문 ─────────────────────────────────────────────

    async def buy(
        self,
        stock_code: str,
        qty: int,
        price: int = 0,
        order_type: str = "03",
    ) -> dict:
        """매수 주문 (CSPAT00601)

        Args:
            stock_code: 종목코드
            qty: 주문 수량
            price: 주문 가격 (0이면 시장가)
            order_type: 호가유형 ("00"=지정가, "03"=시장가)

        Returns:
            주문 결과 dict
        """
        return await self._place_order(
            stock_code=stock_code,
            qty=qty,
            price=price,
            order_type=order_type,
            bns_tp="2",  # 2=매수
        )

    async def sell(
        self,
        stock_code: str,
        qty: int,
        price: int = 0,
        order_type: str = "03",
    ) -> dict:
        """매도 주문 (CSPAT00601)

        Args:
            stock_code: 종목코드
            qty: 주문 수량
            price: 주문 가격 (0이면 시장가)
            order_type: 호가유형 ("00"=지정가, "03"=시장가)

        Returns:
            주문 결과 dict
        """
        return await self._place_order(
            stock_code=stock_code,
            qty=qty,
            price=price,
            order_type=order_type,
            bns_tp="1",  # 1=매도
        )

    async def _place_order(
        self,
        stock_code: str,
        qty: int,
        price: int,
        order_type: str,
        bns_tp: str,
    ) -> dict:
        """주문 공통 처리 (CSPAT00601)"""
        action = "매수" if bns_tp == "2" else "매도"
        try:
            await self._ensure_token()
        except Exception as e:
            logger.error(f"[ls] 토큰 발급 실패 ({type(e).__name__}): {e or repr(e)}")
            raise
        logger.info(f"[ls] {action} 주문 요청: {stock_code} {qty}주, base_url={self.base_url}")
        url = f"{self.base_url}/stock/order"
        resp = await self._http.post(
            url,
            headers=self._auth_header("CSPAT00601"),
            json={
                "CSPAT00601InBlock1": {
                    "IsuNo": stock_code,
                    "OrdQty": qty,
                    "OrdPrc": price,
                    "BnsTpCode": bns_tp,
                    "OrdprcPtnCode": order_type,
                    "MgntrnCode": "000",
                    "LoanDt": "",
                    "OrdCndiTpCode": "0",
                    "AcntNo": self.account_no,
                    "InptPwd": self.account_pwd,
                }
            },
        )
        # HTTP 에러 시에도 응답 본문의 에러 메시지를 보존
        try:
            data = resp.json()
        except Exception:
            data = {}
        if resp.status_code != 200:
            rsp_msg = data.get("rsp_msg", "") or data.get("msg1", "") or resp.text[:300]
            logger.error(f"[ls] 주문 실패 (HTTP {resp.status_code}): {rsp_msg}")
            return {
                "결과": "실패",
                "주문번호": "",
                "종목코드": stock_code,
                "주문유형": action,
                "수량": qty,
                "가격": price if price else "시장가",
                "에러": rsp_msg,
                "raw": data,
            }
        out1 = data.get("CSPAT00601OutBlock1", {})
        out2 = data.get("CSPAT00601OutBlock2", {})
        rsp_msg = data.get("rsp_msg", "")
        success = bool(out2.get("OrdNo"))
        if not success:
            logger.warning(f"[ls] 주문 실패 (API): rsp_cd={data.get('rsp_cd')}, rsp_msg={rsp_msg}")
        return {
            "결과": "성공" if success else "실패",
            "주문번호": out2.get("OrdNo", ""),
            "종목코드": out1.get("IsuNo", stock_code),
            "주문유형": action,
            "수량": qty,
            "가격": price if price else "시장가",
            "에러": "" if success else (rsp_msg or "주문번호가 반환되지 않았습니다"),
            "raw": data,
        }

    # ── 정리 ─────────────────────────────────────────────

    async def close(self):
        await self._http.aclose()


async def fetch_naver_volume(stock_code: str) -> int | None:
    """네이버 증권에서 거래량 조회 (비교 검증용)"""
    url = f"https://polling.finance.naver.com/api/realtime/domestic/stock/{stock_code}"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            data = resp.json()
            # datas[0].tradeVolume or accumulatedTradingVolume
            item = data.get("datas", [{}])[0]
            vol = item.get("accumulatedTradingVolume") or item.get("tradeVolume")
            return int(str(vol).replace(",", "")) if vol else None
    except Exception as e:
        logger.warning(f"[naver] 거래량 조회 실패 ({stock_code}): {e}")
        return None
