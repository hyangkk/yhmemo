'use client';

import type { StudioDevice } from '@/lib/studio';
import { useLang } from '@/lib/i18n';

interface DeviceListProps {
  devices: StudioDevice[];
  myDeviceId: string | null;
}

const STATUS_MAP: Record<string, { label: { ko: string; en: string }; color: string }> = {
  connected: { label: { ko: '대기', en: 'Ready' }, color: 'bg-green-500' },
  recording: { label: { ko: '녹화 중', en: 'Recording' }, color: 'bg-red-500 animate-pulse' },
  uploading: { label: { ko: '업로드 중', en: 'Uploading' }, color: 'bg-yellow-500 animate-pulse' },
  done: { label: { ko: '완료', en: 'Done' }, color: 'bg-blue-500' },
  error: { label: { ko: '오류', en: 'Error' }, color: 'bg-red-700' },
};

export default function DeviceList({ devices, myDeviceId }: DeviceListProps) {
  const { lang } = useLang();

  return (
    <div className="flex gap-2 overflow-x-auto pb-1">
      {devices.map((device) => {
        const status = STATUS_MAP[device.status] || STATUS_MAP.connected;
        const isMe = device.id === myDeviceId;

        return (
          <div
            key={device.id}
            className={`flex-shrink-0 flex items-center gap-2 px-3 py-2 rounded-full text-sm ${
              isMe ? 'bg-purple-600/30 border border-purple-500' : 'bg-gray-800'
            }`}
          >
            <div className={`w-2 h-2 rounded-full ${status.color}`} />
            <span className="text-white">
              {device.name}
              {isMe && <span className="text-purple-300 ml-1">{lang === 'ko' ? '(나)' : '(me)'}</span>}
            </span>
            <span className="text-gray-400 text-xs">{status.label[lang]}</span>
          </div>
        );
      })}
    </div>
  );
}
