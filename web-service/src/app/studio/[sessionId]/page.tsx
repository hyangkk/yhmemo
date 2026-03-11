'use client';

import { useState, useEffect, useCallback, use } from 'react';
import { useRouter } from 'next/navigation';
import { useStudioSession } from '@/hooks/useStudioSession';
import CameraView from '@/components/studio/CameraView';
import DeviceList from '@/components/studio/DeviceList';

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

  // 세션에 자동 참여
  useEffect(() => {
    if (sessionId && !joined && !loading && session) {
      joinSession(sessionId).then((device) => {
        if (device) setJoined(true);
      });
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

  // 녹화 완료 → 업로드
  const handleRecordingComplete = useCallback(async (blob: Blob, durationMs: number) => {
    if (!myDevice || !sessionId) return;

    setUploading(true);
    await updateDeviceStatus('uploading');

    try {
      const formData = new FormData();
      formData.append('video', blob, `camera-${myDevice.camera_index}.webm`);
      formData.append('deviceId', myDevice.id);
      formData.append('durationMs', durationMs.toString());

      const xhr = new XMLHttpRequest();
      xhr.open('POST', `/api/studio/sessions/${sessionId}/upload`);

      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) {
          setUploadProgress(Math.round((e.loaded / e.total) * 100));
        }
      };

      xhr.onload = async () => {
        if (xhr.status === 200) {
          await updateDeviceStatus('done');
          setUploading(false);
          // 업로드 완료 후 결과 페이지로 이동 (호스트, 비호스트 모두)
          router.push(`/studio/${sessionId}/result`);
        } else {
          await updateDeviceStatus('error');
          setUploading(false);
        }
      };

      xhr.onerror = async () => {
        await updateDeviceStatus('error');
        setUploading(false);
      };

      xhr.send(formData);
    } catch {
      await updateDeviceStatus('error');
      setUploading(false);
    }
  }, [myDevice, sessionId, updateDeviceStatus, router]);

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
      {/* 상단 헤더 */}
      <div className="flex-shrink-0 px-4 py-3 bg-gray-900/80 backdrop-blur-sm space-y-2 safe-area-top">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="font-semibold">{session.title}</h1>
            <p className="text-gray-400 text-xs">참여 코드: <span className="font-mono text-white">{session.code}</span></p>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs bg-gray-800 px-2 py-1 rounded-full">
              {devices.length}대 연결
            </span>
            {isHost && (
              <span className="text-xs bg-purple-600/30 text-purple-300 px-2 py-1 rounded-full">
                호스트
              </span>
            )}
          </div>
        </div>

        {/* 디바이스 목록 */}
        <DeviceList devices={devices} myDeviceId={myDevice?.id || null} />
      </div>

      {/* 카메라 뷰 (전체 화면) */}
      <div className="flex-1 relative">
        {joined && (
          <CameraView
            onRecordingComplete={handleRecordingComplete}
            isHost={isHost}
            externalRecordingSignal={recordingSignal}
          />
        )}

        {/* 플로팅 녹화 컨트롤 (호스트) */}
        {isHost && !uploading && (
          <div className="absolute bottom-6 left-0 right-0 flex justify-center z-10">
            {recordingSignal !== 'start' ? (
              <button
                onClick={handleStartRecording}
                className="flex items-center gap-2 bg-red-600 hover:bg-red-500 px-6 py-3 rounded-full font-semibold shadow-lg shadow-red-600/30 transition"
              >
                <div className="w-3 h-3 bg-white rounded-full" />
                녹화 시작
              </button>
            ) : (
              <button
                onClick={handleStopRecording}
                className="flex items-center gap-2 bg-gray-800/90 hover:bg-gray-700 px-6 py-3 rounded-full font-semibold shadow-lg transition"
              >
                <div className="w-3 h-3 bg-red-500 rounded-sm animate-pulse" />
                녹화 종료
              </button>
            )}
          </div>
        )}

        {/* 비호스트: 대기 플로팅 */}
        {!isHost && !uploading && recordingSignal === 'idle' && (
          <div className="absolute bottom-6 left-0 right-0 flex justify-center z-10">
            <div className="bg-gray-800/80 px-5 py-2.5 rounded-full text-gray-400 text-sm backdrop-blur-sm">
              호스트가 녹화를 시작할 때까지 대기 중...
            </div>
          </div>
        )}

        {/* 업로드 중 오버레이 */}
        {uploading && (
          <div className="absolute inset-0 bg-black/80 flex items-center justify-center z-10">
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
