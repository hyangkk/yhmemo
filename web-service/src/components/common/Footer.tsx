'use client';

import { useLang } from '@/lib/i18n';

export function Footer() {
  const { lang } = useLang();

  const t = {
    product: lang === 'ko' ? '서비스' : 'Product',
    pricing: lang === 'ko' ? '요금제' : 'Pricing',
    legal: lang === 'ko' ? '법률' : 'Legal',
    terms: lang === 'ko' ? '이용약관' : 'Terms of Service',
    privacy: lang === 'ko' ? '개인정보처리방침' : 'Privacy Policy',
    refund: lang === 'ko' ? '환불정책' : 'Refund Policy',
    support: lang === 'ko' ? '지원' : 'Support',
    contact: lang === 'ko' ? '문의' : 'Contact',
    desc: lang === 'ko'
      ? 'AI 기반 멀티카메라 자동 편집 서비스'
      : 'AI-powered multi-camera auto editing',
    rights: `© ${new Date().getFullYear()} SupaCam. All rights reserved.`,
    paddle: lang === 'ko' ? '결제: Paddle' : 'Payments by Paddle',
  };

  return (
    <footer className="bg-gray-950 border-t border-gray-800 text-gray-400 text-sm">
      <div className="max-w-5xl mx-auto px-6 py-12">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-8 mb-8">
          {/* 브랜드 */}
          <div className="col-span-2 md:col-span-1">
            <h3 className="text-white font-bold text-lg mb-2">SupaCam</h3>
            <p className="text-xs text-gray-500 leading-relaxed">{t.desc}</p>
          </div>

          {/* 서비스 */}
          <div>
            <h4 className="text-gray-300 font-semibold text-xs uppercase tracking-wider mb-3">{t.product}</h4>
            <ul className="space-y-2">
              <li><a href="/pricing" className="hover:text-white transition">{t.pricing}</a></li>
            </ul>
          </div>

          {/* 법률 */}
          <div>
            <h4 className="text-gray-300 font-semibold text-xs uppercase tracking-wider mb-3">{t.legal}</h4>
            <ul className="space-y-2">
              <li><a href="/legal/terms" className="hover:text-white transition">{t.terms}</a></li>
              <li><a href="/privacy" className="hover:text-white transition">{t.privacy}</a></li>
              <li><a href="/refund" className="hover:text-white transition">{t.refund}</a></li>
            </ul>
          </div>

          {/* 지원 */}
          <div>
            <h4 className="text-gray-300 font-semibold text-xs uppercase tracking-wider mb-3">{t.support}</h4>
            <ul className="space-y-2">
              <li><a href="mailto:ai.agent.yh@gmail.com" className="hover:text-white transition">{t.contact}</a></li>
              <li><span className="text-xs text-gray-600">ai.agent.yh@gmail.com</span></li>
            </ul>
          </div>
        </div>

        <div className="border-t border-gray-800 pt-6 flex flex-col sm:flex-row items-center justify-between gap-2">
          <p className="text-xs text-gray-600">{t.rights}</p>
          <p className="text-xs text-gray-600">{t.paddle}</p>
        </div>
      </div>
    </footer>
  );
}
