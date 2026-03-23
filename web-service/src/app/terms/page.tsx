export default function TermsPage() {
  return (
    <div className="min-h-screen bg-black text-white">
      <div className="max-w-2xl mx-auto px-4 py-12">
        <h1 className="text-2xl font-bold mb-6">이용약관 (Terms of Service)</h1>
        <div className="prose prose-invert prose-sm max-w-none space-y-4 text-gray-300 leading-relaxed">
          <p><strong>최종 수정일:</strong> 2026년 3월 17일</p>

          <h2 className="text-lg font-semibold text-white mt-6">1. 서비스 개요</h2>
          <p>멀티캠 스튜디오(이하 &quot;서비스&quot;)는 여러 카메라로 촬영한 영상을 AI가 자동으로 편집해주는 웹 기반 서비스입니다.</p>

          <h2 className="text-lg font-semibold text-white mt-6">2. 이용 자격</h2>
          <p>서비스를 이용하려면 만 14세 이상이어야 하며, Google 계정을 통해 가입할 수 있습니다.</p>

          <h2 className="text-lg font-semibold text-white mt-6">3. 계정</h2>
          <p>사용자는 자신의 계정 정보를 안전하게 관리할 책임이 있습니다. 계정의 무단 사용이 의심되는 경우 즉시 알려주세요.</p>

          <h2 className="text-lg font-semibold text-white mt-6">4. 요금제 및 결제</h2>
          <p>서비스는 무료(Free) 요금제와 유료(Plus, $3/월) 요금제를 제공합니다. 유료 구독은 Paddle을 통해 처리되며, 매월 자동 갱신됩니다.</p>

          <h2 className="text-lg font-semibold text-white mt-6">5. 콘텐츠 소유권</h2>
          <p>사용자가 업로드한 영상 및 편집 결과물의 소유권은 사용자에게 있습니다. 서비스는 편집 처리 목적으로만 콘텐츠에 접근합니다.</p>

          <h2 className="text-lg font-semibold text-white mt-6">6. 금지 행위</h2>
          <ul className="list-disc pl-5 space-y-1">
            <li>불법 콘텐츠 업로드</li>
            <li>타인의 권리를 침해하는 콘텐츠 업로드</li>
            <li>서비스의 정상적인 운영을 방해하는 행위</li>
            <li>자동화된 방법으로 서비스를 악용하는 행위</li>
          </ul>

          <h2 className="text-lg font-semibold text-white mt-6">7. 서비스 변경 및 중단</h2>
          <p>서비스는 사전 통지 후 기능을 변경하거나 중단할 수 있습니다. 유료 구독 중 서비스가 중단되는 경우 잔여 기간에 대해 환불을 제공합니다.</p>

          <h2 className="text-lg font-semibold text-white mt-6">8. 책임 제한</h2>
          <p>서비스는 &quot;있는 그대로(as-is)&quot; 제공되며, 편집 결과의 품질이나 특정 목적에의 적합성을 보증하지 않습니다.</p>

          <h2 className="text-lg font-semibold text-white mt-6">9. 문의</h2>
          <p>서비스 관련 문의는 이메일로 연락해 주세요.</p>
        </div>

        <div className="mt-8">
          <a href="/pricing" className="text-purple-400 hover:text-purple-300 text-sm">← 요금제로 돌아가기</a>
        </div>
      </div>
    </div>
  );
}
