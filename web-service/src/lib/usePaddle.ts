'use client';

import { useEffect, useRef, useCallback } from 'react';
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
  data?: {
    transaction_id?: string;
    status?: string;
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

function initPaddle(onSuccess: React.RefObject<((id: string) => void) | undefined>) {
  if (!window.Paddle || !PADDLE_CONFIG.clientToken) return false;

  try {
    // Paddle v2: environment는 sandbox일 때만 설정
    if (PADDLE_CONFIG.environment === 'sandbox') {
      window.Paddle.Environment.set('sandbox');
    }

    window.Paddle.Initialize({
      token: PADDLE_CONFIG.clientToken,
      eventCallback: (event) => {
        if (event.name === 'checkout.completed' && event.data?.transaction_id) {
          onSuccess.current?.(event.data.transaction_id);
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
}) {
  const initializedRef = useRef(false);
  const onSuccessRef = useRef(opts?.onSuccess);
  onSuccessRef.current = opts?.onSuccess;

  // Paddle.js async 로드 대기 + 초기화
  useEffect(() => {
    if (initializedRef.current) return;

    // 즉시 시도
    if (initPaddle(onSuccessRef)) {
      initializedRef.current = true;
      return;
    }

    // 로드 대기 (500ms 간격, 최대 20초)
    let attempts = 0;
    const timer = setInterval(() => {
      attempts++;
      if (initPaddle(onSuccessRef)) {
        initializedRef.current = true;
        clearInterval(timer);
      } else if (attempts > 40) {
        console.warn('[Paddle] Failed to initialize after 20s');
        clearInterval(timer);
      }
    }, 500);
    return () => clearInterval(timer);
  }, []);

  const openCheckout = useCallback(() => {
    if (!window.Paddle) {
      console.error('[Paddle] Paddle.js not loaded');
      alert('Payment system is loading. Please try again in a moment.');
      return;
    }

    if (!initializedRef.current) {
      // 마지막 시도로 초기화
      if (initPaddle(onSuccessRef)) {
        initializedRef.current = true;
      } else {
        console.error('[Paddle] Not initialized');
        alert('Payment system is not ready. Please refresh the page.');
        return;
      }
    }

    const priceId = PLANS.plus.priceId;
    if (!priceId) {
      console.error('[Paddle] Price ID not configured');
      alert('Payment configuration error. Please contact support.');
      return;
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

    window.Paddle.Checkout.open(checkoutOpts);
  }, [opts?.userId, opts?.userEmail]);

  return { openCheckout };
}
