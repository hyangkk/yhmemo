'use client';

import { useEffect, useRef, useCallback } from 'react';
import { PADDLE_CONFIG, PLANS } from './paddle';

declare global {
  interface Window {
    Paddle?: {
      Environment: { set: (env: string) => void };
      Initialize: (opts: { token: string; eventCallback?: (event: PaddleEvent) => void }) => void;
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

export function usePaddle(opts?: {
  userId?: string;
  userEmail?: string;
  onSuccess?: (transactionId: string) => void;
}) {
  const initializedRef = useRef(false);
  const onSuccessRef = useRef(opts?.onSuccess);
  onSuccessRef.current = opts?.onSuccess;

  useEffect(() => {
    if (initializedRef.current || !window.Paddle) return;
    if (!PADDLE_CONFIG.clientToken) return;

    if (PADDLE_CONFIG.environment === 'sandbox') {
      window.Paddle.Environment.set('sandbox');
    }

    window.Paddle.Initialize({
      token: PADDLE_CONFIG.clientToken,
      eventCallback: (event) => {
        if (event.name === 'checkout.completed' && event.data?.transaction_id) {
          onSuccessRef.current?.(event.data.transaction_id);
        }
      },
    });
    initializedRef.current = true;
  }, []);

  // Paddle.js가 async 로드되므로 retry
  useEffect(() => {
    if (initializedRef.current) return;
    const timer = setInterval(() => {
      if (window.Paddle && PADDLE_CONFIG.clientToken) {
        if (PADDLE_CONFIG.environment === 'sandbox') {
          window.Paddle.Environment.set('sandbox');
        }
        window.Paddle.Initialize({
          token: PADDLE_CONFIG.clientToken,
          eventCallback: (event) => {
            if (event.name === 'checkout.completed' && event.data?.transaction_id) {
              onSuccessRef.current?.(event.data.transaction_id);
            }
          },
        });
        initializedRef.current = true;
        clearInterval(timer);
      }
    }, 500);
    return () => clearInterval(timer);
  }, []);

  const openCheckout = useCallback(() => {
    if (!window.Paddle) {
      console.error('Paddle.js not loaded');
      return;
    }
    const priceId = PLANS.plus.priceId;
    if (!priceId) {
      console.error('Paddle price ID not configured');
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
