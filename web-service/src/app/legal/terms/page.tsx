import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'SupaCam — Terms of Service',
  description: 'SupaCam 이용약관. 서비스 이용 조건, 구독, 환불 정책을 확인하세요.',
  openGraph: {
    title: 'SupaCam — Terms of Service',
    description: 'SupaCam 이용약관 및 개인정보처리방침.',
    type: 'website',
    siteName: 'SupaCam',
  },
};

export default function TermsPage() {
  return (
    <main className="min-h-screen bg-gray-950 text-white">
      <div className="max-w-3xl mx-auto px-4 py-16">
        <h1 className="text-3xl font-bold mb-8">Terms of Service</h1>
        <p className="text-sm text-gray-400 mb-8">Last updated: March 22, 2026</p>

        <div className="prose prose-invert prose-sm max-w-none space-y-6 text-gray-300">
          <section>
            <h2 className="text-xl font-semibold text-white">1. Service Overview</h2>
            <p>SupaCam is an AI-powered multi-camera video editing service. By using our service, you agree to these terms.</p>
          </section>

          <section>
            <h2 className="text-xl font-semibold text-white">2. Account</h2>
            <p>You must provide accurate information when creating an account. You are responsible for maintaining the security of your account credentials.</p>
          </section>

          <section>
            <h2 className="text-xl font-semibold text-white">3. Subscription & Payments</h2>
            <p>SupaCam offers Free and Plus plans. Plus subscriptions are billed monthly at $9/month through our payment processor, Paddle. You may cancel your subscription at any time. Cancellation takes effect at the end of the current billing period.</p>
          </section>

          <section>
            <h2 className="text-xl font-semibold text-white">4. Refund Policy</h2>
            <p>We offer a full refund within 7 days of your first subscription payment if you are not satisfied with our service. After this period, no refunds will be issued for partial billing periods. To request a refund, contact us at ai.agent.yh@gmail.com.</p>
          </section>

          <section>
            <h2 className="text-xl font-semibold text-white">5. User Content</h2>
            <p>You retain ownership of all videos and content you upload to SupaCam. We do not claim any rights to your content. Uploaded content is processed solely for the purpose of providing our editing service.</p>
          </section>

          <section>
            <h2 className="text-xl font-semibold text-white">6. Acceptable Use</h2>
            <p>You agree not to upload illegal, harmful, or infringing content. We reserve the right to terminate accounts that violate these terms.</p>
          </section>

          <section>
            <h2 className="text-xl font-semibold text-white">7. Privacy Policy</h2>
            <p>We collect minimal personal data necessary to provide our service: email address, name, and Google account information for authentication. We do not sell your personal data to third parties. Video content is stored securely and deleted upon account termination. For payment processing, your billing information is handled by Paddle and is not stored on our servers.</p>
          </section>

          <section>
            <h2 className="text-xl font-semibold text-white">8. Service Availability</h2>
            <p>We strive to maintain 99.9% uptime but do not guarantee uninterrupted service. We are not liable for any damages resulting from service interruptions.</p>
          </section>

          <section>
            <h2 className="text-xl font-semibold text-white">9. Limitation of Liability</h2>
            <p>SupaCam is provided &quot;as is&quot; without warranties. Our liability is limited to the amount you paid for the service in the 12 months preceding any claim.</p>
          </section>

          <section>
            <h2 className="text-xl font-semibold text-white">10. Changes</h2>
            <p>We may update these terms from time to time. Continued use of the service constitutes acceptance of the updated terms.</p>
          </section>

          <section>
            <h2 className="text-xl font-semibold text-white">11. Contact</h2>
            <p>For questions about these terms, contact us at ai.agent.yh@gmail.com.</p>
          </section>
        </div>
      </div>
    </main>
  );
}
