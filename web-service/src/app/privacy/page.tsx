'use client';

import { useLang, LangToggle } from '@/lib/i18n';

const t = {
  ko: {
    title: '개인정보처리방침 (Privacy Policy)',
    lastUpdated: '최종 수정일: 2026년 3월 17일',
    s1Title: '1. 수집하는 정보',
    s1Desc: '서비스는 다음 정보를 수집합니다:',
    s1Items: [
      { bold: '계정 정보:', text: 'Google 로그인 시 제공되는 이름, 이메일, 프로필 사진' },
      { bold: '영상 데이터:', text: '사용자가 촬영하여 업로드한 영상 클립' },
      { bold: '결제 정보:', text: 'Paddle을 통해 처리되며, 서비스는 결제 카드 정보를 직접 저장하지 않습니다' },
      { bold: '사용 데이터:', text: '서비스 이용 기록, 접속 로그' },
    ],
    s2Title: '2. 정보의 이용 목적',
    s2Items: [
      '서비스 제공 및 영상 편집 처리',
      '계정 관리 및 고객 지원',
      '서비스 개선 및 분석',
      '결제 처리 및 구독 관리',
    ],
    s3Title: '3. 정보의 보관 및 삭제',
    s3Desc: '업로드된 영상은 편집 처리 후 30일 이내에 서버에서 자동 삭제됩니다. 계정 삭제 요청 시 모든 개인정보와 영상 데이터를 즉시 삭제합니다.',
    s4Title: '4. 정보의 공유',
    s4Desc: '서비스는 다음의 경우를 제외하고 개인정보를 제3자에게 공유하지 않습니다:',
    s4Items: [
      '결제 처리를 위한 Paddle 전달',
      '서비스 인프라 운영을 위한 클라우드 서비스 제공자 (Supabase, Vercel, Fly.io)',
      '법적 요구사항에 따른 경우',
    ],
    s5Title: '5. 사용자의 권리',
    s5Desc: '사용자는 언제든지 다음을 요청할 수 있습니다:',
    s5Items: [
      '개인정보 열람 및 수정',
      '계정 및 데이터 삭제',
      '데이터 이동(포터빌리티)',
    ],
    s6Title: '6. 쿠키',
    s6Desc: '서비스는 로그인 세션 유지를 위한 필수 쿠키만 사용합니다. 분석 또는 광고 목적의 쿠키는 사용하지 않습니다.',
    s7Title: '7. 보안',
    s7Desc: '모든 데이터는 전송 중 암호화(TLS)되며, 저장 시에도 암호화됩니다. 정기적인 보안 점검을 수행합니다.',
    s8Title: '8. 문의',
    s8Desc: '개인정보 관련 문의는 이메일로 연락해 주세요.',
    backLink: '← 요금제로 돌아가기',
  },
  en: {
    title: 'Privacy Policy',
    lastUpdated: 'Last updated: March 17, 2026',
    s1Title: '1. Information We Collect',
    s1Desc: 'The service collects the following information:',
    s1Items: [
      { bold: 'Account information:', text: 'Name, email, and profile picture provided through Google sign-in' },
      { bold: 'Video data:', text: 'Video clips recorded and uploaded by users' },
      { bold: 'Payment information:', text: 'Processed through Paddle; we do not directly store payment card information' },
      { bold: 'Usage data:', text: 'Service usage records and access logs' },
    ],
    s2Title: '2. How We Use Your Information',
    s2Items: [
      'Providing the service and processing video edits',
      'Account management and customer support',
      'Service improvement and analytics',
      'Payment processing and subscription management',
    ],
    s3Title: '3. Data Retention and Deletion',
    s3Desc: 'Uploaded videos are automatically deleted from our servers within 30 days after editing is complete. Upon account deletion request, all personal information and video data will be immediately deleted.',
    s4Title: '4. Information Sharing',
    s4Desc: 'We do not share personal information with third parties except in the following cases:',
    s4Items: [
      'Paddle for payment processing',
      'Cloud service providers for infrastructure (Supabase, Vercel, Fly.io)',
      'When required by law',
    ],
    s5Title: '5. Your Rights',
    s5Desc: 'You may request the following at any time:',
    s5Items: [
      'Access and correction of personal information',
      'Account and data deletion',
      'Data portability',
    ],
    s6Title: '6. Cookies',
    s6Desc: 'We only use essential cookies to maintain login sessions. We do not use cookies for analytics or advertising purposes.',
    s7Title: '7. Security',
    s7Desc: 'All data is encrypted in transit (TLS) and at rest. We conduct regular security audits.',
    s8Title: '8. Contact',
    s8Desc: 'For privacy-related inquiries, please contact us by email.',
    backLink: '← Back to Pricing',
  },
} as const;

export default function PrivacyPage() {
  const { lang } = useLang();
  const l = t[lang];

  return (
    <div className="min-h-screen bg-black text-white">
      <div className="max-w-2xl mx-auto px-4 py-12">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-bold">{l.title}</h1>
          <LangToggle />
        </div>
        <div className="prose prose-invert prose-sm max-w-none space-y-4 text-gray-300 leading-relaxed">
          <p><strong>{l.lastUpdated}</strong></p>

          <h2 className="text-lg font-semibold text-white mt-6">{l.s1Title}</h2>
          <p>{l.s1Desc}</p>
          <ul className="list-disc pl-5 space-y-1">
            {l.s1Items.map((item) => (
              <li key={item.bold}><strong>{item.bold}</strong> {item.text}</li>
            ))}
          </ul>

          <h2 className="text-lg font-semibold text-white mt-6">{l.s2Title}</h2>
          <ul className="list-disc pl-5 space-y-1">
            {l.s2Items.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>

          <h2 className="text-lg font-semibold text-white mt-6">{l.s3Title}</h2>
          <p>{l.s3Desc}</p>

          <h2 className="text-lg font-semibold text-white mt-6">{l.s4Title}</h2>
          <p>{l.s4Desc}</p>
          <ul className="list-disc pl-5 space-y-1">
            {l.s4Items.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>

          <h2 className="text-lg font-semibold text-white mt-6">{l.s5Title}</h2>
          <p>{l.s5Desc}</p>
          <ul className="list-disc pl-5 space-y-1">
            {l.s5Items.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>

          <h2 className="text-lg font-semibold text-white mt-6">{l.s6Title}</h2>
          <p>{l.s6Desc}</p>

          <h2 className="text-lg font-semibold text-white mt-6">{l.s7Title}</h2>
          <p>{l.s7Desc}</p>

          <h2 className="text-lg font-semibold text-white mt-6">{l.s8Title}</h2>
          <p>{l.s8Desc}</p>
        </div>

        <div className="mt-8">
          <a href="/pricing" className="text-purple-400 hover:text-purple-300 text-sm">{l.backLink}</a>
        </div>
      </div>
    </div>
  );
}
