import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const maxDuration = 30;

const BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const videoId = url.searchParams.get("v") || "dQw4w9WgXcQ";
  const log: string[] = [];

  try {
    // Step 1: Get YouTube session cookies
    log.push("Step 1: Getting session cookies...");
    const cookieResp = await fetch("https://www.youtube.com", {
      headers: { "User-Agent": BROWSER_UA },
      redirect: "manual",
      cache: "no-store",
    });
    const setCookies = cookieResp.headers.getSetCookie?.() || [];
    const cookieParts: string[] = [];
    for (const sc of setCookies) {
      const nameValue = sc.split(";")[0];
      if (nameValue) cookieParts.push(nameValue);
    }
    cookieParts.push("SOCS=CAISNQgDEitib3FfaWRlbnRpdHlmcm9udGVuZHVpc2VydmVyXzIwMjMxMTE0LjA3X3AxGgJlbiACGgYIgJnsBxQB");
    cookieParts.push("CONSENT=YES+cb.20210328-17-p0.en+FX+987");
    const cookieStr = cookieParts.join("; ");
    log.push(`  Cookies: ${cookieParts.length} items (${setCookies.length} from YouTube)`);

    // Step 2: Fetch video page
    log.push("\nStep 2: Fetching video page...");
    const pageResp = await fetch(`https://www.youtube.com/watch?v=${videoId}`, {
      headers: {
        "Accept-Language": "ko,en;q=0.9",
        "User-Agent": BROWSER_UA,
        "Cookie": cookieStr,
      },
      cache: "no-store",
    });
    const html = await pageResp.text();
    log.push(`  HTML length: ${html.length}`);
    log.push(`  Page status: ${pageResp.status}`);

    // Extract visitorData
    const vdMatch = html.match(/"visitorData":"([^"]+)"/);
    const visitorData = vdMatch ? vdMatch[1] : null;
    log.push(`  visitorData: ${visitorData ? visitorData.substring(0, 40) + "..." : "NOT FOUND"}`);

    // Extract getTranscriptEndpoint params
    const paramsMatch = html.match(/getTranscriptEndpoint.*?"params"\s*:\s*"([^"]+)"/);
    const transcriptParams = paramsMatch ? paramsMatch[1] : null;
    log.push(`  getTranscriptEndpoint params: ${transcriptParams ? transcriptParams.substring(0, 40) + "..." : "NOT FOUND"}`);

    // Caption tracks check
    const captionTracks = JSON.parse(html.split('"captions":')[1]?.split(',"videoDetails')[0] || "{}");
    const tracks = captionTracks?.playerCaptionsTracklistRenderer?.captionTracks || [];
    log.push(`  Caption tracks: ${tracks.length}`);
    for (const t of tracks.slice(0, 3)) {
      log.push(`    - ${t.languageCode} (${t.kind || "manual"})`);
    }

    // Step 3: Try get_transcript API
    if (transcriptParams) {
      log.push("\nStep 3: Testing get_transcript API...");

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const ctx: any = {
        client: {
          hl: "ko",
          gl: "KR",
          clientName: "WEB",
          clientVersion: "2.20260301.00.00",
        },
      };
      if (visitorData) ctx.client.visitorData = visitorData;

      const gtResp = await fetch(
        "https://www.youtube.com/youtubei/v1/get_transcript?prettyPrint=false",
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "User-Agent": BROWSER_UA,
            "Cookie": cookieStr,
          },
          body: JSON.stringify({ context: ctx, params: transcriptParams }),
          cache: "no-store",
        }
      );
      log.push(`  Status: ${gtResp.status}`);
      const gtText = await gtResp.text();
      log.push(`  Response length: ${gtText.length}`);
      const segCount = (gtText.match(/transcriptSegmentRenderer/g) || []).length;
      log.push(`  Segments found: ${segCount}`);
      if (segCount > 0) {
        log.push(`  SUCCESS!`);
        // Parse first segment
        try {
          const gtData = JSON.parse(gtText);
          for (const action of gtData.actions || []) {
            const segs = action?.updateEngagementPanelAction?.content?.transcriptRenderer?.content
              ?.transcriptSearchPanelRenderer?.body?.transcriptSegmentListRenderer?.initialSegments;
            if (segs && segs.length > 0) {
              const first = segs[0]?.transcriptSegmentRenderer;
              if (first) {
                const text = first.snippet?.runs?.map((r: { text?: string }) => r.text || "").join("") || "";
                log.push(`  First segment: "${text}"`);
              }
            }
          }
        } catch { /* ignore */ }
      } else if (gtText.length < 1000) {
        log.push(`  Response: ${gtText}`);
      } else {
        log.push(`  Response preview: ${gtText.substring(0, 500)}`);
      }
    } else {
      log.push("\nStep 3: SKIPPED (no getTranscriptEndpoint params)");

      // Fallback: Try caption URL download
      if (tracks.length > 0) {
        const track = tracks[0];
        log.push(`\nStep 3b: Trying caption URL for ${track.languageCode}...`);
        const xmlResp = await fetch(track.baseUrl, {
          headers: { "User-Agent": BROWSER_UA, "Cookie": cookieStr },
          cache: "no-store",
        });
        const xml = await xmlResp.text();
        log.push(`  Status: ${xmlResp.status}, Length: ${xml.length}`);
        if (xml.length > 0) {
          log.push(`  Preview: ${xml.substring(0, 200)}`);
        }
      }
    }

    return NextResponse.json({ log, success: true });
  } catch (error) {
    log.push(`\nERROR: ${error}`);
    return NextResponse.json({ log, error: String(error) });
  }
}
