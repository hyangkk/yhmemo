// 슬랙 service-log 채널에 알림 전송
const SERVICE_LOG_CHANNEL = 'C0ANA717YKE';

export async function notifyServiceLog(message: string) {
  const token = process.env.SLACK_BOT_TOKEN;
  if (!token) return;

  try {
    await fetch('https://slack.com/api/chat.postMessage', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        channel: SERVICE_LOG_CHANNEL,
        text: message,
      }),
    });
  } catch {
    // 슬랙 알림 실패는 서비스에 영향 주지 않도록 무시
  }
}
