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
async function triggerWorkflow(
  workflowFile: string,
  inputs?: Record<string, string>
): Promise<boolean> {
  if (!GITHUB_TOKEN) return false;
  try {
    const body: Record<string, unknown> = { ref: "main" };
    if (inputs) body.inputs = inputs;
    const resp = await fetch(
      `https://api.github.com/repos/hyangkk/yhmemo/actions/workflows/${workflowFile}/dispatches`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${GITHUB_TOKEN}`,
          Accept: "application/vnd.github.v3+json",
        },
        body: JSON.stringify(body),
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
  settings: Record<string, unknown>,
  msgId: number = 0
): Promise<boolean> {
  const cmd = text.trim().split(/\s+/)[0].toLowerCase();

  // /명령어
  if (["/명령어", "/help", "/commands"].includes(cmd)) {
    await tgSend(
      "<b>전체 명령어 목록</b>\n" +
        "\n" +
        "<b>🏛️ 이사회 에이전트</b>\n" +
        "  /생각일기 — 최근 N시간 이사회 분석\n" +
        "  /생각일기 6시간 — 6시간 이사회 분석\n" +
        "  /이사회 — /생각일기와 동일\n" +
        "  /생각분석 — 최근 1개월 종합 분석\n" +
        "  /생각분석 24개월 — 24개월 종합 분석\n" +
        "\n" +
        "<b>🎙️ 인터뷰 에이전트</b>\n" +
        "  /주제 — 인터뷰 주제 목록\n" +
        "  /인터뷰 — 에이전트 상태 확인\n" +
        "  /주기 — 질문 주기 확인/변경\n" +
        "  /대본 — 유튜브 대본 생성\n" +
        "  /대본 주제명 — 특정 주제 대본 생성\n" +
        "  /질문줘 — 지금 바로 질문 받기\n" +
        "  /건너뛰기 — 현재 질문 건너뛰기\n" +
        "\n" +
        "<b>공통</b>\n" +
        "  /명령어 — 이 도움말 표시\n" +
        "\n" +
        "<i>일반 텍스트를 보내면 현재 진행 중인\n" +
        "인터뷰 주제에 답변으로 기록됩니다.</i>"
    );
    return true;
  }

  // /생각분석 — 장기 생각일기 종합 분석
  if (cmd === "/생각분석" || cmd === "/analysis") {
    const parts = text.trim().split(/\s+/);
    let months = 1;
    if (parts.length >= 2) {
      const m = parts[1].match(/^(\d+)/);
      if (m) months = parseInt(m[1], 10);
    }
    if (months < 1) months = 1;
    if (months > 60) months = 60;

    const triggered = await triggerWorkflow("diary-analysis-agent.yml", {
      months: String(months),
      msg_id: String(msgId),
    });
    if (triggered) {
      await tgSend(
        `🔍 최근 <b>${months}개월</b> 생각일기 종합 분석 중...\n항목이 많으면 시간이 걸릴 수 있습니다. 잠시만 기다려주세요.`,
        msgId
      );
    } else {
      await tgSend("⚠️ 분석 에이전트 실행에 실패했습니다. 잠시 후 다시 시도해주세요.", msgId);
    }
    return true;
  }

  // /생각일기, /이사회, /board — 이사회 에이전트 즉시 실행
  if (cmd === "/생각일기" || cmd === "/이사회" || cmd === "/board") {
    // "N시간" 또는 숫자 파싱 (/board 3 또는 /생각일기 3시간)
    const parts = text.trim().split(/\s+/);
    let hours = 0;
    if (parts.length >= 2) {
      const m = parts[1].match(/^(\d+)/);
      if (m) hours = parseInt(m[1], 10);
    }
    const displayHours = hours > 0 ? `${hours}시간` : "기본 주기";

    // Supabase에 커맨드 정보 저장
    await sb.from("agent_settings").update({
      board_command_hours: hours,
      board_command_msg_id: msgId,
    }).eq("id", 1);

    // GitHub Actions 트리거
    const triggered = await triggerWorkflow("diary-board-agent.yml");
    if (triggered) {
      await tgSend(
        `📊 최근 <b>${displayHours}</b> 생각일기 이사회 분석 중...\n잠시 후 결과가 전송됩니다.`,
        msgId
      );
    } else {
      await tgSend("⚠️ 이사회 에이전트 실행에 실패했습니다. 잠시 후 다시 시도해주세요.", msgId);
    }
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

  // /질문줘 — AI 필요 → GitHub Actions 트리거
  if (["/질문줘", "/질문", "/ask"].includes(cmd)) {
    const pending = await getPendingQuestion();
    if (pending) {
      await tgSend(
        "아직 답변하지 않은 질문이 있습니다!\n답변을 보내거나 /건너뛰기 후 다시 시도해주세요."
      );
      return true;
    }
    await tgSend("질문을 생성하고 있습니다. 잠시만 기다려주세요...");
    const triggered = await triggerWorkflow("ask-question.yml");
    if (!triggered) {
      await tgSend("질문 생성 워크플로우 트리거에 실패했습니다.");
    }
    return true;
  }

  // /대본 — AI 필요 → GitHub Actions 트리거
  if (["/대본", "/draft"].includes(cmd)) {
    const draftParts = text.trim().split(/\s+(.+)/);
    const topicKeyword = draftParts.length > 1 ? draftParts[1].trim() : "";

    if (topicKeyword) {
      // 키워드 있으면 바로 실행
      await tgSend(`'${topicKeyword}' 대본 생성을 요청했습니다. 잠시 후 결과가 전송됩니다...`);
      const triggered = await triggerWorkflow("interview-draft.yml", { topic_name: topicKeyword });
      if (!triggered) await tgSend("대본 생성 워크플로우 트리거에 실패했습니다.");
    } else {
      // 키워드 없으면 주제 목록 보여주고 선택 대기
      const topics = await getActiveTopics();
      if (topics.length === 0) {
        await tgSend("활성화된 주제가 없습니다.");
      } else {
        const lines = ["<b>어떤 주제의 대본을 생성할까요?</b>\n"];
        for (const t of topics) {
          lines.push(`  • ${t.name}`);
        }
        lines.push("\n주제 키워드를 입력하거나, <b>전체</b>를 입력하면 모든 주제의 대본을 생성합니다.");
        await tgSend(lines.join("\n"));
        // 선택 대기 상태 저장
        await sb
          .from("agent_settings")
          .update({ draft_pending_at: new Date().toISOString() })
          .eq("id", 1);
      }
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

    // 답변 후 자동으로 대본 재생성 (기존 대본이 있는 경우에만)
    const { data: topicData } = await sb
      .from("interview_topics")
      .select("draft, draft_updated_at")
      .eq("id", topicId)
      .single();

    if (topicData?.draft) {
      // 마지막 대본 생성 후 3분 이상 경과했을 때만 재생성
      const lastDraft = topicData.draft_updated_at
        ? new Date(topicData.draft_updated_at).getTime()
        : 0;
      const now = Date.now();
      if (now - lastDraft > 3 * 60 * 1000) {
        await triggerWorkflow("interview-draft.yml");
      }
    }
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
      await handleCommand(text, settings, msg?.message_id ?? 0);
      return new Response("OK", { status: 200 });
    }

    // 대본 주제 선택 대기 중인지 확인
    const draftPendingAt = settings.draft_pending_at as string | null;
    if (draftPendingAt) {
      const pendingTime = new Date(draftPendingAt).getTime();
      const now = Date.now();
      // 5분 이내의 요청만 유효
      if (now - pendingTime < 5 * 60 * 1000) {
        // 대기 상태 해제
        await sb
          .from("agent_settings")
          .update({ draft_pending_at: null })
          .eq("id", 1);

        const choice = text.trim();
        if (choice === "전체") {
          await tgSend("전체 주제의 대본을 생성합니다. 잠시 후 결과가 전송됩니다...");
          const triggered = await triggerWorkflow("interview-draft.yml", { topic_name: "__all__" });
          if (!triggered) await tgSend("대본 생성 워크플로우 트리거에 실패했습니다.");
        } else {
          await tgSend(`'${choice}' 대본 생성을 요청했습니다. 잠시 후 결과가 전송됩니다...`);
          const triggered = await triggerWorkflow("interview-draft.yml", { topic_name: choice });
          if (!triggered) await tgSend("대본 생성 워크플로우 트리거에 실패했습니다.");
        }
        return new Response("OK", { status: 200 });
      }
      // 5분 지났으면 대기 상태 해제하고 일반 답변으로 처리
      await sb
        .from("agent_settings")
        .update({ draft_pending_at: null })
        .eq("id", 1);
    }

    // 일반 텍스트 → 답변 저장
    await saveAnswer(text, msg.message_id);
  } catch (e) {
    console.error("Webhook error:", e);
  }

  return new Response("OK", { status: 200 });
});
