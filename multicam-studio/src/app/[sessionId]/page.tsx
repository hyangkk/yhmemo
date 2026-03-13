'use client';

import { useState, useEffect, useCallback, useRef, use } from 'react';
import { useRouter } from 'next/navigation';
import { useStudioSession } from '@/hooks/useStudioSession';
import { supabase } from '@/lib/supabase';
import CameraView from '@/components/studio/CameraView';

export default function SessionRoomPage({ params }: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = use(params);
  const router = useRouter();
  const {
    session,
    devices,
    myDevice,
    isHost,
    loading,
    error,
    joinSession,
    sendSignal,
    updateDeviceStatus,
  } = useStudioSession(sessionId);

  const [recordingSignal, setRecordingSignal] = useState<'idle' | 'start' | 'stop'>('idle');
  const [uploadProgress, setUploadProgress] = useState<number>(0);
  const [uploadSize, setUploadSize] = useState<number>(0);
  const [uploading, setUploading] = useState(false);
  const [joined, setJoined] = useState(false);
  const joiningRef = useRef(false);

  // myDevice를 ref로 추적 (stale closure 방지)
  const myDeviceRef = useRef(myDevice);
  useEffect(() => { myDeviceRef.current = myDevice; }, [myDevice]);

  // 세션에 자동 참여 (이중 호출 방지)
  useEffect(() => {
    if (sessionId && !joined && !joiningRef.current && !loading && session) {
      joiningRef.current = true;
      joinSession(sessionId).then((device) => {
        if (device) setJoined(true);
        joiningRef.current = false;
      }).catch(() => { joiningRef.current = false; });
    }
  }, [sessionId, joined, loading, session, joinSession]);

  // 외부 시그널 수신 (비호스트) - Broadcast + Realtime 세션 상태 폴백
  useEffect(() => {
    const handleSignal = (e: Event) => {
      const signal = (e as CustomEvent).detail.signal;
      setRecordingSignal(signal);
    };
    window.addEventListener('studio-signal', handleSignal);
    return () => window.removeEventListener('studio-signal', handleSignal);
  }, []);

  // 세션 상태 변경 감지 (Broadcast 못 받았을 때 폴백)
  useEffect(() => {
    if (!session) return;
    if (session.status === 'recording' && recordingSignal === 'idle') {
      setRecordingSignal('start');
    } else if (session.status === 'uploading' && recordingSignal === 'start') {
      setRecordingSignal('stop');
    }
  }, [session?.status, recordingSignal]);

  // 세션 상태 주기적 폴링 (Realtime 누락 대비)
  useEffect(() => {
    if (!sessionId || uploading) return;
    const poll = setInterval(async () => {
      try {
        const res = await fetch(`/api/studio/sessions/${sessionId}`);
        if (!res.ok) return;
        const data = await res.json();
        const status = data.session?.status;
        if (!status) return;
        // 세션이 uploading 이후 단계인데 아직 녹화 중이면 강제 stop
        if ((status === 'uploading' || status === 'editing' || status === 'done') && recordingSignal === 'start') {
          setRecordingSignal('stop');
        }
      } catch {}
    }, 3000);
    return () => clearInterval(poll);
  }, [sessionId, uploading, recordingSignal]);

  // 호스트: 녹화 시작 (시그널 설정을 먼저, 네트워크 작업은 best-effort)
  const handleStartRecording = useCallback(async () => {
    setRecordingSignal('start');
    try { await sendSignal('start'); } catch {}
    try { await updateDeviceStatus('recording'); } catch {}
  }, [sendSignal, updateDeviceStatus]);

  // 호스트: 녹화 종료 (확인 후 전체 카메라 종료)
  const handleStopRecording = useCallback(async () => {
    if (!window.confirm('녹화를 종료하시겠습니까?\n모든 카메라의 녹화가 종료됩니다.')) return;
    setRecordingSignal('stop');
    try { await sendSignal('stop'); } catch {}
  }, [sendSignal]);

  // 게스트: 내 카메라만 녹화 종료 (다른 카메라는 계속 녹화)
  const handleGuestStopRecording = useCallback(() => {
    if (!window.confirm('내 카메라 녹화를 종료하시겠습니까?\n다른 카메라는 계속 녹화됩니다.')) return;
    setRecordingSignal('stop');
  }, []);

  // XHR 업로드 (Promise 래핑, 진행률 콜백)
  const uploadWithXHR = useCallback((url: string, blob: Blob, timeoutMs: number): Promise<boolean> => {
    return new Promise((resolve) => {
      const xhr = new XMLHttpRequest();
      xhr.open('PUT', url);
      xhr.setRequestHeader('Content-Type', blob.type);
      xhr.timeout = timeoutMs;

      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) {
          setUploadProgress(Math.round((e.loaded / e.total) * 100));
        }
      };

      xhr.onload = () => resolve(xhr.status >= 200 && xhr.status < 300);
      xhr.onerror = () => resolve(false);
      xhr.ontimeout = () => resolve(false);
      xhr.send(blob);
    });
  }, []);

  // signed URL 발급
  const getSignedUrl = useCallback(async (deviceId: string, ext: string) => {
    const res = await fetch(`/api/studio/sessions/${sessionId}/upload`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ phase: 'url', deviceId, ext }),
    });
    if (!res.ok) throw new Error('signed URL 발급 실패');
    return res.json();
  }, [sessionId]);

  // 녹화 완료 → 업로드 (최대 3회 재시도)
  const handleRecordingComplete = useCallback(async (blob: Blob, durationMs: number) => {
    const device = myDeviceRef.current;
    const goToResult = () => {
      router.push(`/${sessionId}/result`);
    };

    // device가 없거나 녹화된 데이터가 없으면 바로 결과 페이지로
    if (!device || !sessionId || blob.size === 0) {
      if (device) {
        try { await supabase.from('studio_devices').update({ status: 'error' }).eq('id', device.id); } catch {}
      }
      goToResult();
      return;
    }

    setUploading(true);
    setUploadSize(blob.size);
    setUploadProgress(0);

    // 디바이스 상태를 직접 업데이트
    try {
      await supabase.from('studio_devices').update({ status: 'uploading' }).eq('id', device.id);
    } catch {}

    const ext = blob.type.includes('mp4') ? 'mp4' : 'webm';
    // 파일 크기에 따라 타임아웃 조정 (최소 60초, MB당 4초, 최대 5분)
    const timeoutMs = Math.max(60000, Math.min(300000, Math.round(blob.size / (1024 * 1024) * 4000)));
    const MAX_RETRIES = 3;

    let uploaded = false;
    let storagePath = '';

    for (let attempt = 1; attempt <= MAX_RETRIES; attempt++) {
      try {
        setUploadProgress(0);

        // 매 시도마다 새 signed URL 발급 (이전 URL은 만료될 수 있음)
        const urlData = await getSignedUrl(device.id, ext);
        storagePath = urlData.storagePath;

        const success = await uploadWithXHR(urlData.signedUrl, blob, timeoutMs);
        if (success) {
          uploaded = true;
          break;
        }

        console.warn(`[studio] 업로드 실패 (${attempt}/${MAX_RETRIES}), ${attempt < MAX_RETRIES ? '재시도...' : '포기'}`);
        if (attempt < MAX_RETRIES) {
          await new Promise(r => setTimeout(r, attempt * 2000)); // 2초, 4초 대기
        }
      } catch (err) {
        console.warn(`[studio] 업로드 에러 (${attempt}/${MAX_RETRIES}):`, err);
        if (attempt < MAX_RETRIES) {
          await new Promise(r => setTimeout(r, attempt * 2000));
        }
      }
    }

    if (uploaded) {
      // 업로드 성공 → 메타데이터 기록
      try {
        await fetch(`/api/studio/sessions/${sessionId}/upload`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            phase: 'confirm',
            deviceId: device.id,
            durationMs,
            fileSize: blob.size,
            storagePath,
          }),
        });
      } catch {}
    } else {
      try {
        await supabase.from('studio_devices').update({ status: 'error' }).eq('id', device.id);
      } catch {}
    }

    goToResult();
  }, [sessionId, router, getSignedUrl, uploadWithXHR]);

  if (loading) {
    return (
      <div className="min-h-screen bg-black text-white flex items-center justify-center">
        <div className="text-center">
          <div className="w-8 h-8 border-2 border-white border-t-transparent rounded-full animate-spin mx-auto mb-4" />
          <p>세션 로드 중...</p>
        </div>
      </div>
    );
  }

  if (error || !session) {
    return (
      <div className="min-h-screen bg-black text-white flex items-center justify-center">
        <div className="text-center">
          <p className="text-red-400 mb-4">{error || '세션을 찾을 수 없습니다'}</p>
          <button
            onClick={() => router.push('/')}
            className="bg-gray-800 px-6 py-2 rounded-full"
          >
            돌아가기
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="h-screen bg-black text-white flex flex-col">
      {/* 상단 헤더 - 컴팩트 1줄 + 녹화 버튼 */}
      <div className="flex-shrink-0 px-3 py-2 bg-gray-900/80 backdrop-blur-sm safe-area-top">
        <div className="flex items-center justify-between gap-2">
          {/* 왼쪽: 세션 정보 */}
          <div className="flex items-center gap-2 min-w-0">
            <span className="text-xs text-gray-400 font-mono">{session.code}</span>
            <span className="text-xs bg-gray-800 px-2 py-0.5 rounded-full">{devices.length}대</span>
            {isHost
              ? <span className="text-xs bg-purple-600/30 text-purple-300 px-2 py-0.5 rounded-full">호스트 카메라</span>
              : <span className="text-xs bg-blue-600/30 text-blue-300 px-2 py-0.5 rounded-full">서브 카메라</span>
            }
          </div>

          {/* 오른쪽: 녹화 버튼 (호스트) / 상태 (비호스트) */}
          {isHost && !uploading && (
            recordingSignal !== 'start' ? (
              <button
                onClick={handleStartRecording}
                className="flex items-center gap-1.5 bg-red-600 hover:bg-red-500 px-4 py-2 rounded-full text-sm font-semibold transition"
              >
                <div className="w-2.5 h-2.5 bg-white rounded-full" />
                녹화 시작
              </button>
            ) : (
              <button
                onClick={handleStopRecording}
                className="flex items-center gap-1.5 bg-gray-700 hover:bg-gray-600 px-4 py-2 rounded-full text-sm font-semibold transition"
              >
                <div className="w-2.5 h-2.5 bg-red-500 rounded-sm animate-pulse" />
                녹화 종료
              </button>
            )
          )}
          {!isHost && !uploading && recordingSignal === 'idle' && (
            <span className="text-xs text-gray-500">대기 중...</span>
          )}
          {!isHost && !uploading && recordingSignal === 'start' && (
            <button
              onClick={handleGuestStopRecording}
              className="flex items-center gap-1.5 bg-gray-700 hover:bg-gray-600 px-4 py-2 rounded-full text-sm font-semibold transition"
            >
              <div className="w-2.5 h-2.5 bg-red-500 rounded-sm animate-pulse" />
              녹화 종료
            </button>
          )}
        </div>
      </div>

      {/* 카메라 뷰 (전체 화면) */}
      <div className="flex-1 relative">
        {joined && !uploading && (
          <CameraView
            onRecordingComplete={handleRecordingComplete}
            isHost={isHost}
            externalRecordingSignal={recordingSignal}
          />
        )}

        {/* 업로드 중 화면 (카메라 꺼짐) */}
        {uploading && (
          <div className="absolute inset-0 bg-black flex items-center justify-center">
            <div className="text-center space-y-4">
              <div className="w-16 h-16 border-4 border-white/20 border-t-white rounded-full animate-spin mx-auto" />
              <p className="text-lg">영상 업로드 중...</p>
              <div className="w-48 h-2 bg-gray-700 rounded-full mx-auto overflow-hidden">
                <div
                  className="h-full bg-purple-500 rounded-full transition-all duration-300"
                  style={{ width: `${uploadProgress}%` }}
                />
              </div>
              <p className="text-gray-400">
                {uploadProgress}%
                {uploadSize > 0 && (
                  <span className="text-gray-600 ml-2">
                    ({(uploadSize / (1024 * 1024)).toFixed(1)}MB)
                  </span>
                )}
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
