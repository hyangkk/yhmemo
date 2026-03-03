/**
 * Supabase Edge Function: telegram-webhook
 *
 * 텔레그램 Webhook으로 들어오는 메시지를 실시간 처리합니다.
 * - 명령어(/주제, /명령어, /주기, /건너뛰기 등) 즉시 응답
 * - 일반 텍스트 → 현재 활성 주제에 답변 저장
 * - AI가 필요한 명령어(/대본)는 GitHub Actions 트리거
 */

import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

// ─── 환경변수 ───
const TELEGRAM_BOT_TOKEN = Deno.env.get("TELEGRAM_BOT_TOKEN") ?? "";
const TELEGRAM_CHAT_ID = Deno.env.get("TELEGRAM_CHAT_ID") ?? "";
const SUPABASE_URL = Deno.env.get("SUPABASE_URL") ?? "";
const SUPABASE_SERVICE_ROLE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
const GITHUB_TOKEN = Deno.env.get("GITHUB_TOKEN") ?? "";
const WEBHOOK_SECRET = Deno.env.get("WEBHOOK_SECRET") ?? "";

const sb = createClient(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY);

// ─── 텔레그램 헬퍼 ───
async function tgSend(text: string, replyTo?: number): Promise<number | null> {
  const payload: Record<string, unknown> = {
    chat_id: TELEGRAM_CHAT_ID,
    text,
    parse_mode: "HTML",
  };
  if (replyTo) payload.reply_to_message_id = replyTo;

  try {
    const resp = await fetch(
      `https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }
    );
    const data = await resp.json();
    return data.ok ? data.result.message_id : null;
  } catch {
    return null;
  }
}

// ─── DB 헬퍼 ───
async function getSettings(): Promise<Record<string, unknown>> {
  const { data } = await sb
    .from("agent_settings")
    .select("*")
    .eq("id", 1)
    .single();
  return data ?? {};
}

async function getActiveTopics() {
  const { data } = await sb
    .from("interview_topics")
    .select("*")
    .eq("enabled", true)
    .order("id", { ascending: true });
  return data ?? [];
}

async function getPendingQuestion() {
  const { data: lastQ } = await sb
    .from("interview_messages")
    .select("*")
    .eq("role", "agent")
    .order("created_at", { ascending: false })
    .limit(1);

  if (!lastQ || lastQ.length === 0) return null;
  const q = lastQ[0];

  const { data: replies } = await sb
    .from("interview_messages")
    .select("id")
    .eq("role", "user")
    .eq("topic_id", q.topic_id)
    .gt("created_at", q.created_at)
    .limit(1);

  return replies && replies.length > 0 ? null : q;
}

// ─── 주기 헬퍼 ───
function getIntervalMinutes(settings: Record<string, unknown>): number {
  const mins = settings.interview_interval_minutes as number | null;
  if (mins && mins > 0) return mins;
  return ((settings.interview_interval_hours as number) ?? 3) * 60;
}

function formatInterval(minutes: number): string {
  if (minutes < 60) return `${minutes}분`;
  const hours = minutes / 60;
  if (hours === Math.floor(hours)) return `${Math.floor(hours)}시간`;
  return `${Math.floor(hours)}시간 ${minutes % 60}분`;
}

function parseInterval(text: string): number | null {
  text = text.trim();

  if (/^\d+$/.test(text)) return parseInt(text, 10);

  let total = 0;
  const hMatch = text.match(/(\d+(?:\.\d+)?)\s*시간/);
  const mMatch = text.match(/(\d+)\s*분/);

  if (hMatch) total += Math.floor(parseFloat(hMatch[1]) * 60);
  if (mMatch) total += parseInt(mMatch[1], 10);

  return total > 0 ? total : null;
}

// ─── GitHub Actions 트리거 ───
async function triggerWorkflow(workflowFile: string): Promise<boolean> {
  if (!GITHUB_TOKEN) return false;
  try {
    const resp = await fetch(
      `https://api.github.com/repos/hyangkk/yhmemo/actions/workflows/${workflowFile}/dispatches`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${GITHUB_TOKEN}`,
          Accept: "application/vnd.github.v3+json",
        },
        body: JSON.stringify({ ref: "main" }),
      }
    );
    return resp.ok;
  } catch {
    return false;
  }
}

// ─── 명령어 핸들러 ───
async function handleCommand(
  text: string,
  settings: Record<string, unknown>
): Promise<boolean> {
  const cmd = text.trim().split(/\s+/)[0].toLowerCase();

  // /명령어
  if (["/명령어", "/help", "/commands"].includes(cmd)) {
    await tgSend(
      "<b>전체 명령어 목록</b>\n" +
        "\n" +
        "<b>인터뷰 에이전트</b>\n" +
        "  /주제 — 인터뷰 주제 목록\n" +
        "  /인터뷰 — 에이전트 상태 확인\n" +
        "  /주기 — 질문 주기 확인/변경\n" +
        "  /대본 — 유튜브 대본 생성\n" +
        "  /대본 주제명 — 특정 주제 대본 생성\n" +
        "  /건너뛰기 — 현재 질문 건너뛰기\n" +
        "\n" +
        "<b>뉴스 에이전트</b>\n" +
        "  자동 실행 (설정 주기마다)\n" +
        "\n" +
        "<b>K-Startup 에이전트</b>\n" +
        "  자동 실행 (설정 주기마다)\n" +
        "\n" +
        "<b>공통</b>\n" +
        "  /명령어 — 이 도움말 표시\n" +
        "\n" +
        "<i>일반 텍스트를 보내면 현재 진행 중인\n" +
        "인터뷰 주제에 답변으로 기록됩니다.</i>"
    );
    return true;
  }

  // /주제
  if (["/주제", "/topics"].includes(cmd)) {
    const topics = await getActiveTopics();
    if (topics.length === 0) {
      await tgSend(
        "활성화된 인터뷰 주제가 없습니다.\n설정 페이지에서 주제를 추가해주세요."
      );
    } else {
      const lines = ["<b>인터뷰 주제 목록</b>\n"];
      for (const t of topics) {
        const cnt = t.total_questions ?? 0;
        lines.push(`  ${t.name}  (질문 ${cnt}개)`);
      }
      await tgSend(lines.join("\n"));
    }
    return true;
  }

  // /인터뷰
  if (["/인터뷰", "/status"].includes(cmd)) {
    const pending = await getPendingQuestion();
    const interval = getIntervalMinutes(settings);
    const lastAt = settings.interview_last_question_at ?? "없음";
    const parts = [
      "<b>인터뷰 에이전트 상태</b>\n",
      `실행 주기: ${formatInterval(interval)}마다`,
      `마지막 질문: ${lastAt}`,
      `미답변 질문: ${pending ? "있음" : "없음"}`,
    ];
    const topics = await getActiveTopics();
    if (topics.length > 0) {
      parts.push(
        `\n활성 주제: ${topics.map((t: { name: string }) => t.name).join(", ")}`
      );
    }
    await tgSend(parts.join("\n"));
    return true;
  }

  // /주기
  if (["/주기", "/interval"].includes(cmd)) {
    const cmdParts = text.trim().split(/\s+(.+)/);
    if (cmdParts.length < 2 || !cmdParts[1]) {
      const current = getIntervalMinutes(settings);
      await tgSend(
        `<b>현재 질문 주기:</b> ${formatInterval(current)}\n\n` +
          "<b>변경 예시:</b>\n" +
          "  /주기 45분\n" +
          "  /주기 1시간 30분\n" +
          "  /주기 2시간\n" +
          "  /주기 90  (숫자만 쓰면 분 단위)"
      );
      return true;
    }

    const raw = cmdParts[1].trim();
    const minutes = parseInterval(raw);
    if (minutes === null || minutes < 15) {
      await tgSend(
        "주기를 인식할 수 없거나 15분 미만입니다.\n예: /주기 45분, /주기 2시간, /주기 1시간 30분"
      );
      return true;
    }

    await sb
      .from("agent_settings")
      .update({ interview_interval_minutes: minutes })
      .eq("id", 1);
    await tgSend(
      `질문 주기가 <b>${formatInterval(minutes)}</b>(으)로 변경되었습니다.`
    );
    return true;
  }

  // /대본 — AI 필요 → GitHub Actions 트리거
  if (["/대본", "/draft"].includes(cmd)) {
    await tgSend("대본 생성을 요청했습니다. 잠시 후 결과가 전송됩니다...");
    // 대본 생성은 Claude API가 필요하므로 GitHub Actions로 위임
    const triggered = await triggerWorkflow("interview-draft.yml");
    if (!triggered) {
      await tgSend("대본 생성 워크플로우 트리거에 실패했습니다. GitHub Actions에서 수동 실행해주세요.");
    }
    return true;
  }

  // /건너뛰기
  if (["/건너뛰기", "/skip"].includes(cmd)) {
    const pending = await getPendingQuestion();
    if (pending) {
      await sb.from("interview_messages").insert({
        topic_id: pending.topic_id,
        role: "user",
        content: "(건너뛰기)",
      });
      await tgSend("현재 질문을 건너뛰었습니다. 다음 질문을 기다려주세요.");
    } else {
      await tgSend("건너뛸 질문이 없습니다.");
    }
    return true;
  }

  return false;
}

// ─── 답변 저장 ───
async function saveAnswer(text: string, messageId?: number): Promise<void> {
  const pending = await getPendingQuestion();
  let topicId: number | null = null;

  if (pending) {
    topicId = pending.topic_id;
  } else {
    const topics = await getActiveTopics();
    if (topics.length > 0) {
      const recent = topics.reduce(
        (max: { total_questions: number }, t: { total_questions: number }) =>
          (t.total_questions ?? 0) > (max.total_questions ?? 0) ? t : max,
        topics[0]
      );
      topicId = recent.id;
    }
  }

  if (topicId) {
    await sb.from("interview_messages").insert({
      topic_id: topicId,
      role: "user",
      content: text,
      telegram_message_id: messageId,
    });
    await tgSend("답변이 기록되었습니다!");
  }
}

// ─── 메인 핸들러 ───
Deno.serve(async (req: Request) => {
  // POST만 허용
  if (req.method !== "POST") {
    return new Response("OK", { status: 200 });
  }

  // 시크릿 토큰 검증 (선택사항)
  if (WEBHOOK_SECRET) {
    const secret = req.headers.get("x-telegram-bot-api-secret-token");
    if (secret !== WEBHOOK_SECRET) {
      return new Response("Unauthorized", { status: 401 });
    }
  }

  try {
    const update = await req.json();
    const msg = update?.message;
    if (!msg) return new Response("OK", { status: 200 });

    // 올바른 채팅인지 확인
    const chatId = String(msg.chat?.id ?? "");
    if (TELEGRAM_CHAT_ID && chatId !== TELEGRAM_CHAT_ID) {
      return new Response("OK", { status: 200 });
    }

    const text = (msg.text ?? "").trim();
    if (!text) return new Response("OK", { status: 200 });

    // update_id 갱신 (Python 에이전트와 동기화)
    const updateId = update.update_id;
    const settings = await getSettings();
    const lastUid = (settings.interview_last_update_id as number) ?? 0;
    if (updateId > lastUid) {
      await sb
        .from("agent_settings")
        .update({ interview_last_update_id: updateId })
        .eq("id", 1);
    }

    // 명령어 처리
    if (text.startsWith("/")) {
      await handleCommand(text, settings);
      return new Response("OK", { status: 200 });
    }

    // 일반 텍스트 → 답변 저장
    await saveAnswer(text, msg.message_id);
  } catch (e) {
    console.error("Webhook error:", e);
  }

  return new Response("OK", { status: 200 });
});
