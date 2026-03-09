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
      headers: { "User-Agent": BROWSER_UA },
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
  html?: string;
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
        return { ...result, cookies, html };
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
      return { ...result, cookies: fallbackCookies, html };
    }
  } catch (e) {
    console.error("HTML scraping fallback error:", e);
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

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function parseInnertubeTranscript(data: any): TranscriptSegment[] {
  const segments: TranscriptSegment[] = [];
  try {
    const actions = data?.actions;
    if (!actions) return segments;

    for (const action of actions) {
      const panel = action?.updateEngagementPanelAction?.content?.transcriptRenderer?.content
        ?.transcriptSearchPanelRenderer?.body?.transcriptSegmentListRenderer?.initialSegments;
      if (panel) {
        for (const seg of panel) {
          const renderer = seg?.transcriptSegmentRenderer;
          if (renderer) {
            const text = renderer.snippet?.runs?.map((r: { text?: string }) => r.text || "").join("").trim() || "";
            const startMs = parseInt(renderer.startMs || "0", 10);
            const endMs = parseInt(renderer.endMs || "0", 10);
            if (text) {
              segments.push({
                start: startMs / 1000,
                duration: (endMs - startMs) / 1000,
                text,
              });
            }
          }
        }
      }
    }
  } catch (e) {
    console.error("parseInnertubeTranscript error:", e);
  }
  return segments;
}

// YouTube 페이지에서 getTranscriptEndpoint params와 visitorData 추출
function extractTranscriptParams(html: string): { params: string | null; visitorData: string | null } {
  let params: string | null = null;
  let visitorData: string | null = null;

  // visitorData 추출
  const vdMatch = html.match(/"visitorData":"([^"]+)"/);
  if (vdMatch) visitorData = vdMatch[1];

  // getTranscriptEndpoint params 추출
  const paramsMatch = html.match(/getTranscriptEndpoint.*?"params"\s*:\s*"([^"]+)"/);
  if (paramsMatch) params = paramsMatch[1];

  return { params, visitorData };
}

async function fetchTranscriptViaGetTranscript(
  videoId: string,
  html: string,
  cookies: string
): Promise<{
  ok: boolean;
  text?: string;
  segments?: TranscriptSegment[];
  error?: string;
}> {
  const { params, visitorData } = extractTranscriptParams(html);

  if (!params) {
    console.log("getTranscriptEndpoint params not found in page");
    return { ok: false, error: "자막 패널 정보를 찾을 수 없습니다." };
  }

  console.log(`get_transcript: params=${params.substring(0, 30)}..., visitorData=${visitorData ? "found" : "missing"}`);

  try {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const context: any = {
      client: {
        hl: "ko",
        gl: "KR",
        clientName: "WEB",
        clientVersion: "2.20260301.00.00",
      },
    };
    if (visitorData) {
      context.client.visitorData = visitorData;
    }

    const resp = await fetch(
      "https://www.youtube.com/youtubei/v1/get_transcript?prettyPrint=false",
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "User-Agent": BROWSER_UA,
          ...(cookies ? { Cookie: cookies } : {}),
        },
        body: JSON.stringify({ context, params }),
        cache: "no-store",
      }
    );

    if (!resp.ok) {
      console.error("get_transcript failed:", resp.status);
      return { ok: false, error: `get_transcript API 실패 (${resp.status})` };
    }

    const data = await resp.json();
    const segments = parseInnertubeTranscript(data);
    if (segments.length > 0) {
      return {
        ok: true,
        text: segments.map(s => s.text).join(" "),
        segments,
      };
    }

    console.log("get_transcript returned no segments, keys:", Object.keys(data));
    return { ok: false, error: "get_transcript 응답에서 자막을 찾을 수 없습니다." };
  } catch (e) {
    console.error("fetchTranscriptViaGetTranscript error:", e);
    return { ok: false, error: "get_transcript API 호출 중 오류" };
  }
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

  const { data: playerData, cookies, html, error: fetchError } = await getPlayerResponse(videoId);
  if (!playerData) {
    return { ok: false, error: fetchError || "영상 데이터를 가져올 수 없습니다." };
  }

  const captionTracks = extractCaptionTracks(playerData);
  if (captionTracks.length === 0) {
    return { ok: false, error: "이 영상에는 자막이 없습니다." };
  }

  // Method 0: get_transcript API (페이지에서 추출한 params 사용 - 캡션 URL 차단 우회)
  if (html) {
    const gtResult = await fetchTranscriptViaGetTranscript(videoId, html, cookies || "");
    if (gtResult.ok) {
      return {
        ...gtResult,
        language: "auto",
        autoGenerated: false,
      };
    }
    console.log("get_transcript failed, falling back to caption URL download...");
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
      `https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v=${videoId}&format=json`,
      { cache: "no-store" }
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
    const { videoId, mode = "summary", manualTranscript } = await request.json();

    if (!videoId || typeof videoId !== "string" || !/^[a-zA-Z0-9_-]{11}$/.test(videoId)) {
      return NextResponse.json({ error: "유효하지 않은 영상 ID입니다." }, { status: 400 });
    }

    const apiKey = await getSecret("ANTHROPIC_API_KEY");
    if (!apiKey) {
      return NextResponse.json({ error: "API 키가 설정되지 않았습니다." }, { status: 500 });
    }

    let videoInfo: { title: string; author: string; thumbnail: string };
    let transcriptText: string;
    let transcriptLanguage = "";
    let transcriptAutoGenerated = false;

    if (manualTranscript && typeof manualTranscript === "string" && manualTranscript.trim().length > 0) {
      // 수동 자막 입력 모드
      videoInfo = await fetchVideoInfo(videoId);
      transcriptText = manualTranscript.trim();
    } else {
      // 자동 자막 추출 모드
      const [vi, transcriptResult] = await Promise.all([
        fetchVideoInfo(videoId),
        fetchTranscript(videoId),
      ]);
      videoInfo = vi;

      if (!transcriptResult.ok) {
        return NextResponse.json({
          error: transcriptResult.error,
          videoInfo,
        }, { status: 422 });
      }

      transcriptText = transcriptResult.text!;
      transcriptLanguage = transcriptResult.language || "";
      transcriptAutoGenerated = transcriptResult.autoGenerated || false;
    }
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
        language: transcriptLanguage,
        autoGenerated: transcriptAutoGenerated,
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
