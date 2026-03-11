'use client';

import { useState, useEffect, useCallback, useRef, use } from 'react';
import { useRouter } from 'next/navigation';
import { useStudioSession } from '@/hooks/useStudioSession';
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

  // 외부 시그널 수신 (비호스트)
  useEffect(() => {
    const handleSignal = (e: Event) => {
      const signal = (e as CustomEvent).detail.signal;
      setRecordingSignal(signal);
    };
    window.addEventListener('studio-signal', handleSignal);
    return () => window.removeEventListener('studio-signal', handleSignal);
  }, []);

  // 호스트: 녹화 시작
  const handleStartRecording = useCallback(async () => {
    await sendSignal('start');
    setRecordingSignal('start');
    await updateDeviceStatus('recording');
  }, [sendSignal, updateDeviceStatus]);

  // 호스트: 녹화 종료
  const handleStopRecording = useCallback(async () => {
    await sendSignal('stop');
    setRecordingSignal('stop');
  }, [sendSignal]);

  // 녹화 완료 → 업로드 (ref 사용으로 stale closure 방지)
  const handleRecordingComplete = useCallback(async (blob: Blob, durationMs: number) => {
    const device = myDeviceRef.current;
    if (!device || !sessionId) return;

    setUploading(true);

    // 디바이스 상태를 직접 업데이트 (ref의 최신값 사용)
    try {
      const { supabase } = await import('@/lib/supabase');
      await supabase.from('studio_devices').update({ status: 'uploading' }).eq('id', device.id);
    } catch {}

    try {
      const formData = new FormData();
      formData.append('video', blob, `camera-${device.camera_index}.webm`);
      formData.append('deviceId', device.id);
      formData.append('durationMs', durationMs.toString());

      const xhr = new XMLHttpRequest();
      xhr.open('POST', `/api/studio/sessions/${sessionId}/upload`);

      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) {
          setUploadProgress(Math.round((e.loaded / e.total) * 100));
        }
      };

      xhr.onload = () => {
        setUploading(false);
        router.push(`/studio/${sessionId}/result`);
      };

      xhr.onerror = () => {
        setUploading(false);
        router.push(`/studio/${sessionId}/result`);
      };

      xhr.send(formData);
    } catch {
      setUploading(false);
      router.push(`/studio/${sessionId}/result`);
    }
  }, [sessionId, router]);

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
            onClick={() => router.push('/studio')}
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
            {isHost && <span className="text-xs bg-purple-600/30 text-purple-300 px-2 py-0.5 rounded-full">호스트</span>}
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
          {!isHost && recordingSignal === 'start' && (
            <span className="flex items-center gap-1 text-xs text-red-400">
              <div className="w-2 h-2 bg-red-500 rounded-full animate-pulse" />
              녹화 중
            </span>
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
              <p className="text-gray-400">{uploadProgress}%</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
