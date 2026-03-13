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

  useEffect(() => {
    const startTime = Date.now();

    const load = async () => {
      const res = await fetch(`/api/studio/sessions/${sessionId}`);
      if (res.ok) {
        setData(await res.json());
      }
      setLoading(false);
    };
    load();

    // 세션 상태 폴링 (done + error가 아닌 한 계속)
    const interval = setInterval(async () => {
      const res = await fetch(`/api/studio/sessions/${sessionId}`);
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
      <div className="px-4 py-4 bg-gray-900 border-b border-gray-800">
        <div className="max-w-2xl mx-auto">
          <h1 className="text-xl font-bold">{session.title}</h1>
          <p className="text-gray-400 text-sm mt-1">
            {devices.length}대 카메라 · {clips.length}개 클립
          </p>
        </div>
      </div>

      <div className="max-w-2xl mx-auto p-4 space-y-6">
        {/* 업로드 대기 중 */}
        {session.status === 'uploading' && (() => {
          const doneCount = devices.filter(d => d.status === 'done').length;
          const waitingCount = devices.filter(d => d.status !== 'done' && d.status !== 'error').length;
          const errorCount = devices.filter(d => d.status === 'error').length;
          const allFinished = devices.every(d => d.status === 'done' || d.status === 'error');
          return (
            <div className="bg-blue-900/30 border border-blue-500/30 rounded-2xl p-6 text-center space-y-3">
              {!allFinished && (
                <div className="w-12 h-12 border-4 border-blue-500/30 border-t-blue-500 rounded-full animate-spin mx-auto" />
              )}
              <h2 className="text-lg font-semibold">
                {allFinished ? '업로드 완료' : '영상 업로드 중'}
              </h2>
              <p className="text-gray-400 text-sm">
                {doneCount}/{devices.length}대 카메라 업로드 완료
                {waitingCount > 0 && ` · ${waitingCount}대 대기중`}
                {allFinished && errorCount > 0 && ` · ${errorCount}대 실패`}
              </p>
              {allFinished && clips.length > 0 && (
                <p className="text-gray-500 text-xs">편집 준비 중...</p>
              )}
            </div>
          );
        })()}

        {/* 편집 상태 */}
        {session.status === 'editing' && (() => {
          const editStep = parseEditStep(data.result);
          return (
            <div className="bg-purple-900/30 border border-purple-500/30 rounded-2xl p-6 text-center space-y-4">
              <div className="w-12 h-12 border-4 border-purple-500/30 border-t-purple-500 rounded-full animate-spin mx-auto" />
              <h2 className="text-lg font-semibold">영상 편집 중</h2>
              {editStep ? (
                <>
                  <div className="space-y-2">
                    <p className="text-purple-300 font-medium">
                      {editStep.step}/{editStep.total} 단계: {editStep.description}
                    </p>
                    <div className="w-full h-2 bg-purple-900/50 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-purple-500 rounded-full transition-all duration-500"
                        style={{ width: `${(editStep.step / editStep.total) * 100}%` }}
                      />
                    </div>
                  </div>
                  <p className="text-gray-500 text-xs">완료되면 자동으로 전환됩니다</p>
                </>
              ) : (
                <p className="text-gray-400 text-sm">
                  AI가 다각도 영상을 분석하고 최적의 컷을 조합하고 있습니다.<br />
                  완료되면 자동으로 전환됩니다.
                </p>
              )}
            </div>
          );
        })()}

        {session.status === 'done' && data.result?.status === 'done' && (
          <div className="bg-green-900/30 border border-green-500/30 rounded-2xl p-6 text-center space-y-4">
            <div className="text-4xl">✅</div>
            <h2 className="text-lg font-semibold">편집 완료!</h2>
            {data.result.duration_ms && (
              <p className="text-gray-400 text-sm">
                편집 영상 길이: {formatDuration(data.result.duration_ms)}
              </p>
            )}
            <a
              href={`${process.env.NEXT_PUBLIC_SUPABASE_URL}/storage/v1/object/public/studio-clips/${data.result.storage_path}`}
              download
              className="inline-block bg-green-600 hover:bg-green-500 px-6 py-3 rounded-xl font-semibold transition"
            >
              편집 영상 다운로드
            </a>
          </div>
        )}
        {session.status === 'done' && !data.result && (
          <div className="bg-green-900/30 border border-green-500/30 rounded-2xl p-6 text-center space-y-3">
            <div className="text-4xl">✅</div>
            <h2 className="text-lg font-semibold">촬영 완료!</h2>
            <p className="text-gray-400 text-sm">
              아래에서 각 카메라의 클립을 개별 다운로드할 수 있습니다.
            </p>
          </div>
        )}
        {session.status === 'done' && data.result?.status === 'error' && (
          <div className="bg-red-900/30 border border-red-500/30 rounded-2xl p-6 text-center space-y-4">
            <div className="text-4xl">⚠️</div>
            <h2 className="text-lg font-semibold">편집 중 오류 발생</h2>
            <p className="text-gray-400 text-sm">영상 편집에 실패했습니다. 각 클립은 아래에서 개별 다운로드 가능합니다.</p>
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
              className="inline-block bg-purple-600 hover:bg-purple-500 disabled:bg-gray-600 disabled:cursor-not-allowed px-6 py-3 rounded-xl font-semibold transition"
            >
              {retrying ? '재시도 준비 중...' : '다시 편집 시도하기'}
            </button>
          </div>
        )}

        {/* 업로드된 클립 목록 */}
        <div>
          <h2 className="text-lg font-semibold mb-3">촬영된 클립</h2>
          <div className="space-y-2">
            {clips.map((clip, idx) => (
              <button
                key={clip.id}
                onClick={() => setSelectedClipIdx(idx)}
                className={`w-full flex items-center gap-4 p-4 rounded-xl transition text-left ${
                  selectedClipIdx === idx ? 'bg-purple-600/20 border border-purple-500/30' : 'bg-gray-900 hover:bg-gray-800'
                }`}
              >
                <div className="w-10 h-10 bg-gray-700 rounded-lg flex items-center justify-center text-lg">
                  🎥
                </div>
                <div className="flex-1 min-w-0">
                  <p className="font-medium">{getDeviceName(clip.device_id)}</p>
                  <p className="text-sm text-gray-400">
                    {formatDuration(clip.duration_ms)} · {formatSize(clip.file_size)}
                  </p>
                </div>
                <a
                  href={`${process.env.NEXT_PUBLIC_SUPABASE_URL}/storage/v1/object/public/studio-clips/${clip.storage_path}`}
                  download
                  onClick={(e) => e.stopPropagation()}
                  className="text-blue-400 hover:text-blue-300 text-sm underline"
                >
                  다운로드
                </a>
              </button>
            ))}
          </div>
        </div>

        {/* 네비게이션 버튼 */}
        <div className="pt-4 space-y-3">
          <button
            onClick={() => router.push('/studio')}
            className="w-full bg-purple-600 hover:bg-purple-500 py-3 rounded-xl font-semibold transition"
          >
            새 촬영 시작
          </button>
          <button
            onClick={() => router.push('/studio')}
            className="w-full bg-gray-800 hover:bg-gray-700 py-3 rounded-xl font-semibold transition"
          >
            홈으로 돌아가기
          </button>
        </div>
      </div>
    </div>
  );
}
