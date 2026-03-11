'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { supabase } from '@/lib/supabase';
import type { StudioSession, StudioDevice } from '@/lib/studio';

interface UseStudioSessionReturn {
  session: StudioSession | null;
  devices: StudioDevice[];
  myDevice: StudioDevice | null;
  isHost: boolean;
  loading: boolean;
  error: string | null;
  joinSession: (sessionId: string) => Promise<StudioDevice | null>;
  sendSignal: (signal: 'start' | 'stop') => Promise<void>;
  updateDeviceStatus: (status: StudioDevice['status']) => Promise<void>;
}

export function useStudioSession(sessionId: string | null): UseStudioSessionReturn {
  const [session, setSession] = useState<StudioSession | null>(null);
  const [devices, setDevices] = useState<StudioDevice[]>([]);
  const [myDevice, setMyDevice] = useState<StudioDevice | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const channelRef = useRef<ReturnType<typeof supabase.channel> | null>(null);

  // 세션 정보 로드
  useEffect(() => {
    if (!sessionId) return;

    const loadSession = async () => {
      setLoading(true);
      const { data, error: err } = await supabase
        .from('studio_sessions')
        .select('*')
        .eq('id', sessionId)
        .single();

      if (err) {
        setError('세션을 찾을 수 없습니다');
        setLoading(false);
        return;
      }

      setSession(data as StudioSession);

      // 디바이스 목록 로드
      const { data: devs } = await supabase
        .from('studio_devices')
        .select('*')
        .eq('session_id', sessionId)
        .order('camera_index');

      setDevices((devs || []) as StudioDevice[]);
      setLoading(false);
    };

    loadSession();
  }, [sessionId]);

  // Realtime 구독
  useEffect(() => {
    if (!sessionId) return;

    const channel = supabase.channel(`studio:${sessionId}`)
      // 세션 상태 변경 감지
      .on('postgres_changes', {
        event: 'UPDATE',
        schema: 'public',
        table: 'studio_sessions',
        filter: `id=eq.${sessionId}`,
      }, (payload) => {
        setSession(prev => prev ? { ...prev, ...payload.new } as StudioSession : null);
      })
      // 디바이스 참여/상태 변경 감지
      .on('postgres_changes', {
        event: '*',
        schema: 'public',
        table: 'studio_devices',
        filter: `session_id=eq.${sessionId}`,
      }, (payload) => {
        if (payload.eventType === 'INSERT') {
          setDevices(prev => [...prev, payload.new as StudioDevice]);
        } else if (payload.eventType === 'UPDATE') {
          setDevices(prev => prev.map(d =>
            d.id === (payload.new as StudioDevice).id ? payload.new as StudioDevice : d
          ));
        } else if (payload.eventType === 'DELETE') {
          setDevices(prev => prev.filter(d => d.id !== (payload.old as StudioDevice).id));
        }
      })
      // 녹화 시작/종료 시그널 (Broadcast)
      .on('broadcast', { event: 'signal' }, (payload) => {
        const signal = payload.payload?.signal as string;
        if (signal === 'start' || signal === 'stop') {
          // 커스텀 이벤트로 전파 (컴포넌트에서 리스닝)
          window.dispatchEvent(new CustomEvent('studio-signal', { detail: { signal } }));
        }
      })
      .subscribe();

    channelRef.current = channel;

    return () => {
      supabase.removeChannel(channel);
    };
  }, [sessionId]);

  const joinSession = useCallback(async (sid: string): Promise<StudioDevice | null> => {
    // 현재 디바이스 수 확인
    const { data: existingDevices } = await supabase
      .from('studio_devices')
      .select('camera_index')
      .eq('session_id', sid)
      .order('camera_index', { ascending: false });

    const nextIndex = existingDevices && existingDevices.length > 0
      ? existingDevices[0].camera_index + 1
      : 0;

    const { data, error: err } = await supabase
      .from('studio_devices')
      .insert({
        session_id: sid,
        name: `카메라 ${nextIndex + 1}`,
        camera_index: nextIndex,
      })
      .select()
      .single();

    if (err) {
      setError('세션 참여 실패');
      return null;
    }

    const device = data as StudioDevice;
    setMyDevice(device);

    // 첫 번째 참여자가 호스트
    if (nextIndex === 0) {
      await supabase
        .from('studio_sessions')
        .update({ host_device_id: device.id })
        .eq('id', sid);
    }

    return device;
  }, []);

  const sendSignal = useCallback(async (signal: 'start' | 'stop') => {
    if (!channelRef.current) return;
    channelRef.current.send({
      type: 'broadcast',
      event: 'signal',
      payload: { signal, timestamp: Date.now() },
    });

    // 세션 상태도 업데이트
    if (sessionId) {
      const newStatus = signal === 'start' ? 'recording' : 'uploading';
      await supabase
        .from('studio_sessions')
        .update({ status: newStatus, updated_at: new Date().toISOString() })
        .eq('id', sessionId);
    }
  }, [sessionId]);

  const updateDeviceStatus = useCallback(async (status: StudioDevice['status']) => {
    if (!myDevice) return;
    await supabase
      .from('studio_devices')
      .update({ status })
      .eq('id', myDevice.id);
    setMyDevice(prev => prev ? { ...prev, status } : null);
  }, [myDevice]);

  const isHost = !!(session && myDevice && session.host_device_id === myDevice.id);

  return {
    session,
    devices,
    myDevice,
    isHost,
    loading,
    error,
    joinSession,
    sendSignal,
    updateDeviceStatus,
  };
}
