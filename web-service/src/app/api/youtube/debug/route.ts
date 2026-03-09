import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const maxDuration = 30;

const BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const videoId = url.searchParams.get("v") || "dQw4w9WgXcQ";
  const log: string[] = [];

  try {
    // Step 1: Fetch video page with cookies
    log.push("Step 1: Fetching video page...");
    const cookieResp = await fetch("https://www.youtube.com", {
      headers: { "User-Agent": BROWSER_UA },
      redirect: "manual",
      cache: "no-store",
    });
    const setCookies = cookieResp.headers.getSetCookie?.() || [];
    const cookieParts: string[] = [];
    for (const sc of setCookies) {
      const nv = sc.split(";")[0];
      if (nv) cookieParts.push(nv);
    }
    cookieParts.push("SOCS=CAISNQgDEitib3FfaWRlbnRpdHlmcm9udGVuZHVpc2VydmVyXzIwMjMxMTE0LjA3X3AxGgJlbiACGgYIgJnsBxQB");
    cookieParts.push("CONSENT=YES+cb.20210328-17-p0.en+FX+987");
    const cookieStr = cookieParts.join("; ");

    const pageResp = await fetch(`https://www.youtube.com/watch?v=${videoId}`, {
      headers: {
        "Accept-Language": "ko,en;q=0.9",
        "User-Agent": BROWSER_UA,
        "Cookie": cookieStr,
      },
      cache: "no-store",
    });
    const html = await pageResp.text();
    log.push(`  HTML: ${html.length} bytes, status: ${pageResp.status}`);

    // Check for transcript data directly in page
    const transcriptInPage = (html.match(/transcriptSegmentRenderer/g) || []).length;
    log.push(`  transcriptSegmentRenderer in page: ${transcriptInPage}`);

    // Extract caption tracks
    let tracks: { baseUrl: string; languageCode: string; kind?: string }[] = [];
    try {
      const captions = JSON.parse(html.split('"captions":')[1]?.split(',"videoDetails')[0] || "{}");
      tracks = captions?.playerCaptionsTracklistRenderer?.captionTracks || [];
    } catch { /* ignore */ }
    log.push(`  Caption tracks: ${tracks.length}`);

    // Step 2: Try video.google.com/timedtext API
    log.push("\nStep 2: Testing video.google.com/timedtext...");
    const ttUrls = [
      `https://video.google.com/timedtext?type=list&v=${videoId}`,
      `https://video.google.com/timedtext?lang=en&v=${videoId}`,
    ];
    for (const ttUrl of ttUrls) {
      try {
        const ttResp = await fetch(ttUrl, {
          headers: { "User-Agent": BROWSER_UA },
          cache: "no-store",
        });
        const ttText = await ttResp.text();
        const shortUrl = ttUrl.split("timedtext")[1];
        log.push(`  ${shortUrl}: status=${ttResp.status}, length=${ttText.length}`);
        if (ttText.length > 0 && ttText.length < 500) {
          log.push(`    content: ${ttText.substring(0, 200)}`);
        } else if (ttText.length > 0) {
          log.push(`    preview: ${ttText.substring(0, 200)}`);
        }
      } catch (e) {
        log.push(`  Error: ${e}`);
      }
    }

    // Step 3: Try caption URL with Origin header
    if (tracks.length > 0) {
      const enTrack = tracks.find(t => t.languageCode === "en" && t.kind !== "asr") || tracks[0];
      log.push(`\nStep 3: Caption URL download (${enTrack.languageCode})...`);

      // Test with Origin header (mimicking same-origin request)
      const variants = [
        { name: "with Origin+Referer", headers: {
          "User-Agent": BROWSER_UA, "Cookie": cookieStr,
          "Origin": "https://www.youtube.com",
          "Referer": `https://www.youtube.com/watch?v=${videoId}`,
          "Accept": "*/*",
        }},
        { name: "with Sec-Fetch headers", headers: {
          "User-Agent": BROWSER_UA, "Cookie": cookieStr,
          "Origin": "https://www.youtube.com",
          "Referer": `https://www.youtube.com/watch?v=${videoId}`,
          "Sec-Fetch-Dest": "empty",
          "Sec-Fetch-Mode": "cors",
          "Sec-Fetch-Site": "same-origin",
        }},
        { name: "plain (no extra headers)", headers: {
          "User-Agent": BROWSER_UA,
        }},
      ];

      for (const v of variants) {
        try {
          const resp = await fetch(enTrack.baseUrl, {
            headers: v.headers,
            cache: "no-store",
          });
          const text = await resp.text();
          log.push(`  ${v.name}: status=${resp.status}, length=${text.length}`);
          if (text.length > 0) {
            log.push(`    preview: ${text.substring(0, 150)}`);
          }
        } catch (e) {
          log.push(`  ${v.name}: error=${e}`);
        }
      }

      // Try with &fmt=srv3 (different format)
      try {
        const srv3Resp = await fetch(enTrack.baseUrl + "&fmt=srv3", {
          headers: { "User-Agent": BROWSER_UA, "Cookie": cookieStr },
          cache: "no-store",
        });
        const srv3Text = await srv3Resp.text();
        log.push(`  fmt=srv3: status=${srv3Resp.status}, length=${srv3Text.length}`);
        if (srv3Text.length > 0) {
          log.push(`    preview: ${srv3Text.substring(0, 150)}`);
        }
      } catch (e) {
        log.push(`  fmt=srv3: error=${e}`);
      }
    }

    // Step 4: Try YouTube oEmbed + separate timedtext via innertube
    log.push("\nStep 4: Try innertube player API for caption URLs...");
    try {
      const playerResp = await fetch(
        "https://www.youtube.com/youtubei/v1/player?prettyPrint=false",
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "User-Agent": BROWSER_UA,
            "Cookie": cookieStr,
            "Origin": "https://www.youtube.com",
            "Referer": "https://www.youtube.com/",
          },
          body: JSON.stringify({
            context: {
              client: {
                hl: "ko", gl: "KR",
                clientName: "WEB",
                clientVersion: "2.20260301.00.00",
              },
            },
            videoId,
          }),
          cache: "no-store",
        }
      );
      const playerData = await playerResp.json();
      const apiTracks = playerData?.captions?.playerCaptionsTracklistRenderer?.captionTracks || [];
      log.push(`  Innertube tracks: ${apiTracks.length}`);
      if (apiTracks.length > 0) {
        const apiTrack = apiTracks.find((t: { languageCode: string; kind?: string }) => t.languageCode === "en" && t.kind !== "asr") || apiTracks[0];
        log.push(`  Trying innertube track URL for ${apiTrack.languageCode}...`);
        const apiXmlResp = await fetch(apiTrack.baseUrl, {
          headers: { "User-Agent": BROWSER_UA, "Cookie": cookieStr },
          cache: "no-store",
        });
        const apiXml = await apiXmlResp.text();
        log.push(`  Result: status=${apiXmlResp.status}, length=${apiXml.length}`);
        if (apiXml.length > 0) {
          log.push(`  preview: ${apiXml.substring(0, 200)}`);
        }
      }
    } catch (e) {
      log.push(`  Error: ${e}`);
    }

    return NextResponse.json({ log });
  } catch (error) {
    log.push(`\nERROR: ${error}`);
    return NextResponse.json({ log, error: String(error) });
  }
}
