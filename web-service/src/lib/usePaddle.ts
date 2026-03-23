'use client';

import { useEffect, useRef, useCallback, useState } from 'react';
import { PADDLE_CONFIG, PLANS } from './paddle';

declare global {
  interface Window {
    Paddle?: {
      Environment: { set: (env: string) => void };
      Initialize: (opts: {
        token: string;
        environment?: string;
        eventCallback?: (event: PaddleEvent) => void;
      }) => void;
      Checkout: { open: (opts: PaddleCheckoutOptions) => void };
    };
  }
}

interface PaddleEvent {
  name: string;
  type?: string;
  data?: {
    transaction_id?: string;
    id?: string;
    status?: string;
    error?: { type?: string; code?: string; detail?: string };
    [key: string]: unknown;
  };
}

interface PaddleCheckoutOptions {
  items: { priceId: string; quantity: number }[];
  customData?: Record<string, string>;
  customer?: { email?: string };
  settings?: {
    successUrl?: string;
    theme?: string;
    locale?: string;
  };
}

function initPaddle(
  onSuccess: React.RefObject<((id: string) => void) | undefined>,
  onError: React.RefObject<((msg: string) => void) | undefined>,
) {
  if (!window.Paddle || !PADDLE_CONFIG.clientToken) return false;

  try {
    if (PADDLE_CONFIG.environment === 'sandbox') {
      window.Paddle.Environment.set('sandbox');
    }

    window.Paddle.Initialize({
      token: PADDLE_CONFIG.clientToken,
      eventCallback: (event) => {
        console.log('[Paddle] Event:', event.name, event.data?.status || '');

        // checkout.completed: 결제 성공
        if (event.name === 'checkout.completed') {
          const txId = event.data?.transaction_id || (event.data?.id as string);
          if (txId) {
            onSuccess.current?.(txId);
          }
        }

        // checkout.error: 결제 실패
        if (event.name === 'checkout.error') {
          const detail = event.data?.error?.detail || 'Payment failed. Please try again.';
          console.error('[Paddle] Checkout error:', event.data?.error);
          onError.current?.(detail);
        }

        // checkout.warning: 경고
        if (event.name === 'checkout.warning') {
          console.warn('[Paddle] Checkout warning:', event.data);
        }
      },
    });
    return true;
  } catch (err) {
    console.error('[Paddle] Initialize failed:', err);
    return false;
  }
}

export function usePaddle(opts?: {
  userId?: string;
  userEmail?: string;
  onSuccess?: (transactionId: string) => void;
  onError?: (message: string) => void;
}) {
  const initializedRef = useRef(false);
  const onSuccessRef = useRef(opts?.onSuccess);
  const onErrorRef = useRef(opts?.onError);
  const [ready, setReady] = useState(false);
  onSuccessRef.current = opts?.onSuccess;
  onErrorRef.current = opts?.onError;

  useEffect(() => {
    if (initializedRef.current) return;

    if (initPaddle(onSuccessRef, onErrorRef)) {
      initializedRef.current = true;
      setReady(true);
      return;
    }

    let attempts = 0;
    const timer = setInterval(() => {
      attempts++;
      if (initPaddle(onSuccessRef, onErrorRef)) {
        initializedRef.current = true;
        setReady(true);
        clearInterval(timer);
      } else if (attempts > 40) {
        console.warn('[Paddle] Failed to initialize after 20s');
        clearInterval(timer);
      }
    }, 500);
    return () => clearInterval(timer);
  }, []);

  const openCheckout = useCallback(async () => {
    if (!window.Paddle) {
      alert('결제 시스템을 불러오는 중입니다. 잠시 후 다시 시도해주세요.');
      return;
    }

    if (!initializedRef.current) {
      if (initPaddle(onSuccessRef, onErrorRef)) {
        initializedRef.current = true;
        setReady(true);
      } else {
        alert('결제 시스템이 준비되지 않았습니다. 페이지를 새로고침해주세요.');
        return;
      }
    }

    const priceId = PLANS.plus.priceId;
    if (!priceId) {
      alert('결제 설정 오류입니다. 고객지원에 문의해주세요.');
      return;
    }

    // 서버사이드에서 Price 유효성 사전 검증
    try {
      const res = await fetch('/api/paddle/check-price');
      const data = await res.json();
      if (!data.ok) {
        console.error('[Paddle] Price validation failed:', data.error);
        alert(data.error || '결제 설정에 문제가 있습니다. 고객지원에 문의해주세요.');
        return;
      }
    } catch (err) {
      console.warn('[Paddle] Price check skipped (network error):', err);
      // 검증 실패해도 checkout 시도는 허용
    }

    const checkoutOpts: PaddleCheckoutOptions = {
      items: [{ priceId, quantity: 1 }],
      settings: {
        successUrl: `${window.location.origin}/mypage?subscribed=1`,
      },
    };

    if (opts?.userId) {
      checkoutOpts.customData = { user_id: opts.userId };
    }
    if (opts?.userEmail) {
      checkoutOpts.customer = { email: opts.userEmail };
    }

    try {
      window.Paddle.Checkout.open(checkoutOpts);
    } catch (err) {
      console.error('[Paddle] Checkout.open failed:', err);
      alert('결제창을 열 수 없습니다. 페이지를 새로고침 후 다시 시도해주세요.');
    }
  }, [opts?.userId, opts?.userEmail]);

  return { openCheckout, ready };
}
