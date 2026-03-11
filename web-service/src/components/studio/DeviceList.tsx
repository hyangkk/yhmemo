'use client';

import type { StudioDevice } from '@/lib/studio';

interface DeviceListProps {
  devices: StudioDevice[];
  myDeviceId: string | null;
}

const STATUS_MAP: Record<string, { label: string; color: string }> = {
  connected: { label: '대기', color: 'bg-green-500' },
  recording: { label: '녹화 중', color: 'bg-red-500 animate-pulse' },
  uploading: { label: '업로드 중', color: 'bg-yellow-500 animate-pulse' },
  done: { label: '완료', color: 'bg-blue-500' },
  error: { label: '오류', color: 'bg-red-700' },
};

export default function DeviceList({ devices, myDeviceId }: DeviceListProps) {
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
              {isMe && <span className="text-purple-300 ml-1">(나)</span>}
            </span>
            <span className="text-gray-400 text-xs">{status.label}</span>
          </div>
        );
      })}
    </div>
  );
}
