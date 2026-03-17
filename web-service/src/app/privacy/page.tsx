export default function PrivacyPage() {
  return (
    <div className="min-h-screen bg-black text-white">
      <div className="max-w-2xl mx-auto px-4 py-12">
        <h1 className="text-2xl font-bold mb-6">개인정보처리방침 (Privacy Policy)</h1>
        <div className="prose prose-invert prose-sm max-w-none space-y-4 text-gray-300 leading-relaxed">
          <p><strong>최종 수정일:</strong> 2026년 3월 17일</p>

          <h2 className="text-lg font-semibold text-white mt-6">1. 수집하는 정보</h2>
          <p>서비스는 다음 정보를 수집합니다:</p>
          <ul className="list-disc pl-5 space-y-1">
            <li><strong>계정 정보:</strong> Google 로그인 시 제공되는 이름, 이메일, 프로필 사진</li>
            <li><strong>영상 데이터:</strong> 사용자가 촬영하여 업로드한 영상 클립</li>
            <li><strong>결제 정보:</strong> Paddle을 통해 처리되며, 서비스는 결제 카드 정보를 직접 저장하지 않습니다</li>
            <li><strong>사용 데이터:</strong> 서비스 이용 기록, 접속 로그</li>
          </ul>

          <h2 className="text-lg font-semibold text-white mt-6">2. 정보의 이용 목적</h2>
          <ul className="list-disc pl-5 space-y-1">
            <li>서비스 제공 및 영상 편집 처리</li>
            <li>계정 관리 및 고객 지원</li>
            <li>서비스 개선 및 분석</li>
            <li>결제 처리 및 구독 관리</li>
          </ul>

          <h2 className="text-lg font-semibold text-white mt-6">3. 정보의 보관 및 삭제</h2>
          <p>업로드된 영상은 편집 처리 후 30일 이내에 서버에서 자동 삭제됩니다. 계정 삭제 요청 시 모든 개인정보와 영상 데이터를 즉시 삭제합니다.</p>

          <h2 className="text-lg font-semibold text-white mt-6">4. 정보의 공유</h2>
          <p>서비스는 다음의 경우를 제외하고 개인정보를 제3자에게 공유하지 않습니다:</p>
          <ul className="list-disc pl-5 space-y-1">
            <li>결제 처리를 위한 Paddle 전달</li>
            <li>서비스 인프라 운영을 위한 클라우드 서비스 제공자 (Supabase, Vercel, Fly.io)</li>
            <li>법적 요구사항에 따른 경우</li>
          </ul>

          <h2 className="text-lg font-semibold text-white mt-6">5. 사용자의 권리</h2>
          <p>사용자는 언제든지 다음을 요청할 수 있습니다:</p>
          <ul className="list-disc pl-5 space-y-1">
            <li>개인정보 열람 및 수정</li>
            <li>계정 및 데이터 삭제</li>
            <li>데이터 이동(포터빌리티)</li>
          </ul>

          <h2 className="text-lg font-semibold text-white mt-6">6. 쿠키</h2>
          <p>서비스는 로그인 세션 유지를 위한 필수 쿠키만 사용합니다. 분석 또는 광고 목적의 쿠키는 사용하지 않습니다.</p>

          <h2 className="text-lg font-semibold text-white mt-6">7. 보안</h2>
          <p>모든 데이터는 전송 중 암호화(TLS)되며, 저장 시에도 암호화됩니다. 정기적인 보안 점검을 수행합니다.</p>

          <h2 className="text-lg font-semibold text-white mt-6">8. 문의</h2>
          <p>개인정보 관련 문의는 이메일로 연락해 주세요.</p>
        </div>

        <div className="mt-8">
          <a href="/pricing" className="text-purple-400 hover:text-purple-300 text-sm">← 요금제로 돌아가기</a>
        </div>
      </div>
    </div>
  );
}
