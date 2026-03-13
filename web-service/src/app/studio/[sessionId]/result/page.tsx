'use client';

import { useState, useEffect, use } from 'react';
import { useRouter } from 'next/navigation';
import type { StudioSession, StudioClip, StudioDevice, StudioResult } from '@/lib/studio';

interface SessionData {
  session: StudioSession;
  devices: StudioDevice[];
  clips: StudioClip[];
  result: StudioResult | null;
}

function parseEditStep(result: StudioResult | null): { step: number; total: number; description: string } | null {
  if (!result || result.status !== 'processing') return null;
  const match = result.storage_path?.match(/^step:(\d+)\/(\d+):(.+)$/);
  if (!match) return null;
  return { step: parseInt(match[1]), total: parseInt(match[2]), description: match[3] };
}

export default function ResultPage({ params }: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = use(params);
  const router = useRouter();
  const [data, setData] = useState<SessionData | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedClipIdx, setSelectedClipIdx] = useState(0);
  const [retrying, setRetrying] = useState(false);
  const [pollKey, setPollKey] = useState(0);
  const [editingElapsed, setEditingElapsed] = useState(0);
  const [editingStartTime] = useState(() => Date.now());

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
      if (res.ok) {
        setData(await res.json());
      }
      setLoading(false);
    };
    load();

    // 세션 상태 폴링 (done + error가 아닌 한 계속)
    const interval = setInterval(async () => {
      const res = await fetchSession();
      if (res.ok) {
        const d: SessionData = await res.json();
        setData(d);

        // done이고 결과가 완료이거나 에러면 폴링 중단
        if (d.session.status === 'done') {
          clearInterval(interval);
          return;
        }

        // uploading 상태에서 30초 이상 지났는데 stuck된 디바이스가 있으면 강제 전환
        const elapsed = Date.now() - startTime;
        if (d.session.status === 'uploading' && elapsed > 30000) {
          const stuckDevices = d.devices.filter(
            dev => dev.status !== 'done' && dev.status !== 'error'
          );
          if (stuckDevices.length > 0) {
            await fetch(`/api/studio/sessions/${sessionId}/finalize`, { method: 'POST' });
          }
        }
      }
    }, 5000);

    return () => clearInterval(interval);
  }, [sessionId, pollKey]);

  if (loading) {
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
            {devices.length}대 · {clips.length}클립
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

        {/* 편집 상태 */}
        {session.status === 'editing' && (() => {
          const editStep = parseEditStep(data.result);
          return (
            <div className="bg-purple-900/30 border border-purple-500/30 rounded-xl p-3 space-y-2">
              <div className="flex items-center gap-3">
                <div className="w-6 h-6 border-2 border-purple-500/30 border-t-purple-500 rounded-full animate-spin shrink-0" />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium">
                    영상 편집 중
                    {editStep && (
                      <span className="text-purple-300 ml-2">
                        {editStep.step}/{editStep.total} · {editStep.description}
                      </span>
                    )}
                  </p>
                </div>
                <span className="text-gray-500 text-xs font-mono shrink-0">
                  {Math.floor(editingElapsed / 60)}:{(editingElapsed % 60).toString().padStart(2, '0')}
                </span>
              </div>
              {editStep ? (
                <div className="w-full h-1.5 bg-purple-900/50 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-purple-500 rounded-full transition-all duration-500"
                    style={{ width: `${(editStep.step / editStep.total) * 100}%` }}
                  />
                </div>
              ) : (
                <p className="text-gray-500 text-xs">완료되면 자동으로 전환됩니다</p>
              )}
            </div>
          );
        })()}

        {session.status === 'done' && data.result?.status === 'done' && (
          <div className="bg-green-900/30 border border-green-500/30 rounded-xl p-3 flex items-center gap-3">
            <span className="text-xl">✅</span>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium">
                편집 완료
                {data.result.duration_ms && (
                  <span className="text-gray-400 font-normal ml-2">{formatDuration(data.result.duration_ms)}</span>
                )}
              </p>
            </div>
            <a
              href={`${process.env.NEXT_PUBLIC_SUPABASE_URL}/storage/v1/object/public/studio-clips/${data.result.storage_path}`}
              download
              className="bg-green-600 hover:bg-green-500 px-4 py-1.5 rounded-lg text-sm font-semibold transition shrink-0"
            >
              다운로드
            </a>
          </div>
        )}
        {session.status === 'done' && !data.result && (
          <div className="bg-green-900/30 border border-green-500/30 rounded-xl p-3 flex items-center gap-3">
            <span className="text-xl">✅</span>
            <p className="text-sm font-medium">촬영 완료 · 아래에서 클립을 다운로드하세요</p>
          </div>
        )}
        {session.status === 'done' && data.result?.status === 'error' && (
          <div className="bg-red-900/30 border border-red-500/30 rounded-xl p-3 space-y-2">
            <div className="flex items-center gap-3">
              <span className="text-xl">⚠️</span>
              <p className="text-sm font-medium flex-1">편집 실패 · 클립은 개별 다운로드 가능</p>
              <button
                disabled={retrying}
                onClick={async () => {
                  setRetrying(true);
                  try {
                    const res = await fetch(`/api/studio/sessions/${sessionId}/retry`, { method: 'POST' });
                    if (res.ok) {
                      const d = await res.json();
                      setData(prev => prev ? { ...prev, session: { ...prev.session, status: 'editing' }, result: d.result } : prev);
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

        {/* 촬영된 클립 */}
        <div>
          <h2 className="text-sm font-semibold text-gray-400 mb-1.5">촬영된 클립</h2>
          <div className="space-y-1">
            {clips.map((clip, idx) => (
              <div
                key={clip.id}
                className={`flex items-center gap-3 px-3 py-2 rounded-lg transition ${
                  selectedClipIdx === idx ? 'bg-purple-600/20 border border-purple-500/30' : 'bg-gray-900 hover:bg-gray-800'
                }`}
                onClick={() => setSelectedClipIdx(idx)}
              >
                <span className="text-base">🎥</span>
                <span className="flex-1 text-sm font-medium min-w-0 truncate">{getDeviceName(clip.device_id)}</span>
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
            ))}
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
