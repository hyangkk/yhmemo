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

// 요금제 정의
export const PLANS = {
  free: {
    name: 'Free',
    price: 0,
    description: '멀티캠 · 타임라인캠 각 2회 무료',
    features: [
      '멀티캠 촬영 2회',
      '타임라인캠 촬영 2회',
      '기본 AI 교차편집',
      'HD 화질 다운로드',
    ],
    limits: {
      maxMulticam: 2,
      maxTimeline: 2,
    },
  },
  plus: {
    name: 'Plus',
    price: 9, // $9/월
    priceId: process.env.NEXT_PUBLIC_PADDLE_PRICE_PLUS || '',
    description: '무제한 촬영 + 프리미엄 편집',
    features: [
      '멀티캠 촬영 무제한',
      '타임라인캠 촬영 무제한',
      'AI 감독 모드 편집',
      '배경음악 (BGM) 자동 삽입',
      '자동 자막 생성',
      '고급 프롬프트 편집',
    ],
    limits: {
      maxMulticam: Infinity,
      maxTimeline: Infinity,
    },
  },
} as const;

export type PlanKey = keyof typeof PLANS;
