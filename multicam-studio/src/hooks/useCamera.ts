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

// 모바일 기기 감지
function isMobileDevice(): boolean {
  if (typeof navigator === 'undefined') return false;
  return /iPhone|iPad|iPod|Android/i.test(navigator.userAgent);
}

export function useCamera(options: UseCameraOptions = {}): UseCameraReturn {
  const mobile = isMobileDevice();
  const { facingMode: initialFacing = 'environment', width = mobile ? 1280 : 1920, height = mobile ? 720 : 1080 } = options;

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

  // stream ref (stale closure 방지 - startRecording/stopCamera에서 사용)
  const streamRef = useRef<MediaStream | null>(null);
  useEffect(() => { streamRef.current = stream; }, [stream]);

  // facingModeRef를 동기화
  useEffect(() => {
    facingModeRef.current = facingMode;
  }, [facingMode]);

  const startCameraWithFacing = useCallback(async (facing: 'user' | 'environment') => {
    try {
      setError(null);

      // 오디오: 에코캔슬/노이즈억제 비활성화 (원본 품질 보존, 편집 시 처리)
      const audioConstraints: MediaTrackConstraints = {
        echoCancellation: false,
        noiseSuppression: false,
        autoGainControl: true,
        sampleRate: { ideal: 48000 },
      };

      // 고해상도 → 저해상도 → 최소 순으로 시도
      const constraintsList: MediaStreamConstraints[] = [
        { video: { facingMode: facing, width: { ideal: width }, height: { ideal: height }, frameRate: { ideal: 30 } }, audio: audioConstraints },
        { video: { facingMode: facing, width: { ideal: 1280 }, height: { ideal: 720 } }, audio: audioConstraints },
        { video: { facingMode: facing }, audio: true },
        { video: true, audio: true },
      ];

      let mediaStream: MediaStream | null = null;
      for (const constraints of constraintsList) {
        try {
          mediaStream = await navigator.mediaDevices.getUserMedia(constraints);
          break;
        } catch {
          continue;
        }
      }

      if (!mediaStream) throw new Error('카메라를 시작할 수 없습니다');

      setStream(mediaStream);
      streamRef.current = mediaStream; // useEffect 대기 없이 즉시 업데이트
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
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(track => track.stop());
      setStream(null);
    }
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
  }, []);

  const startRecording = useCallback(() => {
    // ref를 사용하여 항상 최신 stream 참조 (stale closure 방지)
    const currentStream = streamRef.current;
    if (!currentStream) return;

    chunksRef.current = [];
    setRecordedBlob(null);

    // 브라우저/기기별 MIME 타입 호환성 (우선순위 순)
    const mimeTypes = [
      'video/webm;codecs=vp9,opus',   // Chrome, Edge (고품질)
      'video/webm;codecs=vp8,opus',   // 구형 안드로이드 Chrome
      'video/webm;codecs=h264,opus',  // 일부 안드로이드
      'video/webm',                    // WebM 기본
      'video/mp4',                     // iOS Safari, 일부 브라우저
    ];
    const mimeType = mimeTypes.find(t => MediaRecorder.isTypeSupported(t)) || '';

    // 비트레이트: 고 → 중 → 저 순으로 시도 (기기 인코더 한계 대응)
    const bitrates = mobile ? [8_000_000, 4_000_000, 2_000_000] : [12_000_000, 8_000_000, 4_000_000];
    let recorder: MediaRecorder | null = null;

    for (const bps of bitrates) {
      try {
        const opts: MediaRecorderOptions = { videoBitsPerSecond: bps };
        if (mimeType) opts.mimeType = mimeType;
        recorder = new MediaRecorder(currentStream, opts);
        break;
      } catch {
        continue;
      }
    }

    // 모든 옵션 실패 시 기본값으로 시도
    if (!recorder) {
      try {
        recorder = new MediaRecorder(currentStream);
      } catch (err) {
        setError('녹화를 시작할 수 없습니다: ' + (err instanceof Error ? err.message : ''));
        return;
      }
    }

    recorder.ondataavailable = (e) => {
      if (e.data.size > 0) {
        chunksRef.current.push(e.data);
      }
    };

    recorder.onerror = () => {
      // 녹화 중 에러 시 현재까지 데이터로 복구 시도
      console.warn('[studio] MediaRecorder 에러 발생, 현재까지 데이터 저장');
    };

    recorder.start(1000); // 1초마다 chunk 저장
    mediaRecorderRef.current = recorder;
    startTimeRef.current = Date.now();
    setIsRecording(true);

    // 녹화 시간 타이머
    timerRef.current = setInterval(() => {
      setRecordingDuration(Math.floor((Date.now() - startTimeRef.current) / 1000));
    }, 1000);
  }, []);

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
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(track => track.stop());
      setStream(null);
      if (videoRef.current) {
        videoRef.current.srcObject = null;
      }
    }

    // 새 facingMode로 즉시 카메라 재시작
    const newFacing = facingModeRef.current === 'user' ? 'environment' : 'user';
    setFacingMode(newFacing);
    await startCameraWithFacing(newFacing);
  }, [isRecording, startCameraWithFacing]);

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
