'use client';

import { useEffect, useRef } from 'react';
import { useCamera } from '@/hooks/useCamera';

interface CameraViewProps {
  onRecordingComplete: (blob: Blob, durationMs: number) => void;
  isHost: boolean;
  externalRecordingSignal: 'idle' | 'start' | 'stop';
}

export default function CameraView({ onRecordingComplete, isHost, externalRecordingSignal }: CameraViewProps) {
  const {
    videoRef,
    stream,
    isRecording,
    recordingDuration,
    error,
    startCamera,
    stopCamera,
    startRecording,
    stopRecording,
    switchCamera,
  } = useCamera();

  // ref로 최신 값 추적 (stale closure 방지)
  const isRecordingRef = useRef(isRecording);
  const streamRef = useRef(stream);
  const stopRecordingRef = useRef(stopRecording);
  const startRecordingRef = useRef(startRecording);
  const onRecordingCompleteRef = useRef(onRecordingComplete);

  useEffect(() => { isRecordingRef.current = isRecording; }, [isRecording]);
  useEffect(() => { streamRef.current = stream; }, [stream]);
  useEffect(() => { stopRecordingRef.current = stopRecording; }, [stopRecording]);
  useEffect(() => { startRecordingRef.current = startRecording; }, [startRecording]);
  useEffect(() => { onRecordingCompleteRef.current = onRecordingComplete; }, [onRecordingComplete]);

  // 카메라 자동 시작
  useEffect(() => {
    startCamera();
    return () => stopCamera();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 외부 시그널 처리 (호스트 + 비호스트 모두)
  useEffect(() => {
    if (externalRecordingSignal === 'start' && !isRecordingRef.current) {
      // stream이 아직 없으면 잠시 대기 후 재시도
      const tryStart = () => {
        if (streamRef.current) {
          startRecordingRef.current();
        }
      };

      if (streamRef.current) {
        tryStart();
      } else {
        // 카메라 초기화 대기 (최대 3초)
        let attempts = 0;
        const interval = setInterval(() => {
          attempts++;
          if (streamRef.current) {
            clearInterval(interval);
            startRecordingRef.current();
          } else if (attempts >= 15) {
            clearInterval(interval);
          }
        }, 200);
        return () => clearInterval(interval);
      }
    } else if (externalRecordingSignal === 'stop') {
      // stop은 isRecording 체크 없이 항상 시도 (stale closure 방지)
      (async () => {
        const result = await stopRecordingRef.current();
        if (result) {
          onRecordingCompleteRef.current(result.blob, result.durationMs);
        }
      })();
    }
  }, [externalRecordingSignal]);

  const formatTime = (seconds: number) => {
    const m = Math.floor(seconds / 60).toString().padStart(2, '0');
    const s = (seconds % 60).toString().padStart(2, '0');
    return `${m}:${s}`;
  };

  return (
    <div className="relative w-full h-full bg-black">
      {/* 카메라 뷰 */}
      <video
        ref={videoRef}
        autoPlay
        playsInline
        muted
        className="w-full h-full object-cover"
      />

      {/* 에러 표시 */}
      {error && (
        <div className="absolute inset-0 flex items-center justify-center bg-black/80">
          <div className="text-center p-6">
            <p className="text-red-400 mb-4">{error}</p>
            <button
              onClick={startCamera}
              className="bg-white/20 px-6 py-2 rounded-full text-white"
            >
              다시 시도
            </button>
          </div>
        </div>
      )}

      {/* 녹화 중 표시 */}
      {isRecording && (
        <div className="absolute top-4 left-4 flex items-center gap-2 bg-black/60 px-3 py-1.5 rounded-full">
          <div className="w-3 h-3 bg-red-500 rounded-full animate-pulse" />
          <span className="text-white font-mono text-sm">{formatTime(recordingDuration)}</span>
        </div>
      )}

      {/* 카메라 전환 버튼 */}
      {!isRecording && (
        <button
          onClick={switchCamera}
          className="absolute top-4 right-4 bg-black/60 p-3 rounded-full text-white hover:bg-black/80 transition"
          aria-label="카메라 전환"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M11 19H4a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h5" />
            <path d="M13 5h7a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2h-5" />
            <circle cx="12" cy="12" r="3" />
            <path d="m18 22-3-3 3-3" />
            <path d="m6 2 3 3-3 3" />
          </svg>
        </button>
      )}
    </div>
  );
}
