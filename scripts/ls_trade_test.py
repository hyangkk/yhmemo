#!/usr/bin/env python3
"""
LS증권 API 매매 연결 테스트

사용법:
  # 환경변수 설정 후 실행
  export LS_APP_KEY=...
  export LS_APP_SECRET=...
  export LS_ACCOUNT_NO=...
  export LS_MODE=mock  # mock=모의투자, real=실전

  python scripts/ls_trade_test.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "slack-agents"))

from agents.invest.ls_broker import LSBroker


async def main():
    broker = LSBroker()

    if not broker.app_key or not broker.app_secret:
        print("ERROR: LS_APP_KEY, LS_APP_SECRET 환경변수를 설정하세요")
        sys.exit(1)

    print(f"=== LS증권 API 연결 테스트 (mode: {broker.mode}) ===\n")

    # 1. 토큰 발급 테스트
    print("[1] 토큰 발급...")
    try:
        await broker._ensure_token()
        print(f"    OK - token: {broker._token.access_token[:20]}...\n")
    except Exception as e:
        print(f"    FAIL - {e}")
        sys.exit(1)

    # 2. 현재가 조회 (삼성전자)
    print("[2] 현재가 조회 (005930 삼성전자)...")
    try:
        price = await broker.get_price("005930")
        print(f"    {price['name']} | 현재가: {price['price']:,}원")
        print(f"    등락: {price['change']:+,}원 ({price['change_rate']:+.2f}%)")
        print(f"    거래량: {price['volume']:,}\n")
    except Exception as e:
        print(f"    FAIL - {e}\n")

    # 3. 잔고 조회
    print("[3] 잔고 조회...")
    try:
        balance = await broker.get_balance()
        print(f"    총 평가: {balance['total_eval']:,}원")
        print(f"    총 손익: {balance['total_profit']:,}원 ({balance['profit_rate']:+.2f}%)")
        if balance["holdings"]:
            print(f"    보유종목:")
            for h in balance["holdings"]:
                print(f"      - {h['name']}({h['code']}): {h['qty']}주 "
                      f"| 평균 {h['avg_price']:,}원 -> 현재 {h['cur_price']:,}원 "
                      f"({h['profit_rate']:+.2f}%)")
        else:
            print(f"    보유종목 없음")
        print()
    except Exception as e:
        print(f"    FAIL - {e}\n")

    # 4. 매수 테스트 (모의투자에서만)
    if broker.mode == "mock":
        print("[4] 모의 매수 테스트 (삼성전자 1주 시장가)...")
        try:
            result = await broker.buy("005930", qty=1, order_type="market")
            print(f"    주문번호: {result['order_no']}")
            print(f"    {result}\n")
        except Exception as e:
            print(f"    FAIL - {e}\n")

        # 5. 주문 내역 조회
        print("[5] 당일 주문 내역...")
        try:
            orders = await broker.get_orders()
            for o in orders:
                print(f"    #{o['order_no']} {o['side'].upper()} {o['name']} "
                      f"{o['qty']}주 @ {o['price']:,}원 (체결: {o['filled_qty']}주)")
            if not orders:
                print(f"    주문 내역 없음")
            print()
        except Exception as e:
            print(f"    FAIL - {e}\n")
    else:
        print("[4] 실전 모드 - 자동 매수 테스트 건너뜀\n")

    print("=== 테스트 완료 ===")


if __name__ == "__main__":
    asyncio.run(main())
