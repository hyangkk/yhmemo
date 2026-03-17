export default function RefundPage() {
  return (
    <div className="min-h-screen bg-black text-white">
      <div className="max-w-2xl mx-auto px-4 py-12">
        <h1 className="text-2xl font-bold mb-6">환불정책 (Refund Policy)</h1>
        <div className="prose prose-invert prose-sm max-w-none space-y-4 text-gray-300 leading-relaxed">
          <p><strong>최종 수정일:</strong> 2026년 3월 17일</p>

          <h2 className="text-lg font-semibold text-white mt-6">1. 구독 취소</h2>
          <p>Plus 구독은 언제든지 취소할 수 있습니다. 취소 후에도 현재 결제 기간이 끝날 때까지 Plus 기능을 계속 이용할 수 있습니다.</p>

          <h2 className="text-lg font-semibold text-white mt-6">2. 환불 조건</h2>
          <ul className="list-disc pl-5 space-y-1">
            <li><strong>구독 시작 후 7일 이내:</strong> 서비스를 이용하지 않은 경우 전액 환불이 가능합니다.</li>
            <li><strong>서비스 장애:</strong> 서비스 장애로 인해 정상적으로 이용하지 못한 기간에 대해 일할 계산으로 환불합니다.</li>
            <li><strong>중복 결제:</strong> 중복 결제가 확인된 경우 즉시 환불합니다.</li>
          </ul>

          <h2 className="text-lg font-semibold text-white mt-6">3. 환불 불가 사유</h2>
          <ul className="list-disc pl-5 space-y-1">
            <li>구독 시작 후 7일이 경과하고 서비스를 이미 이용한 경우</li>
            <li>이용약관 위반으로 계정이 정지된 경우</li>
          </ul>

          <h2 className="text-lg font-semibold text-white mt-6">4. 환불 절차</h2>
          <p>환불을 요청하려면 이메일로 연락해 주세요. 결제는 Paddle을 통해 처리되며, 환불 승인 후 5~10 영업일 이내에 원래 결제 수단으로 환불됩니다.</p>

          <h2 className="text-lg font-semibold text-white mt-6">5. 무료 체험</h2>
          <p>Free 요금제는 무료이므로 별도의 환불 절차가 없습니다.</p>

          <h2 className="text-lg font-semibold text-white mt-6">6. 문의</h2>
          <p>환불 관련 문의는 이메일로 연락해 주세요. 영업일 기준 1~2일 이내에 답변드립니다.</p>
        </div>

        <div className="mt-8">
          <a href="/pricing" className="text-purple-400 hover:text-purple-300 text-sm">← 요금제로 돌아가기</a>
        </div>
      </div>
    </div>
  );
}
