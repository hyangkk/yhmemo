"use client";

import { useState } from "react";

export default function FeedbackButton() {
  const [open, setOpen] = useState(false);
  const [type, setType] = useState<"like" | "improve" | "bug">("like");
  const [message, setMessage] = useState("");
  const [sent, setSent] = useState(false);
  const [sending, setSending] = useState(false);

  async function handleSubmit() {
    if (!message.trim()) return;
    setSending(true);
    try {
      await fetch("/api/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ type, message }),
      });
      setSent(true);
      setMessage("");
      setTimeout(() => {
        setSent(false);
        setOpen(false);
      }, 2000);
    } catch {
      // 실패해도 UX 방해하지 않음
    } finally {
      setSending(false);
    }
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="fixed bottom-6 right-6 w-12 h-12 rounded-full bg-amber-500 hover:bg-amber-600 text-white shadow-lg transition flex items-center justify-center z-50"
        aria-label="피드백 보내기"
      >
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
        </svg>
      </button>
    );
  }

  return (
    <div className="fixed bottom-6 right-6 w-80 bg-white dark:bg-gray-900 rounded-2xl shadow-2xl border border-gray-200 dark:border-gray-700 z-50 overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 bg-amber-50 dark:bg-amber-900/20 border-b border-gray-200 dark:border-gray-700">
        <span className="font-semibold text-sm text-gray-800 dark:text-gray-200">피드백</span>
        <button onClick={() => setOpen(false)} className="text-gray-400 hover:text-gray-600">
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      {sent ? (
        <div className="p-6 text-center">
          <div className="text-3xl mb-2">&#10003;</div>
          <p className="text-sm text-gray-600 dark:text-gray-300">감사합니다! 피드백이 전달됐어요.</p>
        </div>
      ) : (
        <div className="p-4 space-y-3">
          <div className="flex gap-2">
            {([["like", "좋아요"], ["improve", "개선"], ["bug", "버그"]] as const).map(([key, label]) => (
              <button
                key={key}
                onClick={() => setType(key)}
                className={`px-3 py-1.5 rounded-full text-xs font-medium transition ${
                  type === key
                    ? "bg-amber-500 text-white"
                    : "bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
          <textarea
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            placeholder="의견을 자유롭게 적어주세요..."
            rows={3}
            className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-amber-400"
          />
          <button
            onClick={handleSubmit}
            disabled={!message.trim() || sending}
            className="w-full py-2 rounded-lg bg-amber-500 hover:bg-amber-600 disabled:opacity-50 text-white text-sm font-medium transition"
          >
            {sending ? "전송 중..." : "보내기"}
          </button>
        </div>
      )}
    </div>
  );
}
