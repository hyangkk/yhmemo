"use client";

interface NewsItem {
  id?: string;
  title: string;
  url: string;
  source: string;
  content?: string;
  created_at?: string;
  ai_summary?: string;
  relevance_score?: number;
}

export default function NewsCard({
  item,
  curated,
}: {
  item: NewsItem;
  curated?: boolean;
}) {
  const timeAgo = item.created_at
    ? getTimeAgo(new Date(item.created_at))
    : "";

  return (
    <article className="group relative rounded-xl border border-gray-200 bg-white p-5 transition-all hover:shadow-lg hover:border-blue-300 dark:bg-gray-900 dark:border-gray-700 dark:hover:border-blue-600">
      {curated && (
        <span className="absolute -top-2 -right-2 bg-gradient-to-r from-blue-500 to-purple-600 text-white text-xs font-bold px-2 py-0.5 rounded-full">
          AI Pick
        </span>
      )}

      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <a
            href={item.url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-lg font-semibold text-gray-900 dark:text-gray-100 hover:text-blue-600 dark:hover:text-blue-400 line-clamp-2 transition-colors"
          >
            {item.title}
          </a>

          <div className="flex items-center gap-2 mt-2 text-sm text-gray-500 dark:text-gray-400">
            <span className="inline-flex items-center px-2 py-0.5 rounded-md bg-gray-100 dark:bg-gray-800 font-medium">
              {item.source}
            </span>
            {timeAgo && <span>{timeAgo}</span>}
            {item.relevance_score && (
              <span className="text-blue-500 font-medium">
                {Math.round(item.relevance_score * 100)}% 관련
              </span>
            )}
          </div>
        </div>
      </div>

      {item.ai_summary && (
        <div className="mt-3 p-3 rounded-lg bg-blue-50 dark:bg-blue-900/20 border border-blue-100 dark:border-blue-800">
          <p className="text-sm text-blue-800 dark:text-blue-200 leading-relaxed">
            <span className="font-semibold">AI 요약:</span> {item.ai_summary}
          </p>
        </div>
      )}

      {item.content && !item.ai_summary && (
        <p className="mt-3 text-sm text-gray-600 dark:text-gray-300 line-clamp-2 leading-relaxed">
          {item.content}
        </p>
      )}
    </article>
  );
}

function getTimeAgo(date: Date): string {
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMin = Math.floor(diffMs / 60000);

  if (diffMin < 1) return "방금";
  if (diffMin < 60) return `${diffMin}분 전`;

  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}시간 전`;

  const diffDay = Math.floor(diffHr / 24);
  if (diffDay < 7) return `${diffDay}일 전`;

  return date.toLocaleDateString("ko-KR");
}
