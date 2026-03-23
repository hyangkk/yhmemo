'use client';

import { useState, useRef, useEffect } from 'react';
import { useLang } from '@/lib/i18n';

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: number;
  status?: 'sending' | 'processing' | 'done' | 'error';
}

interface PromptChatProps {
  sessionId: string;
  clipCount: number;
  disabled?: boolean;
  onEditRequested?: () => void;
}

export default function PromptChat({ sessionId, clipCount, disabled, onEditRequested }: PromptChatProps) {
  const { lang } = useLang();

  const welcomeMessage = lang === 'ko'
    ? `${clipCount}개 클립이 준비되었습니다. 어떻게 편집해드릴까요?\n\n예시:\n• "3초마다 카메라 전환해줘"\n• "배경음악 넣어서 편집해줘"\n• "메인 카메라 중심으로 리액션 컷 넣어줘"\n• "5초 간격으로 교차편집하고 배경음악 추가"`
    : `${clipCount} clips ready. How would you like them edited?\n\nExamples:\n• "Switch cameras every 3 seconds"\n• "Edit with background music"\n• "Focus on the main camera with reaction cuts"\n• "Cross-edit every 5 seconds with BGM"`;

  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 'welcome',
      role: 'assistant',
      content: welcomeMessage,
      timestamp: Date.now(),
    },
  ]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // textarea 높이 자동 조절
  useEffect(() => {
    if (inputRef.current) {
      inputRef.current.style.height = 'auto';
      inputRef.current.style.height = Math.min(inputRef.current.scrollHeight, 120) + 'px';
    }
  }, [input]);

  const sendMessage = async () => {
    const text = input.trim();
    if (!text || sending || disabled) return;

    const userMsg: ChatMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: text,
      timestamp: Date.now(),
    };

    setMessages(prev => [...prev, userMsg]);
    setInput('');
    setSending(true);

    // 편집 요청 중 메시지
    const processingMsg: ChatMessage = {
      id: `assistant-${Date.now()}`,
      role: 'assistant',
      content: lang === 'ko' ? '편집 요청을 처리하고 있습니다...' : 'Processing your edit request...',
      timestamp: Date.now(),
      status: 'processing',
    };
    setMessages(prev => [...prev, processingMsg]);

    try {
      const res = await fetch(`/api/studio/sessions/${sessionId}/edit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode: 'prompt', prompt: text }),
      });

      if (res.ok) {
        setMessages(prev =>
          prev.map(m =>
            m.id === processingMsg.id
              ? { ...m, content: lang === 'ko' ? '편집을 시작했습니다. 완료되면 위에 결과가 표시됩니다.' : 'Edit started. Results will appear above when done.', status: 'done' }
              : m
          )
        );
        onEditRequested?.();
      } else {
        const err = await res.json().catch(() => ({ error: lang === 'ko' ? '요청 실패' : 'Request failed' }));
        setMessages(prev =>
          prev.map(m =>
            m.id === processingMsg.id
              ? { ...m, content: `${lang === 'ko' ? '오류' : 'Error'}: ${err.error || (lang === 'ko' ? '편집 요청에 실패했습니다.' : 'Edit request failed.')}`, status: 'error' }
              : m
          )
        );
      }
    } catch {
      setMessages(prev =>
        prev.map(m =>
          m.id === processingMsg.id
            ? { ...m, content: lang === 'ko' ? '네트워크 오류가 발생했습니다. 다시 시도해주세요.' : 'Network error. Please try again.', status: 'error' }
            : m
        )
      );
    } finally {
      setSending(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  return (
    <div className="bg-gray-900 border border-gray-700 rounded-xl overflow-hidden flex flex-col">
      {/* 채팅 헤더 */}
      <div className="px-3 py-2 border-b border-gray-800 flex items-center gap-2">
        <span className="text-sm">✨</span>
        <span className="text-sm font-semibold text-gray-300">{lang === 'ko' ? 'AI 편집 프롬프트' : 'AI Edit Prompt'}</span>
      </div>

      {/* 메시지 영역 */}
      <div className="flex-1 overflow-y-auto px-3 py-2 space-y-3 max-h-[300px] min-h-[150px]">
        {messages.map((msg) => (
          <div key={msg.id} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div
              className={`max-w-[85%] rounded-2xl px-3 py-2 text-sm whitespace-pre-wrap ${
                msg.role === 'user'
                  ? 'bg-purple-600 text-white'
                  : msg.status === 'error'
                  ? 'bg-red-900/40 text-red-300 border border-red-500/30'
                  : msg.status === 'processing'
                  ? 'bg-gray-800 text-gray-300 border border-purple-500/30'
                  : 'bg-gray-800 text-gray-300'
              }`}
            >
              {msg.status === 'processing' && (
                <span className="inline-block w-2 h-2 bg-purple-400 rounded-full animate-pulse mr-2 align-middle" />
              )}
              {msg.content}
            </div>
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* 입력 영역 */}
      <div className="border-t border-gray-800 p-2 flex items-end gap-2">
        <textarea
          ref={inputRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={disabled
            ? (lang === 'ko' ? '편집 완료 후 다시 입력할 수 있습니다' : 'Available after editing completes')
            : (lang === 'ko' ? '편집 지시를 입력하세요...' : 'Enter editing instructions...')}
          disabled={disabled || sending}
          rows={1}
          className="flex-1 bg-gray-800 text-white text-sm rounded-xl px-3 py-2 resize-none outline-none placeholder-gray-500 disabled:opacity-50 border border-gray-700 focus:border-purple-500/50 transition"
        />
        <button
          onClick={sendMessage}
          disabled={!input.trim() || sending || disabled}
          className="bg-purple-600 hover:bg-purple-500 disabled:bg-gray-700 disabled:text-gray-500 text-white px-3 py-2 rounded-xl text-sm font-semibold transition shrink-0"
        >
          {sending ? (
            <span className="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
          ) : (
            lang === 'ko' ? '전송' : 'Send'
          )}
        </button>
      </div>
    </div>
  );
}
