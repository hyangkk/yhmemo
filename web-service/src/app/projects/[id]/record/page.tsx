'use client';

import { useState, useEffect, useCallback, useRef, use } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth, getBrowserSupabase } from '@/lib/auth';
import CameraView from '@/components/studio/CameraView';

export default function ProjectRecordPage({ params }: { params: Promise<{ id: string }> }) {
  const { id: projectId } = use(params);
  const { user } = useAuth();
  const router = useRouter();

  const [memberId, setMemberId] = useState<string | null>(null);
  const [recordingSignal, setRecordingSignal] = useState<'idle' | 'start' | 'stop'>('idle');
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [clipCount, setClipCount] = useState(0);
  const [recordingStartTime, setRecordingStartTime] = useState<string | null>(null);
  const [joined, setJoined] = useState(false);

  const membIdRef = useRef(memberId);
  useEffect(() => { membIdRef.current = memberId; }, [memberId]);

  // 프로젝트 참여 (멤버 등록)
  useEffect(() => {
    if (!user || joined) return;
    const join = async () => {
      const res = await fetch(`/api/projects/${projectId}/join`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ userId: user.id, name: user.name }),
      });
      if (res.ok) {
        const data = await res.json();
        setMemberId(data.id);
        setJoined(true);
      }
    };
    join();
  }, [projectId, user, joined]);

  // 녹화 시작
  const handleStart = useCallback(() => {
    setRecordingStartTime(new Date().toISOString());
    setRecordingSignal('start');
  }, []);

  // 녹화 종료
  const handleStop = useCallback(() => {
    setRecordingSignal('stop');
  }, []);

  // XHR 업로드
  const uploadWithXHR = useCallback((url: string, blob: Blob, timeoutMs: number): Promise<boolean> => {
    return new Promise((resolve) => {
      const xhr = new XMLHttpRequest();
      xhr.open('PUT', url);
      xhr.setRequestHeader('Content-Type', blob.type);
      xhr.timeout = timeoutMs;
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) setUploadProgress(Math.round((e.loaded / e.total) * 100));
      };
      xhr.onload = () => resolve(xhr.status >= 200 && xhr.status < 300);
      xhr.onerror = () => resolve(false);
      xhr.ontimeout = () => resolve(false);
      xhr.send(blob);
    });
  }, []);

  // 녹화 완료 → 업로드 → 다시 대기 (result 페이지로 이동하지 않음!)
  const handleRecordingComplete = useCallback(async (blob: Blob, durationMs: number) => {
    const mId = membIdRef.current;
    if (!mId || !projectId || blob.size === 0) {
      setRecordingSignal('idle');
      return;
    }

    setUploading(true);
    setUploadProgress(0);

    const clipId = crypto.randomUUID();
    const ext = blob.type.includes('mp4') ? 'mp4' : 'webm';
    const timeoutMs = Math.max(60000, Math.min(300000, Math.round(blob.size / (1024 * 1024) * 4000)));
    const startedAt = recordingStartTime || new Date().toISOString();
    const endedAt = new Date().toISOString();

    let uploaded = false;
    let storagePath = '';

    for (let attempt = 1; attempt <= 3; attempt++) {
      try {
        setUploadProgress(0);
        const urlRes = await fetch(`/api/projects/${projectId}/clips`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ phase: 'url', memberId: mId, clipId, ext }),
        });
        const urlData = await urlRes.json();
        storagePath = urlData.storagePath;

        const success = await uploadWithXHR(urlData.signedUrl, blob, timeoutMs);
        if (success) { uploaded = true; break; }
        if (attempt < 3) await new Promise(r => setTimeout(r, attempt * 2000));
      } catch {
        if (attempt < 3) await new Promise(r => setTimeout(r, attempt * 2000));
      }
    }

    if (uploaded) {
      await fetch(`/api/projects/${projectId}/clips`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          phase: 'confirm',
          memberId: mId,
          durationMs,
          fileSize: blob.size,
          storagePath,
          startedAt,
          endedAt,
        }),
      });
      setClipCount(c => c + 1);
    }

    setUploading(false);
    setUploadProgress(0);
    setRecordingSignal('idle'); // 다시 대기 상태로! (반복 촬영 가능)
    setRecordingStartTime(null);
  }, [projectId, recordingStartTime, uploadWithXHR]);

  return (
    <div className="h-screen bg-black text-white flex flex-col">
      {/* 상단 헤더 */}
      <div className="flex-shrink-0 px-3 py-2 bg-gray-900/80 backdrop-blur-sm safe-area-top">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <button onClick={() => router.push(`/projects/${projectId}`)} className="text-gray-400 hover:text-white text-sm">←</button>
            {clipCount > 0 && (
              <span className="text-xs bg-green-600/30 text-green-300 px-2 py-0.5 rounded-full">
                {clipCount}클립 완료
              </span>
            )}
          </div>

          {!uploading && (
            recordingSignal !== 'start' ? (
              <button
                onClick={handleStart}
                disabled={!joined}
                className="flex items-center gap-1.5 bg-red-600 hover:bg-red-500 disabled:bg-gray-700 px-4 py-2 rounded-full text-sm font-semibold transition"
              >
                <div className="w-2.5 h-2.5 bg-white rounded-full" />
                {clipCount > 0 ? '다시 촬영' : '촬영 시작'}
              </button>
            ) : (
              <button
                onClick={handleStop}
                className="flex items-center gap-1.5 bg-gray-700 hover:bg-gray-600 px-4 py-2 rounded-full text-sm font-semibold transition"
              >
                <div className="w-2.5 h-2.5 bg-red-500 rounded-sm animate-pulse" />
                촬영 종료
              </button>
            )
          )}
        </div>
      </div>

      {/* 카메라 뷰 */}
      <div className="flex-1 relative">
        {joined && !uploading && (
          <CameraView
            onRecordingComplete={handleRecordingComplete}
            isHost={true}
            externalRecordingSignal={recordingSignal}
          />
        )}

        {/* 업로드 중 */}
        {uploading && (
          <div className="absolute inset-0 bg-black flex items-center justify-center">
            <div className="text-center space-y-4">
              <div className="w-16 h-16 border-4 border-white/20 border-t-white rounded-full animate-spin mx-auto" />
              <p className="text-lg">클립 업로드 중...</p>
              <div className="w-48 h-2 bg-gray-700 rounded-full mx-auto overflow-hidden">
                <div className="h-full bg-purple-500 rounded-full transition-all duration-300" style={{ width: `${uploadProgress}%` }} />
              </div>
              <p className="text-gray-400">{uploadProgress}%</p>
              <p className="text-gray-600 text-sm">업로드 후 다시 촬영할 수 있어요</p>
            </div>
          </div>
        )}

        {/* 대기 안내 (녹화 전) */}
        {!uploading && recordingSignal === 'idle' && joined && (
          <div className="absolute bottom-0 inset-x-0 p-4">
            <div className="bg-gray-900/90 backdrop-blur rounded-xl p-3 text-center">
              <p className="text-sm text-gray-300">
                {clipCount > 0
                  ? `${clipCount}개 클립 촬영 완료! 더 촬영하거나 대시보드에서 편집하세요`
                  : '촬영 시작 버튼을 눌러 촬영하세요. 여러 번 찍을 수 있어요!'}
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
