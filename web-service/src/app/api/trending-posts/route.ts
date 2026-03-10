import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

interface RedditPost {
  title: string;
  url: string;
  permalink: string;
  score: number;
  num_comments: number;
  subreddit: string;
  created_utc: number;
  link_flair_text?: string;
  selftext?: string;
  thumbnail?: string;
  is_self: boolean;
}

interface TrendingPost {
  title: string;
  url: string;
  score: number;
  comments: number;
  source: string;
  sourceIcon: string;
  sourceColor: string;
  createdAt: string;
  flair?: string;
  snippet?: string;
}

// Reddit 공개 JSON API로 인기 글 가져오기
async function fetchRedditHot(subreddit: string, limit = 5): Promise<TrendingPost[]> {
  try {
    const res = await fetch(
      `https://www.reddit.com/r/${subreddit}/hot.json?limit=${limit}&raw_json=1`,
      {
        headers: { "User-Agent": "YHMemo/1.0" },
        next: { revalidate: 600 }, // 10분 캐시
      }
    );
    if (!res.ok) return [];
    const data = await res.json();
    const posts: TrendingPost[] = (data?.data?.children || [])
      .filter((c: { data: RedditPost }) => !c.data.is_self || c.data.score > 50)
      .map((c: { data: RedditPost }) => {
        const d = c.data;
        return {
          title: d.title,
          url: d.is_self
            ? `https://reddit.com${d.permalink}`
            : d.url,
          score: d.score,
          comments: d.num_comments,
          source: `r/${subreddit}`,
          sourceIcon: "🔴",
          sourceColor: "orange",
          createdAt: new Date(d.created_utc * 1000).toISOString(),
          flair: d.link_flair_text || undefined,
          snippet: d.selftext ? d.selftext.slice(0, 120) : undefined,
        };
      });
    return posts;
  } catch (e) {
    console.error(`Reddit r/${subreddit} fetch error:`, e);
    return [];
  }
}

// CryptoPanic 공개 필터 (인증 불필요한 public endpoint)
async function fetchCryptoPanic(): Promise<TrendingPost[]> {
  try {
    const res = await fetch(
      "https://cryptopanic.com/api/free/v1/posts/?auth_token=free&filter=hot&public=true",
      { next: { revalidate: 600 } }
    );
    if (!res.ok) return [];
    const data = await res.json();
    return (data?.results || []).slice(0, 5).map(
      (p: { title: string; url: string; votes: { positive: number; negative: number; comments: number }; published_at: string; source: { title: string } }) => ({
        title: p.title,
        url: p.url,
        score: (p.votes?.positive || 0) - (p.votes?.negative || 0),
        comments: p.votes?.comments || 0,
        source: `CryptoPanic`,
        sourceIcon: "⚡",
        sourceColor: "blue",
        createdAt: p.published_at,
      })
    );
  } catch {
    return [];
  }
}

export async function GET() {
  try {
    // 여러 서브레딧에서 병렬 fetch
    const subreddits = ["cryptocurrency", "wallstreetbets", "investing", "stocks"];
    const [redditResults, cryptoPanicResults] = await Promise.all([
      Promise.all(subreddits.map((sub) => fetchRedditHot(sub, 5))),
      fetchCryptoPanic(),
    ]);

    // Reddit 결과 합치기
    const allReddit = redditResults.flat();

    // 중복 제거 (같은 제목)
    const seen = new Set<string>();
    const deduplicated = [...allReddit, ...cryptoPanicResults].filter((p) => {
      const key = p.title.toLowerCase().slice(0, 50);
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });

    // score 기준 정렬 후 상위 15개
    const sorted = deduplicated
      .sort((a, b) => b.score - a.score)
      .slice(0, 15);

    return NextResponse.json({
      posts: sorted,
      sources: subreddits.map((s) => `r/${s}`).concat(["CryptoPanic"]),
      fetchedAt: new Date().toISOString(),
    });
  } catch (err) {
    console.error("Trending posts API error:", err);
    return NextResponse.json(
      { error: "Failed to fetch trending posts", posts: [] },
      { status: 500 }
    );
  }
}
