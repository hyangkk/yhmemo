"""
LS증권 OpenAPI 매매 클라이언트

인증, 현재가 조회, 매수/매도 주문, 잔고 조회 지원.
API 문서: https://openapi.ls-sec.co.kr

환경변수:
  LS_APP_KEY, LS_APP_SECRET, LS_ACCOUNT_NO
  LS_MODE=real|mock  (기본: mock - 모의투자)
"""

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# REST API는 실전/모의 동일 URL (8080), 29015는 웹소켓 모의 전용
BASE_URL_REAL = "https://openapi.ls-sec.co.kr:8080"
BASE_URL_MOCK = "https://openapi.ls-sec.co.kr:8080"


@dataclass
class Token:
    access_token: str
    expires_at: float  # unix timestamp


class LSBroker:
    """LS증권 OpenAPI 클라이언트"""

    def __init__(
        self,
        app_key: str = "",
        app_secret: str = "",
        account_no: str = "",
        mode: str = "mock",
    ):
        self.app_key = app_key or os.environ.get("LS_APP_KEY", "")
        self.app_secret = app_secret or os.environ.get("LS_APP_SECRET", "")
        self.account_no = account_no or os.environ.get("LS_ACCOUNT_NO", "")
        self.mode = mode if mode else os.environ.get("LS_MODE", "mock")
        self.base_url = BASE_URL_REAL if self.mode == "real" else BASE_URL_MOCK
        self._token: Optional[Token] = None

    # ── 인증 ──────────────────────────────────────────

    async def _ensure_token(self):
        """토큰이 없거나 만료됐으면 재발급"""
        if self._token and time.time() < self._token.expires_at - 60:
            return
        await self._issue_token()

    async def _issue_token(self):
        """OAuth2 토큰 발급"""
        url = f"{self.base_url}/oauth2/token"
        payload = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "appsecretkey": self.app_secret,
            "scope": "oob",
        }
        async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
            resp = await client.post(url, data=payload)
            resp.raise_for_status()
            data = resp.json()

        self._token = Token(
            access_token=data["access_token"],
            expires_at=time.time() + int(data.get("expires_in", 7200)),
        )
        logger.info(f"[ls_broker] Token issued (mode={self.mode})")

    def _headers(self, tr_cd: str, tr_cont: str = "N") -> dict:
        """API 공통 헤더"""
        return {
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {self._token.access_token}",
            "tr_cd": tr_cd,
            "tr_cont": tr_cont,
            "tr_cont_key": "",
            "mac_address": "000000000000",
        }

    async def _request(self, tr_cd: str, path: str, body: dict, tr_cont: str = "N") -> dict:
        """공통 API 요청"""
        await self._ensure_token()
        url = f"{self.base_url}{path}"
        headers = self._headers(tr_cd, tr_cont)

        async with httpx.AsyncClient(timeout=15.0, verify=False) as client:
            resp = await client.post(url, headers=headers, json=body)
            logger.debug(f"[ls_broker] {tr_cd} -> {resp.status_code}: {resp.text[:500]}")
            resp.raise_for_status()
            return resp.json()

    # ── 현재가 조회 (t1102) ───────────────────────────

    async def get_price(self, stock_code: str) -> dict:
        """
        주식 현재가 조회

        Returns:
            {name, price, change, change_rate, volume, ...}
        """
        body = {
            "t1102InBlock": {
                "shcode": stock_code,
            }
        }
        data = await self._request("t1102", "/stock/market-data", body)
        block = data.get("t1102OutBlock", {})
        return {
            "code": stock_code,
            "name": block.get("hname", ""),
            "price": int(block.get("price", 0)),
            "change": int(block.get("change", 0)),
            "change_rate": float(block.get("diff", 0)),
            "volume": int(block.get("volume", 0)),
            "high": int(block.get("high", 0)),
            "low": int(block.get("low", 0)),
            "open": int(block.get("open", 0)),
        }

    # ── 매수 주문 (CSPAT00601) ────────────────────────

    async def buy(
        self,
        stock_code: str,
        qty: int,
        price: int = 0,
        order_type: str = "market",
    ) -> dict:
        """
        주식 현금 매수

        Args:
            stock_code: 종목코드 (예: "005930")
            qty: 수량
            price: 지정가 (시장가면 0)
            order_type: "market" 또는 "limit"

        Returns:
            {order_no, ...}
        """
        # 주문유형: 03=시장가, 00=지정가
        ord_prc_ptn_code = "03" if order_type == "market" else "00"
        if order_type == "market":
            price = 0

        acnt_no = self.account_no.replace("-", "")

        body = {
            "CSPAT00601InBlock1": {
                "IsuNo": f"A{stock_code}",  # A + 종목코드
                "OrdQty": qty,
                "OrdPrc": price,
                "BnsTpCode": "2",  # 2=매수
                "OrdprcPtnCode": ord_prc_ptn_code,
                "MgntrnCode": "000",
                "LoanDt": "",
                "OrdCndiTpCode": "0",
            }
        }
        data = await self._request("CSPAT00601", "/stock/order", body)
        out = self._parse_order_response(data)
        logger.info(f"[ls_broker] BUY {stock_code} x{qty} @ {price or 'market'} -> order#{out.get('OrdNo', '')}")
        return {
            "order_no": out.get("OrdNo", ""),
            "stock_code": stock_code,
            "side": "buy",
            "qty": qty,
            "price": price,
            "order_type": order_type,
            "raw": data,
        }

    # ── 매도 주문 ─────────────────────────────────────

    async def sell(
        self,
        stock_code: str,
        qty: int,
        price: int = 0,
        order_type: str = "market",
    ) -> dict:
        """
        주식 현금 매도

        Args:
            stock_code: 종목코드 (예: "005930")
            qty: 수량
            price: 지정가 (시장가면 0)
            order_type: "market" 또는 "limit"

        Returns:
            {order_no, ...}
        """
        ord_prc_ptn_code = "03" if order_type == "market" else "00"
        if order_type == "market":
            price = 0

        body = {
            "CSPAT00601InBlock1": {
                "IsuNo": f"A{stock_code}",
                "OrdQty": qty,
                "OrdPrc": price,
                "BnsTpCode": "1",  # 1=매도
                "OrdprcPtnCode": ord_prc_ptn_code,
                "MgntrnCode": "000",
                "LoanDt": "",
                "OrdCndiTpCode": "0",
            }
        }
        data = await self._request("CSPAT00601", "/stock/order", body)
        out = self._parse_order_response(data)
        logger.info(f"[ls_broker] SELL {stock_code} x{qty} @ {price or 'market'} -> order#{out.get('OrdNo', '')}")
        return {
            "order_no": out.get("OrdNo", ""),
            "stock_code": stock_code,
            "side": "sell",
            "qty": qty,
            "price": price,
            "order_type": order_type,
            "raw": data,
        }

    def _parse_order_response(self, data: dict) -> dict:
        """주문 응답에서 OutBlock을 찾아 반환 (OutBlock1 또는 OutBlock2)"""
        for key in ["CSPAT00601OutBlock2", "CSPAT00601OutBlock1", "CSPAT00601OutBlock"]:
            if key in data and data[key]:
                return data[key]
        return {}

    # ── 잔고 조회 (t0424) ────────────────────────────

    async def get_balance(self) -> dict:
        """
        주식 잔고 조회

        Returns:
            {total_eval, total_profit, profit_rate, holdings: [{code, name, qty, avg_price, cur_price, profit, profit_rate}, ...]}
        """
        body = {
            "t0424InBlock": {
                "pession": "0",
                "chegession": "0",
                "dangession": "0",
                "charge": "0",
                "cts_expcode": "",
            }
        }
        data = await self._request("t0424", "/stock/accno", body)

        out_block = data.get("t0424OutBlock", {})
        items = data.get("t0424OutBlock1", [])

        holdings = []
        for item in items:
            holdings.append({
                "code": item.get("expcode", ""),
                "name": item.get("hname", ""),
                "qty": int(item.get("janqty", 0)),
                "avg_price": int(item.get("pamt", 0)),
                "cur_price": int(item.get("price", 0)),
                "eval_amount": int(item.get("appamt", 0)),
                "profit": int(item.get("dtsunik", 0)),
                "profit_rate": float(item.get("sunikrt", 0)),
            })

        return {
            "total_eval": int(out_block.get("sunamt", 0)),
            "total_buy": int(out_block.get("mamt", 0)),
            "total_profit": int(out_block.get("sunamt1", 0)),
            "profit_rate": float(out_block.get("tsunikrt", 0)),
            "holdings": holdings,
        }

    # ── 주문 체결 내역 조회 (CSPAQ13700) ──────────────

    async def get_orders(self) -> list[dict]:
        """
        당일 주문/체결 내역 조회

        Returns:
            [{order_no, stock_code, name, side, qty, price, status}, ...]
        """
        body = {
            "CSPAQ13700InBlock1": {
                "OrdMktCode": "00",
                "BnsTpCode": "0",
                "IsuNo": "",
                "ExecYn": "0",
                "OrdDt": "",
                "SrtOrdNo2": 0,
                "BkseqTpCode": "0",
                "OrdPtnCode": "00",
            }
        }
        try:
            data = await self._request("CSPAQ13700", "/stock/accno", body)
        except httpx.HTTPStatusError as e:
            logger.warning(f"[ls_broker] get_orders failed: {e}")
            # fallback: t0425
            return await self._get_orders_t0425()
        items = data.get("CSPAQ13700OutBlock3", [])

        orders = []
        for item in items:
            orders.append({
                "order_no": item.get("OrdNo", ""),
                "stock_code": item.get("IsuNo", "").lstrip("A"),
                "name": item.get("IsuNm", ""),
                "side": "buy" if item.get("BnsTpCode") == "2" else "sell",
                "qty": int(item.get("OrdQty", 0)),
                "price": int(item.get("OrdPrc", 0)),
                "filled_qty": int(item.get("ExecQty", 0)),
                "status": item.get("ExecTpNm", ""),
            })
        return orders

    async def _get_orders_t0425(self) -> list[dict]:
        """t0425 fallback"""
        body = {
            "t0425InBlock": {
                "expcode": "",
                "chegession": "0",
                "sortgb": "0",
                "cts_ordno": "",
            }
        }
        try:
            data = await self._request("t0425", "/stock/accno", body)
        except Exception as e:
            logger.warning(f"[ls_broker] t0425 also failed: {e}")
            return []
        items = data.get("t0425OutBlock1", [])

        orders = []
        for item in items:
            orders.append({
                "order_no": item.get("ordno", ""),
                "stock_code": item.get("expcode", ""),
                "name": item.get("hname", ""),
                "side": "buy" if item.get("medession") == "2" else "sell",
                "qty": int(item.get("qty", 0)),
                "price": int(item.get("price", 0)),
                "filled_qty": int(item.get("cheqty", 0)),
                "status": item.get("ordermtd", ""),
            })
        return orders
