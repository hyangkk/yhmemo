'use client';

import { useState, useEffect, use } from 'react';
import { useRouter } from 'next/navigation';
import type { StudioSession, StudioClip, StudioDevice, StudioResult } from '@/lib/studio';
import { supabase } from '@/lib/supabase';

interface SessionData {
  session: StudioSession;
  devices: StudioDevice[];
  clips: StudioClip[];
  result: StudioResult | null;
  results?: StudioResult[];
}

const MODE_LABELS: Record<string, string> = {
  auto: '3초 교차편집',
  director: 'AI 감독 모드',
  split: '화면 분할',
  pip: 'PIP',
  prompt: 'AI 프롬프트',
};

function parseEditStep(result: StudioResult | null): { step: number; total: number; description: string } | null {
  if (!result || result.status !== 'processing') return null;
  const match = result.storage_path?.match(/^step:(\d+)\/(\d+):(.+)$/);
  if (!match) return null;
  return { step: parseInt(match[1]), total: parseInt(match[2]), description: match[3] };
}

function parseModeFromPath(path: string): string | null {
  // result_{id}_{mode}.mp4 패턴에서 모드 추출
  const match = path.match(/_([a-z]+)\.mp4$/);
  return match ? match[1] : null;
}

// storage_path에서 프롬프트 텍스트 추출 (mode:prompt:텍스트 형태)
function parsePromptFromResult(result: StudioResult): string | null {
  // 처리 중일 때는 storage_path에 mode:prompt:텍스트 형태
  const promptMatch = result.storage_path?.match(/^mode:prompt:(.+?)(?::audio=\w+)?$/);
  return promptMatch ? promptMatch[1] : null;
}

// 상대 시간 포맷 (몇 분 전, 몇 시간 전)
function formatRelativeTime(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return '방금 전';
  if (minutes < 60) return `${minutes}분 전`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}시간 전`;
  return `${Math.floor(hours / 24)}일 전`;
}

export default function ResultPage({ params }: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = use(params);
  const router = useRouter();
  const [data, setData] = useState<SessionData | null>(null);
  const [loading, setLoading] = useState(true);
  const [retrying, setRetrying] = useState(false);
  const [editingMode, setEditingMode] = useState<string | null>(null);
  const [pollKey, setPollKey] = useState(0);
  const [editingElapsed, setEditingElapsed] = useState(0);
  const [editingStartTime, setEditingStartTime] = useState(() => Date.now());
  const [finalizeCalled, setFinalizeCalled] = useState(false);
  const [audioMode, setAudioMode] = useState<'each' | 'best'>('each');
  const [addingTestClip, setAddingTestClip] = useState(false);
  const [hostChecked, setHostChecked] = useState(false);
  const [selectedBgm, setSelectedBgm] = useState<string | null>(null);
  const [selectedMode, setSelectedMode] = useState<string>('auto');
  const [selectedSubtitle, setSelectedSubtitle] = useState<string | null>(null);
  const [promptText, setPromptText] = useState('');

  // 호스트 카메라 기기만 결과 페이지 접근 가능 (촬영 참여자인 경우)
  useEffect(() => {
    if (!data) return;
    const myDeviceId = localStorage.getItem(`studio_device_${sessionId}`);
    // 촬영에 참여한 기기인데 호스트가 아니면 → 홈으로
    if (myDeviceId && data.session.host_device_id !== myDeviceId) {
      router.replace('/studio');
      return;
    }
    // 참여하지 않은 기기(홈에서 직접 접근) 또는 호스트 → 허용
    setHostChecked(true);
  }, [data, sessionId, router]);

  // 편집 중 경과 시간 타이머
  useEffect(() => {
    if (!data || (data.session.status !== 'editing' && data.session.status !== 'uploading')) {
      return;
    }
    const timer = setInterval(() => {
      setEditingElapsed(Math.floor((Date.now() - editingStartTime) / 1000));
    }, 1000);
    return () => clearInterval(timer);
  }, [data?.session.status, editingStartTime]);

  useEffect(() => {
    const startTime = Date.now();
    const fetchSession = () => fetch(`/api/studio/sessions/${sessionId}?_t=${Date.now()}`, { cache: 'no-store' });

    const load = async () => {
      const res = await fetchSession();
      if (res.ok) setData(await res.json());
      setLoading(false);
    };
    load();

    const interval = setInterval(async () => {
      const res = await fetchSession();
      if (res.ok) {
        const d: SessionData = await res.json();
        setData(d);
        if (d.session.status === 'done') {
          clearInterval(interval);
          return;
        }
        const elapsed = Date.now() - startTime;
        // 모든 디바이스가 done/error이면 바로 finalize (편집 전환)
        if (d.session.status === 'uploading') {
          const allFinished = d.devices.every(dev => dev.status === 'done' || dev.status === 'error');
          if (allFinished) {
            await fetch(`/api/studio/sessions/${sessionId}/finalize`, { method: 'POST' });
          } else if (elapsed > 90000) {
            // 90초 초과 시 stuck 디바이스 강제 완료 (1회만, force=true)
            setFinalizeCalled(prev => {
              if (!prev) {
                fetch(`/api/studio/sessions/${sessionId}/finalize`, {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ force: true }),
                });
              }
              return true;
            });
          } else {
            // 아직 타임아웃 전: stuck 디바이스(connected 등)만 정리, uploading은 유지
            await fetch(`/api/studio/sessions/${sessionId}/finalize`, { method: 'POST' });
          }
        }
      }
    }, 5000);

    return () => clearInterval(interval);
  }, [sessionId, pollKey]);

  const requestEdit = async (mode: string, prompt?: string) => {
    setEditingMode(mode);
    setEditingElapsed(0);
    setEditingStartTime(Date.now());
    try {
      const body: Record<string, string> = { mode, audio_mode: audioMode };
      if (prompt) body.prompt = prompt;
      const res = await fetch(`/api/studio/sessions/${sessionId}/edit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (res.ok) {
        const d = await res.json();
        setData(prev => prev ? {
          ...prev,
          session: { ...prev.session, status: 'editing' },
          result: d.result,
        } : prev);
        setPollKey(k => k + 1);
      }
    } finally {
      setEditingMode(null);
    }
  };

  if (loading || !hostChecked) {
    return (
      <div className="min-h-screen bg-black text-white flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-white border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!data) {
    return (
      <div className="min-h-screen bg-black text-white flex items-center justify-center">
        <p>세션을 찾을 수 없습니다</p>
      </div>
    );
  }

  const { session, devices, clips } = data;
  const failedDevices = devices.filter(d => !clips.some(c => c.device_id === d.id));
  const allResults = data.results || (data.result ? [data.result] : []);
  const doneResults = allResults.filter(r => r.status === 'done');
  const processingResult = allResults.find(r => r.status === 'processing');
  const latestResult = processingResult || doneResults[0] || allResults[0] || null;

  // 이미 완료된 모드 목록
  const completedModes = new Set(
    doneResults.map(r => parseModeFromPath(r.storage_path)).filter(Boolean)
  );

  const getDeviceName = (deviceId: string) => {
    return devices.find(d => d.id === deviceId)?.name || '카메라';
  };

  const formatDuration = (ms: number | null) => {
    if (!ms) return '--:--';
    const s = Math.floor(ms / 1000);
    const m = Math.floor(s / 60);
    return `${m}:${(s % 60).toString().padStart(2, '0')}`;
  };

  const formatSize = (bytes: number | null) => {
    if (!bytes) return '-';
    if (bytes > 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)}GB`;
    if (bytes > 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
    return `${(bytes / 1024).toFixed(1)}KB`;
  };

  return (
    <div className="min-h-screen bg-black text-white">
      {/* 상태 헤더 */}
      <div className="px-4 py-2.5 bg-gray-900 border-b border-gray-800">
        <div className="max-w-2xl mx-auto flex items-baseline gap-2">
          <h1 className="text-lg font-bold">{session.title}</h1>
          <span className="text-gray-500 text-xs">
            {clips.length}클립{failedDevices.length > 0 && ` · ${failedDevices.length}대 미사용`}
          </span>
        </div>
      </div>

      <div className="max-w-2xl mx-auto p-3 space-y-3">
        {/* 업로드 대기 중 */}
        {session.status === 'uploading' && (() => {
          const doneCount = devices.filter(d => d.status === 'done').length;
          const waitingCount = devices.filter(d => d.status !== 'done' && d.status !== 'error').length;
          const errorCount = devices.filter(d => d.status === 'error').length;
          const allFinished = devices.every(d => d.status === 'done' || d.status === 'error');
          return (
            <div className="bg-blue-900/30 border border-blue-500/30 rounded-xl p-3 flex items-center gap-3">
              {!allFinished && (
                <div className="w-6 h-6 border-2 border-blue-500/30 border-t-blue-500 rounded-full animate-spin shrink-0" />
              )}
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium">
                  {allFinished ? '업로드 완료' : '영상 업로드 중'}
                  <span className="text-gray-400 font-normal ml-2">
                    {doneCount}/{devices.length}대
                    {waitingCount > 0 && ` · ${waitingCount}대 대기`}
                    {allFinished && errorCount > 0 && ` · ${errorCount}대 실패`}
                  </span>
                </p>
                {allFinished && clips.length > 0 && (
                  <p className="text-gray-500 text-xs mt-0.5">편집 준비 중...</p>
                )}
              </div>
            </div>
          );
        })()}

        {/* 편집 진행 중 */}
        {session.status === 'editing' && (() => {
          const editStep = parseEditStep(latestResult);
          const rawPath = latestResult?.storage_path || '';
          const rawMatch = rawPath.match(/^step:(\d+)\/(\d+):(.+)$/);
          const directStep = rawMatch ? { step: parseInt(rawMatch[1]), total: parseInt(rawMatch[2]), description: rawMatch[3] } : null;
          const step = editStep || directStep;
          // 현재 편집 중인 모드 표시
          const modeMatch = rawPath.match(/^mode:(\w+)$/);
          const currentMode = modeMatch ? MODE_LABELS[modeMatch[1]] || modeMatch[1] : null;
          return (
            <div className="bg-purple-900/30 border border-purple-500/30 rounded-xl p-3 space-y-2">
              <div className="flex items-center gap-3">
                <div className="w-6 h-6 border-2 border-purple-500/30 border-t-purple-500 rounded-full animate-spin shrink-0" />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium">
                    영상 편집 중
                    {currentMode && !step && (
                      <span className="text-purple-300 ml-2">{currentMode}</span>
                    )}
                    {step && (
                      <span className="text-purple-300 ml-2">
                        {step.step}/{step.total} · {step.description}
                      </span>
                    )}
                  </p>
                </div>
                <span className="text-gray-500 text-xs font-mono shrink-0">
                  {Math.floor(editingElapsed / 60)}:{(editingElapsed % 60).toString().padStart(2, '0')}
                </span>
              </div>
              {step ? (
                <div className="w-full h-1.5 bg-purple-900/50 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-purple-500 rounded-full transition-all duration-500"
                    style={{ width: `${(step.step / step.total) * 100}%` }}
                  />
                </div>
              ) : (
                <p className="text-gray-500 text-xs">완료되면 자동으로 전환됩니다</p>
              )}
            </div>
          );
        })()}

        {/* 편집 완료된 결과들 (최신순) */}
        {session.status === 'done' && doneResults.length > 0 && (
          <div className="space-y-2">
            <h2 className="text-sm font-semibold text-gray-400">
              편집 결과 <span className="text-gray-600 font-normal">{doneResults.length}개</span>
            </h2>
            {[...doneResults]
              .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
              .map((result, idx) => {
              const mode = parseModeFromPath(result.storage_path);
              const modeLabel = mode ? MODE_LABELS[mode] || mode : '편집 결과';
              const promptText = parsePromptFromResult(result);
              const isLatest = idx === 0;
              return (
                <div
                  key={result.id}
                  className={`rounded-xl p-3 space-y-1.5 ${
                    isLatest
                      ? 'bg-green-900/40 border-2 border-green-500/50'
                      : 'bg-gray-900/60 border border-gray-700/50'
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <span className="text-lg">
                      {mode === 'director' ? '🎬' : mode === 'prompt' ? '✨' : '✅'}
                    </span>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <p className="text-sm font-medium">
                          {promptText ? 'AI 프롬프트' : modeLabel}
                        </p>
                        {isLatest && (
                          <span className="text-[10px] font-bold bg-green-500 text-black px-1.5 py-0.5 rounded">
                            최신
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-2 mt-0.5">
                        {result.duration_ms && (
                          <span className="text-xs text-gray-500">{formatDuration(result.duration_ms)}</span>
                        )}
                        <span className="text-xs text-gray-600">{formatRelativeTime(result.created_at)}</span>
                      </div>
                    </div>
                    <a
                      href={`${process.env.NEXT_PUBLIC_SUPABASE_URL}/storage/v1/object/public/studio-clips/${result.storage_path}`}
                      download
                      className={`px-4 py-1.5 rounded-lg text-sm font-semibold transition shrink-0 ${
                        isLatest
                          ? 'bg-green-600 hover:bg-green-500'
                          : 'bg-gray-700 hover:bg-gray-600 text-gray-300'
                      }`}
                    >
                      다운로드
                    </a>
                  </div>
                  {promptText && (
                    <p className="text-xs text-purple-300/80 bg-purple-900/20 rounded-lg px-2.5 py-1.5 truncate">
                      &ldquo;{promptText}&rdquo;
                    </p>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {session.status === 'done' && doneResults.length === 0 && !latestResult && clips.length >= 2 && (
          <div className="bg-purple-900/30 border border-purple-500/30 rounded-xl p-3 flex items-center gap-3">
            <span className="text-xl">🎬</span>
            <p className="text-sm font-medium">촬영 완료! 아래에서 편집 설정 후 편집을 시작하세요</p>
          </div>
        )}
        {session.status === 'done' && doneResults.length === 0 && !latestResult && clips.length < 2 && (
          <div className="bg-green-900/30 border border-green-500/30 rounded-xl p-3 flex items-center gap-3">
            <span className="text-xl">✅</span>
            <p className="text-sm font-medium">촬영 완료 · 아래에서 클립을 다운로드하세요</p>
          </div>
        )}

        {/* 편집 실패 */}
        {session.status === 'done' && latestResult?.status === 'error' && doneResults.length === 0 && (
          <div className="bg-red-900/30 border border-red-500/30 rounded-xl p-3 space-y-2">
            <div className="flex items-center gap-3">
              <span className="text-xl">⚠️</span>
              <p className="text-sm font-medium flex-1">편집 실패 · 아래에서 다시 시도하세요</p>
              <button
                disabled={retrying}
                onClick={async () => {
                  setRetrying(true);
                  try {
                    const res = await fetch(`/api/studio/sessions/${sessionId}/retry`, { method: 'POST' });
                    if (res.ok) {
                      setData(prev => prev ? { ...prev, session: { ...prev.session, status: 'editing' } } : prev);
                      setPollKey(k => k + 1);
                    }
                  } finally {
                    setRetrying(false);
                  }
                }}
                className="bg-purple-600 hover:bg-purple-500 disabled:bg-gray-600 px-4 py-1.5 rounded-lg text-sm font-semibold transition shrink-0"
              >
                {retrying ? '준비 중...' : '다시 시도'}
              </button>
            </div>
          </div>
        )}

        {/* 편집 설정 패널 (done 상태 + 클립 2개 이상) */}
        {session.status === 'done' && clips.length >= 2 && (
          <div className="bg-gray-900 border border-gray-700 rounded-xl overflow-hidden">
            <div className="px-3 py-2 border-b border-gray-800">
              <span className="text-sm font-semibold text-gray-300">편집 설정</span>
            </div>
            <div className="p-3 space-y-3">
              {/* 편집 모드 */}
              <div>
                <h3 className="text-xs font-semibold text-gray-500 mb-1.5">편집 모드</h3>
                <div className="grid grid-cols-2 gap-1.5">
                  <button
                    onClick={() => setSelectedMode('auto')}
                    className={`p-2 rounded-lg text-left transition border ${
                      selectedMode === 'auto'
                        ? 'bg-purple-900/40 border-purple-500/50'
                        : 'bg-gray-800 border-gray-700 hover:bg-gray-750'
                    }`}
                  >
                    <p className="text-sm font-semibold">🔄 교차편집</p>
                    <p className="text-[11px] text-gray-400">3초마다 카메라 전환</p>
                  </button>
                  <button
                    onClick={() => setSelectedMode('director')}
                    className={`p-2 rounded-lg text-left transition border ${
                      selectedMode === 'director'
                        ? 'bg-purple-900/40 border-purple-500/50'
                        : 'bg-gray-800 border-gray-700 hover:bg-gray-750'
                    }`}
                  >
                    <p className="text-sm font-semibold">🎬 감독 모드</p>
                    <p className="text-[11px] text-gray-400">메인 + 리액션 컷</p>
                  </button>
                </div>
              </div>

              {/* 배경음악 */}
              <div>
                <h3 className="text-xs font-semibold text-gray-500 mb-1.5">배경음악</h3>
                <div className="flex gap-1.5 flex-wrap">
                  <button
                    onClick={() => setSelectedBgm(null)}
                    className={`px-3 py-1.5 rounded-lg text-sm transition border ${
                      selectedBgm === null
                        ? 'bg-gray-700 border-gray-500 text-white'
                        : 'bg-gray-800/50 border-gray-700 text-gray-400 hover:bg-gray-800'
                    }`}
                  >
                    없음
                  </button>
                  <button
                    onClick={() => setSelectedBgm('calm')}
                    className={`px-3 py-1.5 rounded-lg text-sm transition border ${
                      selectedBgm === 'calm'
                        ? 'bg-teal-900/50 border-teal-500/60 text-teal-300'
                        : 'bg-gray-800/50 border-gray-700 text-gray-400 hover:bg-gray-800'
                    }`}
                  >
                    🎵 잔잔한
                  </button>
                  <button
                    onClick={() => setSelectedBgm('upbeat')}
                    className={`px-3 py-1.5 rounded-lg text-sm transition border ${
                      selectedBgm === 'upbeat'
                        ? 'bg-pink-900/50 border-pink-500/60 text-pink-300'
                        : 'bg-gray-800/50 border-gray-700 text-gray-400 hover:bg-gray-800'
                    }`}
                  >
                    🎶 신나는
                  </button>
                </div>
              </div>

              {/* 자막 */}
              <div>
                <h3 className="text-xs font-semibold text-gray-500 mb-1.5">자막</h3>
                <div className="flex gap-1.5 flex-wrap">
                  <button
                    onClick={() => setSelectedSubtitle(null)}
                    className={`px-3 py-1.5 rounded-lg text-sm transition border ${
                      selectedSubtitle === null
                        ? 'bg-gray-700 border-gray-500 text-white'
                        : 'bg-gray-800/50 border-gray-700 text-gray-400 hover:bg-gray-800'
                    }`}
                  >
                    없음
                  </button>
                  <button
                    onClick={() => setSelectedSubtitle('blackBg')}
                    className={`px-3 py-1.5 rounded-lg text-sm transition border ${
                      selectedSubtitle === 'blackBg'
                        ? 'bg-yellow-900/50 border-yellow-500/60 text-yellow-300'
                        : 'bg-gray-800/50 border-gray-700 text-gray-400 hover:bg-gray-800'
                    }`}
                  >
                    <span className="inline-flex items-center gap-1">
                      <span className="inline-block px-1 py-0.5 bg-black text-white text-[10px] rounded leading-none">가</span>
                      검은 배경
                    </span>
                  </button>
                  <button
                    onClick={() => setSelectedSubtitle('outline')}
                    className={`px-3 py-1.5 rounded-lg text-sm transition border ${
                      selectedSubtitle === 'outline'
                        ? 'bg-yellow-900/50 border-yellow-500/60 text-yellow-300'
                        : 'bg-gray-800/50 border-gray-700 text-gray-400 hover:bg-gray-800'
                    }`}
                  >
                    <span className="inline-flex items-center gap-1">
                      <span className="inline-block px-1 py-0.5 text-white text-[10px] leading-none" style={{textShadow: '1px 1px 0 #000, -1px -1px 0 #000, 1px -1px 0 #000, -1px 1px 0 #000'}}>가</span>
                      테두리
                    </span>
                  </button>
                </div>
              </div>

              {/* 음성 설정 */}
              <div>
                <h3 className="text-xs font-semibold text-gray-500 mb-1.5">음성</h3>
                <div className="flex gap-1.5">
                  <button
                    onClick={() => setAudioMode('each')}
                    className={`px-3 py-1.5 rounded-lg text-sm transition border ${
                      audioMode === 'each'
                        ? 'bg-blue-900/40 border-blue-500/50 text-blue-300'
                        : 'bg-gray-800/50 border-gray-700 text-gray-400 hover:bg-gray-800'
                    }`}
                  >
                    🎙️ 각 영상 음성
                  </button>
                  <button
                    onClick={() => setAudioMode('best')}
                    className={`px-3 py-1.5 rounded-lg text-sm transition border ${
                      audioMode === 'best'
                        ? 'bg-blue-900/40 border-blue-500/50 text-blue-300'
                        : 'bg-gray-800/50 border-gray-700 text-gray-400 hover:bg-gray-800'
                    }`}
                  >
                    🔊 최적 음성만
                  </button>
                </div>
              </div>

              {/* 추가 지시사항 (프롬프트) */}
              <div>
                <h3 className="text-xs font-semibold text-gray-500 mb-1.5">추가 지시사항 <span className="text-gray-600 font-normal">(선택)</span></h3>
                <input
                  type="text"
                  value={promptText}
                  onChange={(e) => setPromptText(e.target.value)}
                  placeholder="예: 5초 간격으로 전환해줘"
                  className="w-full bg-gray-800 text-white text-sm rounded-lg px-3 py-2 outline-none placeholder-gray-500 border border-gray-700 focus:border-purple-500/50 transition"
                />
              </div>

              {/* 편집하기 버튼 */}
              <button
                disabled={!!editingMode}
                onClick={() => {
                  const bgmMap: Record<string, string> = {
                    calm: '잔잔한 클래식 배경음악 넣어줘',
                    upbeat: '신나는 배경음악 넣어줘',
                  };
                  const subtitleMap: Record<string, string> = {
                    blackBg: '자동 자막을 넣어줘. 스타일: 흰색 글씨에 검은색 반투명 배경 박스',
                    outline: '자동 자막을 넣어줘. 스타일: 흰색 글씨에 검은색 테두리(외곽선)',
                  };
                  const modeMap: Record<string, string> = {
                    auto: '교차편집',
                    director: '감독 모드로 편집',
                  };

                  const hasBgm = selectedBgm && bgmMap[selectedBgm];
                  const hasSubtitle = selectedSubtitle && subtitleMap[selectedSubtitle];
                  const hasPrompt = promptText.trim();

                  if (hasBgm || hasSubtitle || hasPrompt) {
                    const parts: string[] = [];
                    parts.push(modeMap[selectedMode] || '교차편집');
                    if (hasBgm) parts.push(bgmMap[selectedBgm!]);
                    if (hasSubtitle) parts.push(subtitleMap[selectedSubtitle!]);
                    if (hasPrompt) parts.push(promptText.trim());
                    requestEdit('prompt', parts.join(', '));
                  } else {
                    requestEdit(selectedMode);
                  }
                }}
                className="w-full bg-purple-600 hover:bg-purple-500 disabled:bg-gray-700 disabled:text-gray-500 py-3 rounded-xl text-sm font-bold transition"
              >
                {editingMode ? (
                  <span className="flex items-center justify-center gap-2">
                    <span className="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                    편집 준비 중...
                  </span>
                ) : '편집하기'}
              </button>
            </div>
          </div>
        )}

        {/* 편집 중일 때 설정 패널 비활성 표시 */}
        {session.status === 'editing' && clips.length >= 2 && (
          <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-3 opacity-50">
            <p className="text-sm text-gray-500 text-center">편집이 완료되면 다시 설정할 수 있습니다</p>
          </div>
        )}

        {/* 촬영된 클립 */}
        <div>
          <h2 className="text-sm font-semibold text-gray-400 mb-1.5">촬영된 클립</h2>
          <div className="space-y-1">
            {devices.filter(d => clips.some(c => c.device_id === d.id)).map((device) => {
              const clip = clips.find(c => c.device_id === device.id)!;
              return (
                <div
                  key={device.id}
                  className="flex items-center gap-3 px-3 py-2 rounded-lg bg-gray-900 hover:bg-gray-800 transition"
                >
                  <span className="text-base">🎥</span>
                  <span className="flex-1 text-sm font-medium min-w-0 truncate">{device.name}</span>
                  <span className="text-xs text-gray-500">{formatDuration(clip.duration_ms)} · {formatSize(clip.file_size)}</span>
                  <a
                    href={`${process.env.NEXT_PUBLIC_SUPABASE_URL}/storage/v1/object/public/studio-clips/${clip.storage_path}`}
                    download
                    onClick={(e) => e.stopPropagation()}
                    className="text-blue-400 hover:text-blue-300 text-xs"
                  >
                    저장
                  </a>
                </div>
              );
            })}
            {/* 클립 없는 디바이스 (업로드 실패/미사용) */}
            {failedDevices.map((device) => (
              <div
                key={device.id}
                className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-gray-600 text-xs"
              >
                <span>{device.name}</span>
                <span>·</span>
                <span>
                  {device.status === 'error' ? '업로드 실패' : device.status === 'uploading' ? '업로드 중...' : '미사용'}
                </span>
              </div>
            ))}

            {/* 테스트 영상 추가 버튼 */}
            <button
              disabled={addingTestClip || session.status === 'editing'}
              onClick={async () => {
                setAddingTestClip(true);
                try {
                  const res = await fetch(`/api/studio/sessions/${sessionId}/test-clip`, { method: 'POST' });
                  if (res.ok) {
                    setPollKey(k => k + 1);
                  } else {
                    const err = await res.json().catch(() => ({ error: '실패' }));
                    alert(err.error || '테스트 영상 추가 실패');
                  }
                } finally {
                  setAddingTestClip(false);
                }
              }}
              className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg border border-dashed border-gray-600 hover:border-gray-400 text-gray-400 hover:text-gray-300 text-sm transition disabled:opacity-30"
            >
              {addingTestClip ? (
                <>
                  <span className="inline-block w-4 h-4 border-2 border-gray-400/30 border-t-gray-400 rounded-full animate-spin" />
                  추가 중...
                </>
              ) : (
                <>
                  <span>+</span>
                  테스트 영상 추가
                </>
              )}
            </button>
          </div>
        </div>

        {/* 하단 버튼 */}
        <button
          onClick={() => router.push('/studio')}
          className="w-full bg-gray-800 hover:bg-gray-700 py-2.5 rounded-xl text-sm font-semibold transition"
        >
          홈으로 가기
        </button>
      </div>
    </div>
  );
}
