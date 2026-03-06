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
BASE_URL = "https://openapi.ls-sec.co.kr:8080"


class LSSecuritiesClient:
    """LS증권 Open API REST 클라이언트"""

    def __init__(
        self,
        app_key: str | None = None,
        app_secret: str | None = None,
        account_no: str | None = None,
    ):
        self.app_key = app_key or os.environ.get("LS_APP_KEY", "")
        self.app_secret = app_secret or os.environ.get("LS_APP_SECRET", "")
        self.account_no = account_no or os.environ.get("LS_ACCOUNT_NO", "")
        self._access_token = ""
        self._token_expires = datetime.min.replace(tzinfo=KST)
        self._http = httpx.AsyncClient(timeout=15.0, verify=False)

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
        url = f"{BASE_URL}/oauth2/token"
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
        logger.info("[ls] 접근토큰 발급 완료")

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

    async def get_price(self, stock_code: str) -> dict:
        """주식 현재가 호가 조회 (t1101)

        Args:
            stock_code: 종목코드 (예: "005930" = 삼성전자)

        Returns:
            dict with price info (hname, price, sign, change, diff, volume, etc.)
        """
        await self._ensure_token()
        url = f"{BASE_URL}/stock/market-data"
        resp = await self._http.post(
            url,
            headers=self._auth_header("t1101"),
            json={"t1101InBlock": {"shcode": stock_code}},
        )
        resp.raise_for_status()
        data = resp.json()
        block = data.get("t1101OutBlock", {})
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
        }

    async def get_stock_info(self, stock_code: str) -> dict:
        """주식 종목 마스터 조회 (t1102)"""
        await self._ensure_token()
        url = f"{BASE_URL}/stock/market-data"
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
            dict with account balance info
        """
        await self._ensure_token()
        url = f"{BASE_URL}/stock/accno"
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
                }
            },
        )
        resp.raise_for_status()
        data = resp.json()
        summary = data.get("t0424OutBlock", {})
        holdings = data.get("t0424OutBlock1", [])
        return {
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
        await self._ensure_token()
        url = f"{BASE_URL}/stock/order"
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
                }
            },
        )
        resp.raise_for_status()
        data = resp.json()
        out1 = data.get("CSPAT00601OutBlock1", {})
        out2 = data.get("CSPAT00601OutBlock2", {})
        action = "매수" if bns_tp == "2" else "매도"
        return {
            "결과": "성공" if out2.get("OrdNo") else "실패",
            "주문번호": out2.get("OrdNo", ""),
            "종목코드": out1.get("IsuNo", stock_code),
            "주문유형": action,
            "수량": qty,
            "가격": price if price else "시장가",
            "raw": data,
        }

    # ── 정리 ─────────────────────────────────────────────

    async def close(self):
        await self._http.aclose()
