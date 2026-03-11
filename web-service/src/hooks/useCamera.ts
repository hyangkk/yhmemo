'use client';

import { useState, useRef, useCallback, useEffect } from 'react';

interface UseCameraOptions {
  facingMode?: 'user' | 'environment';
  width?: number;
  height?: number;
}

interface UseCameraReturn {
  videoRef: React.RefObject<HTMLVideoElement | null>;
  stream: MediaStream | null;
  isRecording: boolean;
  recordedBlob: Blob | null;
  recordingDuration: number;
  error: string | null;
  startCamera: () => Promise<void>;
  stopCamera: () => void;
  startRecording: () => void;
  stopRecording: () => Promise<{ blob: Blob; durationMs: number } | null>;
  switchCamera: () => Promise<void>;
}

export function useCamera(options: UseCameraOptions = {}): UseCameraReturn {
  const { facingMode: initialFacing = 'environment', width = 1920, height = 1080 } = options;

  const videoRef = useRef<HTMLVideoElement | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const startTimeRef = useRef<number>(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const cameraActiveRef = useRef(false);
  const facingModeRef = useRef(initialFacing);

  const [stream, setStream] = useState<MediaStream | null>(null);
  const [isRecording, setIsRecording] = useState(false);
  const [recordedBlob, setRecordedBlob] = useState<Blob | null>(null);
  const [recordingDuration, setRecordingDuration] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [facingMode, setFacingMode] = useState(initialFacing);

  // facingModeRef를 동기화
  useEffect(() => {
    facingModeRef.current = facingMode;
  }, [facingMode]);

  const startCameraWithFacing = useCallback(async (facing: 'user' | 'environment') => {
    try {
      setError(null);
      const constraints: MediaStreamConstraints = {
        video: {
          facingMode: facing,
          width: { ideal: width },
          height: { ideal: height },
        },
        audio: true,
      };

      const mediaStream = await navigator.mediaDevices.getUserMedia(constraints);
      setStream(mediaStream);
      cameraActiveRef.current = true;

      if (videoRef.current) {
        videoRef.current.srcObject = mediaStream;
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : '카메라 접근 실패';
      setError(msg);
    }
  }, [width, height]);

  const startCamera = useCallback(async () => {
    await startCameraWithFacing(facingModeRef.current);
  }, [startCameraWithFacing]);

  const stopCamera = useCallback(() => {
    if (stream) {
      stream.getTracks().forEach(track => track.stop());
      setStream(null);
    }
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
  }, [stream]);

  const startRecording = useCallback(() => {
    if (!stream) return;

    chunksRef.current = [];
    setRecordedBlob(null);

    // WebM이 가장 널리 지원됨, MP4 폴백 (iOS Safari)
    const mimeType = MediaRecorder.isTypeSupported('video/webm;codecs=vp9,opus')
      ? 'video/webm;codecs=vp9,opus'
      : MediaRecorder.isTypeSupported('video/webm')
        ? 'video/webm'
        : 'video/mp4';

    const recorder = new MediaRecorder(stream, { mimeType });

    recorder.ondataavailable = (e) => {
      if (e.data.size > 0) {
        chunksRef.current.push(e.data);
      }
    };

    recorder.start(1000); // 1초마다 chunk 저장
    mediaRecorderRef.current = recorder;
    startTimeRef.current = Date.now();
    setIsRecording(true);

    // 녹화 시간 타이머
    timerRef.current = setInterval(() => {
      setRecordingDuration(Math.floor((Date.now() - startTimeRef.current) / 1000));
    }, 1000);
  }, [stream]);

  const stopRecording = useCallback((): Promise<{ blob: Blob; durationMs: number } | null> => {
    return new Promise((resolve) => {
      const recorder = mediaRecorderRef.current;
      if (!recorder || recorder.state === 'inactive') {
        resolve(null);
        return;
      }

      const durationMs = startTimeRef.current > 0 ? Date.now() - startTimeRef.current : 0;

      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }

      recorder.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType });
        setRecordedBlob(blob);
        setIsRecording(false);
        resolve({ blob, durationMs });
      };

      recorder.stop();
    });
  }, []);

  const switchCamera = useCallback(async () => {
    if (isRecording) return;

    // 현재 스트림 정지
    if (stream) {
      stream.getTracks().forEach(track => track.stop());
      setStream(null);
      if (videoRef.current) {
        videoRef.current.srcObject = null;
      }
    }

    // 새 facingMode로 즉시 카메라 재시작
    const newFacing = facingMode === 'user' ? 'environment' : 'user';
    setFacingMode(newFacing);
    await startCameraWithFacing(newFacing);
  }, [facingMode, stream, isRecording, startCameraWithFacing]);

  // stream ref (클린업용)
  const streamRef = useRef<MediaStream | null>(null);
  useEffect(() => { streamRef.current = stream; }, [stream]);

  // 클린업
  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
      streamRef.current?.getTracks().forEach(track => track.stop());
    };
  }, []);

  return {
    videoRef,
    stream,
    isRecording,
    recordedBlob,
    recordingDuration,
    error,
    startCamera,
    stopCamera,
    startRecording,
    stopRecording,
    switchCamera,
  };
}
