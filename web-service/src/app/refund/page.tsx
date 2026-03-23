'use client';

import { useLang, LangToggle } from '@/lib/i18n';

const t = {
  ko: {
    title: '환불정책 (Refund Policy)',
    lastUpdated: '최종 수정일: 2026년 3월 17일',
    s1Title: '1. 구독 취소',
    s1Desc: 'Plus 구독은 언제든지 취소할 수 있습니다. 취소 후에도 현재 결제 기간이 끝날 때까지 Plus 기능을 계속 이용할 수 있습니다.',
    s2Title: '2. 환불 조건',
    s2Items: [
      { bold: '구독 시작 후 7일 이내:', text: '서비스를 이용하지 않은 경우 전액 환불이 가능합니다.' },
      { bold: '서비스 장애:', text: '서비스 장애로 인해 정상적으로 이용하지 못한 기간에 대해 일할 계산으로 환불합니다.' },
      { bold: '중복 결제:', text: '중복 결제가 확인된 경우 즉시 환불합니다.' },
    ],
    s3Title: '3. 환불 불가 사유',
    s3Items: [
      '구독 시작 후 7일이 경과하고 서비스를 이미 이용한 경우',
      '이용약관 위반으로 계정이 정지된 경우',
    ],
    s4Title: '4. 환불 절차',
    s4Desc: '환불을 요청하려면 이메일로 연락해 주세요. 결제는 Paddle을 통해 처리되며, 환불 승인 후 5~10 영업일 이내에 원래 결제 수단으로 환불됩니다.',
    s5Title: '5. 무료 체험',
    s5Desc: 'Free 요금제는 무료이므로 별도의 환불 절차가 없습니다.',
    s6Title: '6. 문의',
    s6Desc: '환불 관련 문의는 이메일로 연락해 주세요. 영업일 기준 1~2일 이내에 답변드립니다.',
    backLink: '← 요금제로 돌아가기',
  },
  en: {
    title: 'Refund Policy',
    lastUpdated: 'Last updated: March 17, 2026',
    s1Title: '1. Cancellation',
    s1Desc: 'You can cancel your Plus subscription at any time. After cancellation, you can continue using Plus features until the end of your current billing period.',
    s2Title: '2. Refund Eligibility',
    s2Items: [
      { bold: 'Within 7 days of subscription:', text: 'Full refund is available if the service has not been used.' },
      { bold: 'Service outage:', text: 'Pro-rated refund for periods when the service was unavailable due to outages.' },
      { bold: 'Duplicate charges:', text: 'Immediate refund upon confirmation of duplicate payment.' },
    ],
    s3Title: '3. Non-Refundable Cases',
    s3Items: [
      'More than 7 days after subscription start and the service has been used',
      'Account suspended due to terms of service violation',
    ],
    s4Title: '4. Refund Process',
    s4Desc: 'To request a refund, please contact us by email. Payments are processed through Paddle, and refunds will be issued to the original payment method within 5-10 business days after approval.',
    s5Title: '5. Free Plan',
    s5Desc: 'The Free plan is free of charge, so no refund process applies.',
    s6Title: '6. Contact',
    s6Desc: 'For refund inquiries, please contact us by email. We will respond within 1-2 business days.',
    backLink: '← Back to Pricing',
  },
} as const;

export default function RefundPage() {
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

          <h2 className="text-lg font-semibold text-white mt-6">{l.s2Title}</h2>
          <ul className="list-disc pl-5 space-y-1">
            {l.s2Items.map((item) => (
              <li key={item.bold}><strong>{item.bold}</strong> {item.text}</li>
            ))}
          </ul>

          <h2 className="text-lg font-semibold text-white mt-6">{l.s3Title}</h2>
          <ul className="list-disc pl-5 space-y-1">
            {l.s3Items.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>

          <h2 className="text-lg font-semibold text-white mt-6">{l.s4Title}</h2>
          <p>{l.s4Desc}</p>

          <h2 className="text-lg font-semibold text-white mt-6">{l.s5Title}</h2>
          <p>{l.s5Desc}</p>

          <h2 className="text-lg font-semibold text-white mt-6">{l.s6Title}</h2>
          <p>{l.s6Desc}</p>
        </div>

        <div className="mt-8">
          <a href="/pricing" className="text-purple-400 hover:text-purple-300 text-sm">{l.backLink}</a>
        </div>
      </div>
    </div>
  );
}
