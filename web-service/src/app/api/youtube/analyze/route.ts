import { NextResponse } from "next/server";
import { getSecret } from "@/lib/secrets";
import Anthropic from "@anthropic-ai/sdk";

export const dynamic = "force-dynamic";
export const maxDuration = 60;

interface TranscriptSegment {
  text: string;
  start: number;
  duration: number;
}

interface CaptionTrack {
  baseUrl: string;
  languageCode: string;
  kind?: string;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function extractCaptionTracks(playerData: any): CaptionTrack[] {
  try {
    return playerData?.captions?.playerCaptionsTracklistRenderer?.captionTracks || [];
  } catch {
    return [];
  }
}

const BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36";

async function getYouTubeSessionCookies(): Promise<string> {
  try {
    const resp = await fetch("https://www.youtube.com", {
      headers: {
        "User-Agent": BROWSER_UA,
      },
      redirect: "manual",
      cache: "no-store",
    });
    const setCookies = resp.headers.getSetCookie?.() || [];
    const cookieParts: string[] = [];
    for (const sc of setCookies) {
      const nameValue = sc.split(";")[0];
      if (nameValue) cookieParts.push(nameValue);
    }
    // consent 쿠키 추가 (유럽 GDPR 동의 우회)
    cookieParts.push("SOCS=CAISNQgDEitib3FfaWRlbnRpdHlmcm9udGVuZHVpc2VydmVyXzIwMjMxMTE0LjA3X3AxGgJlbiACGgYIgJnsBxQB");
    cookieParts.push("CONSENT=YES+cb.20210328-17-p0.en+FX+987");
    return cookieParts.join("; ");
  } catch (e) {
    console.error("Failed to get YouTube session cookies:", e);
    return "SOCS=CAISNQgDEitib3FfaWRlbnRpdHlmcm9udGVuZHVpc2VydmVyXzIwMjMxMTE0LjA3X3AxGgJlbiACGgYIgJnsBxQB; CONSENT=YES+cb.20210328-17-p0.en+FX+987";
  }
}

function parsePlayerResponseFromHTML(html: string): { data: unknown | null; error?: string } {
  let startIdx = html.indexOf("var ytInitialPlayerResponse");
  if (startIdx === -1) startIdx = html.indexOf("ytInitialPlayerResponse");
  if (startIdx === -1) return { data: null, error: "영상 데이터를 가져올 수 없습니다." };

  const braceStart = html.indexOf("{", startIdx);
  if (braceStart === -1) return { data: null, error: "영상 데이터 파싱에 실패했습니다." };

  let depth = 0;
  let jsonEnd = braceStart;
  for (let i = braceStart; i < html.length; i++) {
    if (html[i] === "{") depth++;
    else if (html[i] === "}") {
      depth--;
      if (depth === 0) { jsonEnd = i + 1; break; }
    }
  }

  try {
    return { data: JSON.parse(html.slice(braceStart, jsonEnd)) };
  } catch {
    return { data: null, error: "영상 데이터 파싱에 실패했습니다." };
  }
}

async function getPlayerResponse(videoId: string): Promise<{
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  data: any | null;
  cookies?: string;
  error?: string;
}> {
  // Method 1: HTML scraping (세션 쿠키로 봇 감지 우회)
  try {
    const cookies = await getYouTubeSessionCookies();
    const pageResp = await fetch(`https://www.youtube.com/watch?v=${videoId}`, {
      headers: {
        "Accept-Language": "ko,en;q=0.9",
        "User-Agent": BROWSER_UA,
        "Cookie": cookies,
      },
      cache: "no-store",
    });
    const html = await pageResp.text();
    const result = parsePlayerResponseFromHTML(html);
    if (result.data) {
      const tracks = extractCaptionTracks(result.data);
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const status = (result.data as any)?.playabilityStatus?.status;
      if (tracks.length > 0 || status === "OK") {
        return { ...result, cookies };
      }
      console.log(`HTML scraping: status=${status}, tracks=${tracks.length}`);
    }
  } catch (e) {
    console.error("HTML scraping error:", e);
  }

  // Method 2: Fallback - consent 쿠키만으로 재시도
  const fallbackCookies = "SOCS=CAISNQgDEitib3FfaWRlbnRpdHlmcm9udGVuZHVpc2VydmVyXzIwMjMxMTE0LjA3X3AxGgJlbiACGgYIgJnsBxQB; CONSENT=YES+cb.20210328-17-p0.en+FX+987";
  try {
    const pageResp = await fetch(`https://www.youtube.com/watch?v=${videoId}`, {
      headers: {
        "Accept-Language": "ko,en;q=0.9",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Cookie": fallbackCookies,
      },
      cache: "no-store",
    });
    const html = await pageResp.text();
    const result = parsePlayerResponseFromHTML(html);
    if (result.data) {
      return { ...result, cookies: fallbackCookies };
    }
  } catch (e) {
    console.error("HTML scraping fallback error:", e);
  }

  // Method 3: Innertube API (일부 환경에서 작동)
  try {
    const innertubeResp = await fetch(
      "https://www.youtube.com/youtubei/v1/player?prettyPrint=false",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          context: {
            client: {
              hl: "ko",
              gl: "KR",
              clientName: "WEB",
              clientVersion: "2.20260301.00.00",
            },
          },
          videoId,
        }),
      }
    );
    if (innertubeResp.ok) {
      const data = await innertubeResp.json();
      const tracks = extractCaptionTracks(data);
      if (tracks.length > 0 || data.playabilityStatus?.status === "OK") {
        return { data };
      }
    }
  } catch (e) {
    console.error("Innertube API error:", e);
  }

  return { data: null, error: "영상 데이터를 가져올 수 없습니다. YouTube가 요청을 차단했을 수 있습니다." };
}

function parseXmlTranscript(xml: string): TranscriptSegment[] {
  const segments: TranscriptSegment[] = [];
  const entryRegex = /<text start="([\d.]+)" dur="([\d.]+)"[^>]*>([\s\S]*?)<\/text>/g;
  let match;

  while ((match = entryRegex.exec(xml)) !== null) {
    const text = match[3]
      .replace(/&amp;/g, "&")
      .replace(/&lt;/g, "<")
      .replace(/&gt;/g, ">")
      .replace(/&quot;/g, '"')
      .replace(/&#39;/g, "'")
      .replace(/<[^>]+>/g, "")
      .trim();

    if (text) {
      segments.push({
        start: parseFloat(match[1]),
        duration: parseFloat(match[2]),
        text,
      });
    }
  }
  return segments;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function parseJson3Transcript(json3: any): TranscriptSegment[] {
  const segments: TranscriptSegment[] = [];
  const events = json3?.events || [];
  for (const event of events) {
    const segs = event.segs || [];
    const text = segs.map((s: { utf8?: string }) => s.utf8 || "").join("").trim();
    if (text && event.tStartMs !== undefined) {
      segments.push({
        start: (event.tStartMs || 0) / 1000,
        duration: (event.dDurationMs || 0) / 1000,
        text,
      });
    }
  }
  return segments;
}

async function fetchTranscript(videoId: string): Promise<{
  ok: boolean;
  text?: string;
  segments?: TranscriptSegment[];
  language?: string;
  autoGenerated?: boolean;
  error?: string;
}> {
  const preferredLanguages = ["ko", "en", "ja"];

  const { data: playerData, cookies, error: fetchError } = await getPlayerResponse(videoId);
  if (!playerData) {
    return { ok: false, error: fetchError || "영상 데이터를 가져올 수 없습니다." };
  }

  const captionTracks = extractCaptionTracks(playerData);
  if (captionTracks.length === 0) {
    return { ok: false, error: "이 영상에는 자막이 없습니다." };
  }

  // Find preferred language track
  let selectedTrack: CaptionTrack | null = null;
  for (const lang of preferredLanguages) {
    const track = captionTracks.find((t: CaptionTrack) => t.languageCode === lang);
    if (track) { selectedTrack = track; break; }
  }
  if (!selectedTrack) selectedTrack = captionTracks[0];

  const autoGenerated = selectedTrack.kind === "asr";
  const fetchHeaders: Record<string, string> = {
    "User-Agent": BROWSER_UA,
    "Accept-Language": "ko,en;q=0.9",
    "Referer": `https://www.youtube.com/watch?v=${videoId}`,
  };
  if (cookies) {
    fetchHeaders["Cookie"] = cookies;
  }

  try {
    // Attempt 1: XML 형식 (기본)
    const trackResp = await fetch(selectedTrack.baseUrl, { headers: fetchHeaders, cache: "no-store" });
    if (trackResp.ok) {
      const xml = await trackResp.text();
      if (xml.length > 0) {
        const segments = parseXmlTranscript(xml);
        if (segments.length > 0) {
          return {
            ok: true,
            text: segments.map(s => s.text).join(" "),
            segments,
            language: selectedTrack.languageCode,
            autoGenerated,
          };
        }
      }
    }

    // Attempt 2: json3 형식
    const json3Url = selectedTrack.baseUrl + "&fmt=json3";
    const json3Resp = await fetch(json3Url, { headers: fetchHeaders, cache: "no-store" });
    if (json3Resp.ok) {
      const text = await json3Resp.text();
      if (text.length > 0) {
        try {
          const json3Data = JSON.parse(text);
          const segments = parseJson3Transcript(json3Data);
          if (segments.length > 0) {
            return {
              ok: true,
              text: segments.map(s => s.text).join(" "),
              segments,
              language: selectedTrack.languageCode,
              autoGenerated,
            };
          }
        } catch {
          const segments = parseXmlTranscript(text);
          if (segments.length > 0) {
            return {
              ok: true,
              text: segments.map(s => s.text).join(" "),
              segments,
              language: selectedTrack.languageCode,
              autoGenerated,
            };
          }
        }
      }
    }

    // Attempt 3: 다른 자막 트랙으로 시도
    for (const altTrack of captionTracks) {
      if (altTrack === selectedTrack) continue;
      try {
        const altResp = await fetch(altTrack.baseUrl, { headers: fetchHeaders, cache: "no-store" });
        if (altResp.ok) {
          const altXml = await altResp.text();
          if (altXml.length > 0) {
            const segments = parseXmlTranscript(altXml);
            if (segments.length > 0) {
              return {
                ok: true,
                text: segments.map(s => s.text).join(" "),
                segments,
                language: altTrack.languageCode,
                autoGenerated: altTrack.kind === "asr",
              };
            }
          }
        }
      } catch {
        continue;
      }
    }

    console.error(`All transcript fetch attempts failed for ${videoId}`);
    return { ok: false, error: "자막 데이터를 가져올 수 없습니다. YouTube 서버에서 차단되었을 수 있습니다." };
  } catch (err) {
    console.error("Transcript fetch error:", err);
    return { ok: false, error: "자막을 가져오는 중 오류가 발생했습니다." };
  }
}

async function fetchVideoInfo(videoId: string): Promise<{ title: string; author: string; thumbnail: string }> {
  try {
    const resp = await fetch(
      `https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v=${videoId}&format=json`
    );
    if (resp.ok) {
      const data = await resp.json();
      return {
        title: data.title || "",
        author: data.author_name || "",
        thumbnail: `https://img.youtube.com/vi/${videoId}/hqdefault.jpg`,
      };
    }
  } catch { /* ignore */ }
  return { title: "", author: "", thumbnail: `https://img.youtube.com/vi/${videoId}/hqdefault.jpg` };
}

export async function POST(request: Request) {
  try {
    const { videoId, mode = "summary" } = await request.json();

    if (!videoId || typeof videoId !== "string" || !/^[a-zA-Z0-9_-]{11}$/.test(videoId)) {
      return NextResponse.json({ error: "유효하지 않은 영상 ID입니다." }, { status: 400 });
    }

    const apiKey = await getSecret("ANTHROPIC_API_KEY");
    if (!apiKey) {
      return NextResponse.json({ error: "API 키가 설정되지 않았습니다." }, { status: 500 });
    }

    // Fetch video info and transcript in parallel
    const [videoInfo, transcriptResult] = await Promise.all([
      fetchVideoInfo(videoId),
      fetchTranscript(videoId),
    ]);

    if (!transcriptResult.ok) {
      return NextResponse.json({
        error: transcriptResult.error,
        videoInfo,
      }, { status: 422 });
    }

    const transcriptText = transcriptResult.text!;
    const maxChars = 300_000;
    const truncated = transcriptText.length > maxChars
      ? transcriptText.slice(0, maxChars) + "\n\n... (자막이 너무 길어 일부만 포함)"
      : transcriptText;

    const titleHint = videoInfo.title ? `\n영상 제목: ${videoInfo.title}` : "";

    const prompts: Record<string, string> = {
      summary: `다음은 YouTube 영상의 자막입니다.${titleHint}

이 영상의 내용을 한국어로 요약해주세요.

요약 형식:
1. **핵심 주제** (1-2줄)
2. **주요 내용** (핵심 포인트 3-7개, 불릿)
3. **결론/시사점** (1-2줄)

자막:
${truncated}`,

      full: `다음은 YouTube 영상의 자막입니다.${titleHint}

이 자막을 깔끔하게 정리해주세요:
- 말의 반복, 군더더기를 제거
- 주제별로 구분
- 읽기 쉽게 문단 나누기
- 한국어로 작성 (원문이 영어면 번역)

자막:
${truncated}`,

      key_points: `다음은 YouTube 영상의 자막입니다.${titleHint}

핵심 포인트만 추출해주세요:
- 가장 중요한 인사이트 5-10개
- 각 포인트는 1-2줄로 간결하게
- 실행 가능한 조언이 있다면 별도 표시

자막:
${truncated}`,
    };

    const client = new Anthropic({ apiKey });
    const response = await client.messages.create({
      model: "claude-sonnet-4-20250514",
      max_tokens: 4000,
      system: "당신은 영상 내용을 정확하고 깊이있게 요약하는 전문가입니다. 마크다운 포맷으로 작성하세요.",
      messages: [{ role: "user", content: prompts[mode] || prompts.summary }],
    });

    const summary = response.content[0].type === "text" ? response.content[0].text : "";

    return NextResponse.json({
      videoInfo,
      transcript: {
        text: transcriptText,
        language: transcriptResult.language,
        autoGenerated: transcriptResult.autoGenerated,
        charCount: transcriptText.length,
      },
      summary,
      mode,
    });
  } catch (error) {
    console.error("YouTube analyze error:", error);
    return NextResponse.json({ error: "분석 중 오류가 발생했습니다." }, { status: 500 });
  }
}
