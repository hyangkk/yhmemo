// Paddle 결제 설정

export const PADDLE_CONFIG = {
  // Paddle 환경 (sandbox 또는 production)
  environment: (process.env.NEXT_PUBLIC_PADDLE_ENV || 'sandbox') as 'sandbox' | 'production',
  // 클라이언트 토큰 (프론트엔드용)
  clientToken: process.env.NEXT_PUBLIC_PADDLE_CLIENT_TOKEN || '',
  // API 키 (서버용)
  apiKey: process.env.PADDLE_API_KEY || '',
  // Webhook Secret
  webhookSecret: process.env.PADDLE_WEBHOOK_SECRET || '',
};

// 요금제 정의 (i18n)
export const PLANS = {
  free: {
    name: 'Free',
    price: 0,
    description: { ko: '멀티캠 · 타임라인캠 각 2회 무료', en: '2 free sessions per mode' },
    features: {
      ko: ['멀티캠 촬영 2회', '타임라인캠 촬영 2회', '기본 AI 교차편집', 'HD 화질 다운로드'],
      en: ['2 MultiCam sessions', '2 Timeline Cam sessions', 'Basic AI cross-editing', 'HD download'],
    },
    limits: { maxMulticam: 2, maxTimeline: 2 },
  },
  plus: {
    name: 'Plus',
    price: 3,
    priceId: process.env.NEXT_PUBLIC_PADDLE_PRICE_PLUS || '',
    description: { ko: '무제한 촬영 + 프리미엄 편집', en: 'Unlimited sessions + premium editing' },
    features: {
      ko: ['멀티캠 촬영 무제한', '타임라인캠 촬영 무제한', 'AI 감독 모드 편집', '배경음악 (BGM) 자동 삽입', '자동 자막 생성', '고급 프롬프트 편집'],
      en: ['Unlimited MultiCam', 'Unlimited Timeline Cam', 'AI Director mode', 'Auto BGM insertion', 'Auto subtitles', 'Advanced prompt editing'],
    },
    limits: { maxMulticam: Infinity, maxTimeline: Infinity },
  },
} as const;

export type PlanKey = keyof typeof PLANS;
