'use client';

import { useState, useEffect, use, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/lib/auth';
import type { Project, ProjectMember, ProjectClip, ProjectResult } from '@/lib/project';

const MODE_LABELS: Record<string, string> = {
  auto: '교차편집',
  director: 'AI 감독 모드',
  timeline: '타임라인 편집',
  prompt: 'AI 프롬프트',
};

function formatRelativeTime(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return '방금 전';
  if (minutes < 60) return `${minutes}분 전`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}시간 전`;
  return `${Math.floor(hours / 24)}일 전`;
}

function formatDuration(ms: number | null) {
  if (!ms) return '--:--';
  const s = Math.floor(ms / 1000);
  const m = Math.floor(s / 60);
  return `${m}:${(s % 60).toString().padStart(2, '0')}`;
}

function formatSize(bytes: number | null) {
  if (!bytes) return '-';
  if (bytes > 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
  return `${(bytes / 1024).toFixed(1)}KB`;
}

function formatDateTime(dateStr: string): string {
  const d = new Date(dateStr);
  const month = d.getMonth() + 1;
  const day = d.getDate();
  const hours = d.getHours().toString().padStart(2, '0');
  const mins = d.getMinutes().toString().padStart(2, '0');
  return `${month}/${day} ${hours}:${mins}`;
}

interface ProjectData {
  project: Project;
  members: ProjectMember[];
  clips: ProjectClip[];
  results: ProjectResult[];
}

export default function ProjectDashboardPage({ params }: { params: Promise<{ id: string }> }) {
  const { id: projectId } = use(params);
  const { user } = useAuth();
  const router = useRouter();
  const [data, setData] = useState<ProjectData | null>(null);
  const [loading, setLoading] = useState(true);
  const [editingMode, setEditingMode] = useState<string | null>(null);
  const [selectedMode, setSelectedMode] = useState('auto');
  const [selectedBgm, setSelectedBgm] = useState<string | null>(null);
  const [selectedSubtitle, setSelectedSubtitle] = useState<string | null>(null);
  const [audioMode, setAudioMode] = useState<'each' | 'best'>('each');
  const [promptText, setPromptText] = useState('');
  const [pollKey, setPollKey] = useState(0);

  const loadData = useCallback(async () => {
    const res = await fetch(`/api/projects/${projectId}?_t=${Date.now()}`);
    if (res.ok) setData(await res.json());
    setLoading(false);
  }, [projectId]);

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 5000);
    return () => clearInterval(interval);
  }, [loadData, pollKey]);

  const requestEdit = async (mode: string, prompt?: string) => {
    setEditingMode(mode);
    try {
      const body: Record<string, string> = { mode, audio_mode: audioMode };
      if (prompt) body.prompt = prompt;
      const res = await fetch(`/api/projects/${projectId}/edit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (res.ok) {
        setPollKey(k => k + 1);
      }
    } finally {
      setEditingMode(null);
    }
  };

  if (loading || !data) {
    return (
      <div className="min-h-screen bg-black text-white flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-white border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  const { project, members, clips, results } = data;
  const isOwner = user?.id === project.owner_id;
  const doneResults = results.filter(r => r.status === 'done');
  const processingResult = results.find(r => r.status === 'processing');

  // 멤버별 클립 그룹핑
  const clipsByMember = new Map<string, ProjectClip[]>();
  clips.forEach(c => {
    const arr = clipsByMember.get(c.member_id) || [];
    arr.push(c);
    clipsByMember.set(c.member_id, arr);
  });

  // 타임라인 범위
  const timeRange = clips.length > 0 ? {
    start: new Date(Math.min(...clips.map(c => new Date(c.started_at).getTime()))),
    end: new Date(Math.max(...clips.map(c => {
      const s = new Date(c.started_at).getTime();
      return c.ended_at ? new Date(c.ended_at).getTime() : s + (c.duration_ms || 0);
    }))),
  } : null;

  return (
    <div className="min-h-screen bg-black text-white">
      {/* 헤더 */}
      <div className="px-4 py-2.5 bg-gray-900 border-b border-gray-800">
        <div className="max-w-2xl mx-auto flex items-center gap-3">
          <button onClick={() => router.push('/projects')} className="text-gray-400 hover:text-white text-sm">←</button>
          <div className="flex-1 min-w-0">
            <h1 className="text-lg font-bold truncate">{project.title}</h1>
            <div className="flex items-center gap-2">
              <span className="text-xs text-gray-500 font-mono">{project.code}</span>
              <span className="text-xs text-gray-600">{members.length}명 · {clips.length}클립</span>
            </div>
          </div>
          <button
            onClick={() => router.push(`/projects/${projectId}/record`)}
            className="bg-red-600 hover:bg-red-500 px-4 py-2 rounded-full text-sm font-semibold transition flex items-center gap-1.5"
          >
            <div className="w-2 h-2 bg-white rounded-full" />
            촬영
          </button>
        </div>
      </div>

      <div className="max-w-2xl mx-auto p-3 space-y-3">
        {/* 편집 중 상태 */}
        {processingResult && (
          <div className="bg-purple-900/30 border border-purple-500/30 rounded-xl p-3">
            <div className="flex items-center gap-3">
              <div className="w-6 h-6 border-2 border-purple-500/30 border-t-purple-500 rounded-full animate-spin shrink-0" />
              <p className="text-sm font-medium">영상 편집 중...</p>
            </div>
          </div>
        )}

        {/* 편집 결과 */}
        {doneResults.length > 0 && (
          <div className="space-y-2">
            <h2 className="text-sm font-semibold text-gray-400">
              편집 결과 <span className="text-gray-600 font-normal">{doneResults.length}개</span>
            </h2>
            {doneResults.slice(0, 5).map((result, idx) => {
              const isLatest = idx === 0;
              const modeLabel = result.edit_mode ? MODE_LABELS[result.edit_mode] || result.edit_mode : '편집';
              return (
                <div
                  key={result.id}
                  className={`rounded-xl p-3 ${
                    isLatest
                      ? 'bg-green-900/40 border-2 border-green-500/50'
                      : 'bg-gray-900/60 border border-gray-700/50'
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <span className="text-lg">{isLatest ? '✅' : '🎬'}</span>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <p className="text-sm font-medium">{modeLabel}</p>
                        {isLatest && (
                          <span className="text-[10px] font-bold bg-green-500 text-black px-1.5 py-0.5 rounded">최신</span>
                        )}
                      </div>
                      <p className="text-xs text-gray-500">
                        {formatDuration(result.duration_ms)} · {formatRelativeTime(result.created_at)}
                      </p>
                    </div>
                    <a
                      href={`${process.env.NEXT_PUBLIC_SUPABASE_URL}/storage/v1/object/public/studio-clips/${result.storage_path}`}
                      download
                      className={`px-4 py-1.5 rounded-lg text-sm font-semibold transition ${
                        isLatest ? 'bg-green-600 hover:bg-green-500' : 'bg-gray-700 hover:bg-gray-600'
                      }`}
                    >
                      다운로드
                    </a>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* 멤버별 클립 타임라인 */}
        <div>
          <h2 className="text-sm font-semibold text-gray-400 mb-2">
            타임라인
            {timeRange && (
              <span className="text-gray-600 font-normal ml-2">
                {formatDateTime(timeRange.start.toISOString())} ~ {formatDateTime(timeRange.end.toISOString())}
              </span>
            )}
          </h2>

          {members.map((member) => {
            const memberClips = clipsByMember.get(member.id) || [];
            const totalDuration = memberClips.reduce((sum, c) => sum + (c.duration_ms || 0), 0);
            return (
              <div key={member.id} className="mb-2">
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-xs font-medium text-gray-300">{member.name}</span>
                  <span className="text-xs text-gray-600">
                    {memberClips.length}클립 · {formatDuration(totalDuration)}
                  </span>
                </div>
                {/* 타임라인 바 */}
                {timeRange && memberClips.length > 0 && (
                  <div className="relative h-6 bg-gray-900 rounded-lg overflow-hidden">
                    {memberClips.map((clip) => {
                      const totalMs = timeRange.end.getTime() - timeRange.start.getTime();
                      if (totalMs <= 0) return null;
                      const left = ((new Date(clip.started_at).getTime() - timeRange.start.getTime()) / totalMs) * 100;
                      const width = Math.max(1, ((clip.duration_ms || 1000) / totalMs) * 100);
                      return (
                        <div
                          key={clip.id}
                          className="absolute top-0.5 bottom-0.5 bg-purple-500/60 rounded"
                          style={{ left: `${Math.max(0, left)}%`, width: `${Math.min(width, 100 - left)}%` }}
                          title={`${formatDateTime(clip.started_at)} · ${formatDuration(clip.duration_ms)}`}
                        />
                      );
                    })}
                  </div>
                )}
                {memberClips.length === 0 && (
                  <p className="text-xs text-gray-600">클립 없음</p>
                )}
              </div>
            );
          })}
        </div>

        {/* 클립 목록 (시간순) */}
        <div>
          <h2 className="text-sm font-semibold text-gray-400 mb-1.5">클립 목록 (시간순)</h2>
          <div className="space-y-1">
            {clips.map((clip) => {
              const member = members.find(m => m.id === clip.member_id);
              return (
                <div key={clip.id} className="flex items-center gap-3 px-3 py-2 rounded-lg bg-gray-900">
                  <span className="text-base">🎥</span>
                  <div className="flex-1 min-w-0">
                    <span className="text-sm font-medium">{member?.name || '참여자'}</span>
                    <span className="text-xs text-gray-500 ml-2">
                      {formatDateTime(clip.started_at)}
                    </span>
                  </div>
                  <span className="text-xs text-gray-500">
                    {formatDuration(clip.duration_ms)} · {formatSize(clip.file_size)}
                  </span>
                  <a
                    href={`${process.env.NEXT_PUBLIC_SUPABASE_URL}/storage/v1/object/public/studio-clips/${clip.storage_path}`}
                    download
                    className="text-blue-400 hover:text-blue-300 text-xs"
                  >
                    저장
                  </a>
                </div>
              );
            })}
            {clips.length === 0 && (
              <p className="text-center text-gray-600 text-sm py-4">아직 클립이 없어요. 촬영 버튼을 눌러 시작하세요!</p>
            )}
          </div>
        </div>

        {/* 편집 설정 패널 */}
        {clips.length >= 1 && !processingResult && (
          <div className="bg-gray-900 border border-gray-700 rounded-xl overflow-hidden">
            <div className="px-3 py-2 border-b border-gray-800">
              <span className="text-sm font-semibold text-gray-300">편집 설정</span>
              {user?.plan === 'free' && (
                <span className="text-xs text-yellow-500 ml-2">일부 기능은 Pro 결제 필요</span>
              )}
            </div>
            <div className="p-3 space-y-3">
              {/* 편집 모드 */}
              <div>
                <h3 className="text-xs font-semibold text-gray-500 mb-1.5">편집 모드</h3>
                <div className="grid grid-cols-2 gap-1.5">
                  {[
                    { key: 'auto', label: '🔄 교차편집', desc: '카메라 자동 전환', free: true },
                    { key: 'director', label: '🎬 감독 모드', desc: '메인 + 리액션 컷', free: false },
                  ].map(({ key, label, desc, free }) => (
                    <button
                      key={key}
                      onClick={() => setSelectedMode(key)}
                      className={`p-2 rounded-lg text-left transition border ${
                        selectedMode === key
                          ? 'bg-purple-900/40 border-purple-500/50'
                          : 'bg-gray-800 border-gray-700 hover:bg-gray-750'
                      }`}
                    >
                      <p className="text-sm font-semibold">{label}</p>
                      <p className="text-[11px] text-gray-400">
                        {desc}
                        {!free && user?.plan === 'free' && ' (Pro)'}
                      </p>
                    </button>
                  ))}
                </div>
              </div>

              {/* BGM */}
              <div>
                <h3 className="text-xs font-semibold text-gray-500 mb-1.5">배경음악</h3>
                <div className="flex gap-1.5 flex-wrap">
                  {[
                    { key: null, label: '없음' },
                    { key: 'calm', label: '🎵 잔잔한' },
                    { key: 'upbeat', label: '🎶 신나는' },
                  ].map(({ key, label }) => (
                    <button
                      key={key || 'none'}
                      onClick={() => setSelectedBgm(key)}
                      className={`px-3 py-1.5 rounded-lg text-sm transition border ${
                        selectedBgm === key
                          ? 'bg-teal-900/50 border-teal-500/60 text-teal-300'
                          : 'bg-gray-800/50 border-gray-700 text-gray-400 hover:bg-gray-800'
                      }`}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>

              {/* 자막 */}
              <div>
                <h3 className="text-xs font-semibold text-gray-500 mb-1.5">자막</h3>
                <div className="flex gap-1.5 flex-wrap">
                  {[
                    { key: null, label: '없음' },
                    { key: 'blackBg', label: '검은 배경' },
                    { key: 'outline', label: '테두리' },
                  ].map(({ key, label }) => (
                    <button
                      key={key || 'none'}
                      onClick={() => setSelectedSubtitle(key)}
                      className={`px-3 py-1.5 rounded-lg text-sm transition border ${
                        selectedSubtitle === key
                          ? 'bg-yellow-900/50 border-yellow-500/60 text-yellow-300'
                          : 'bg-gray-800/50 border-gray-700 text-gray-400 hover:bg-gray-800'
                      }`}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>

              {/* 음성 */}
              <div>
                <h3 className="text-xs font-semibold text-gray-500 mb-1.5">음성</h3>
                <div className="flex gap-1.5">
                  <button
                    onClick={() => setAudioMode('each')}
                    className={`px-3 py-1.5 rounded-lg text-sm transition border ${
                      audioMode === 'each'
                        ? 'bg-blue-900/40 border-blue-500/50 text-blue-300'
                        : 'bg-gray-800/50 border-gray-700 text-gray-400'
                    }`}
                  >
                    🎙️ 각 영상 음성
                  </button>
                  <button
                    onClick={() => setAudioMode('best')}
                    className={`px-3 py-1.5 rounded-lg text-sm transition border ${
                      audioMode === 'best'
                        ? 'bg-blue-900/40 border-blue-500/50 text-blue-300'
                        : 'bg-gray-800/50 border-gray-700 text-gray-400'
                    }`}
                  >
                    🔊 최적 음성만
                  </button>
                </div>
              </div>

              {/* 추가 지시사항 */}
              <div>
                <h3 className="text-xs font-semibold text-gray-500 mb-1.5">추가 지시사항 <span className="text-gray-600 font-normal">(선택)</span></h3>
                <input
                  type="text"
                  value={promptText}
                  onChange={(e) => setPromptText(e.target.value)}
                  placeholder="예: 하이라이트 위주로 2분짜리로 만들어줘"
                  className="w-full bg-gray-800 text-white text-sm rounded-lg px-3 py-2 outline-none placeholder-gray-500 border border-gray-700 focus:border-purple-500/50 transition"
                />
              </div>

              {/* 편집 버튼 */}
              <button
                disabled={!!editingMode || !!processingResult}
                onClick={() => {
                  const bgmMap: Record<string, string> = {
                    calm: '잔잔한 배경음악 넣어줘',
                    upbeat: '신나는 배경음악 넣어줘',
                  };
                  const subtitleMap: Record<string, string> = {
                    blackBg: '자동 자막. 스타일: 검은 배경',
                    outline: '자동 자막. 스타일: 테두리',
                  };
                  const modeMap: Record<string, string> = { auto: '교차편집', director: '감독 모드' };

                  const hasBgm = selectedBgm && bgmMap[selectedBgm];
                  const hasSubtitle = selectedSubtitle && subtitleMap[selectedSubtitle];
                  const hasPrompt = promptText.trim();

                  if (hasBgm || hasSubtitle || hasPrompt) {
                    const parts: string[] = [modeMap[selectedMode] || '교차편집'];
                    if (hasBgm) parts.push(bgmMap[selectedBgm!]);
                    if (hasSubtitle) parts.push(subtitleMap[selectedSubtitle!]);
                    if (hasPrompt) parts.push(promptText.trim());
                    requestEdit('prompt', parts.join(', '));
                  } else {
                    requestEdit(selectedMode);
                  }
                }}
                className="w-full bg-purple-600 hover:bg-purple-500 disabled:bg-gray-700 disabled:text-gray-500 py-3 rounded-xl text-sm font-bold transition"
              >
                {editingMode ? '편집 준비 중...' : `편집하기 (${clips.length}클립)`}
              </button>

              {/* Plus 업그레이드 버튼 */}
              {user?.plan === 'free' && isOwner && (
                <button
                  onClick={() => router.push('/pricing')}
                  className="w-full bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-500 hover:to-indigo-500 py-2.5 rounded-xl text-sm font-semibold transition"
                >
                  Plus 업그레이드 ($9/월) — 모든 기능 해금
                </button>
              )}
            </div>
          </div>
        )}

        {/* 멤버 초대 */}
        <div className="bg-gray-900 rounded-xl p-3">
          <h3 className="text-xs font-semibold text-gray-500 mb-2">멤버 초대</h3>
          <div className="flex items-center gap-2">
            <div className="flex-1 bg-gray-800 rounded-lg px-3 py-2 text-center">
              <span className="text-lg font-mono font-bold tracking-[0.2em]">{project.code}</span>
            </div>
            <button
              onClick={() => {
                navigator.clipboard.writeText(project.code);
              }}
              className="bg-gray-700 hover:bg-gray-600 px-3 py-2 rounded-lg text-sm transition"
            >
              복사
            </button>
          </div>
          <p className="text-xs text-gray-600 mt-1.5">이 코드를 공유하면 누구나 참여할 수 있어요</p>
        </div>
      </div>
    </div>
  );
}
