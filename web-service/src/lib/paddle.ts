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
    description: '기본 기능',
    features: [
      '프로젝트 1개',
      '기본 교차편집',
      '클립 업로드',
    ],
    limits: {
      maxProjects: 1,
    },
  },
  plus: {
    name: 'Plus',
    price: 9, // $9/월
    priceId: process.env.NEXT_PUBLIC_PADDLE_PRICE_PLUS || '',
    description: '모든 기능 해금',
    features: [
      '프로젝트 무제한',
      'AI 감독 모드',
      '배경음악 (BGM)',
      '자동 자막',
      '타임라인 편집',
      '고급 프롬프트 편집',
    ],
    limits: {
      maxProjects: Infinity,
    },
  },
} as const;

export type PlanKey = keyof typeof PLANS;
