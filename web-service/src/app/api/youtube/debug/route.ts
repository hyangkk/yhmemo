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
    log.push(`  Cookie names: ${cookieParts.map(c => c.split("=")[0]).join(", ")}`);

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

    // Step 3: Extract player response
    let startIdx = html.indexOf("var ytInitialPlayerResponse");
    if (startIdx === -1) startIdx = html.indexOf("ytInitialPlayerResponse");
    log.push(`  ytInitialPlayerResponse found at: ${startIdx}`);

    if (startIdx === -1) {
      log.push("  FAILED: No ytInitialPlayerResponse in page");
      return NextResponse.json({ log, error: "no player response" });
    }

    const braceStart = html.indexOf("{", startIdx);
    let depth = 0;
    let jsonEnd = braceStart;
    for (let i = braceStart; i < html.length; i++) {
      if (html[i] === "{") depth++;
      else if (html[i] === "}") {
        depth--;
        if (depth === 0) { jsonEnd = i + 1; break; }
      }
    }
    const playerData = JSON.parse(html.slice(braceStart, jsonEnd));
    const playStatus = playerData?.playabilityStatus?.status;
    log.push(`  Playability status: ${playStatus}`);

    const captionTracks = playerData?.captions?.playerCaptionsTracklistRenderer?.captionTracks || [];
    log.push(`  Caption tracks: ${captionTracks.length}`);

    if (captionTracks.length === 0) {
      log.push("  FAILED: No caption tracks found");
      return NextResponse.json({ log, error: "no captions", playStatus });
    }

    // List tracks
    for (const t of captionTracks.slice(0, 5)) {
      log.push(`    - ${t.languageCode} (${t.kind || "manual"}): url_len=${t.baseUrl?.length || 0}`);
    }

    // Step 4: Try fetching subtitle XML
    const track = captionTracks[0];
    log.push(`\nStep 3: Fetching subtitle XML for ${track.languageCode}...`);
    log.push(`  URL: ${track.baseUrl.substring(0, 100)}...`);

    // Attempt A: without cookies
    const xmlRespA = await fetch(track.baseUrl, {
      headers: { "User-Agent": BROWSER_UA },
      cache: "no-store",
    });
    const xmlA = await xmlRespA.text();
    log.push(`  Attempt A (no cookies): status=${xmlRespA.status}, length=${xmlA.length}`);

    // Attempt B: with cookies
    const xmlRespB = await fetch(track.baseUrl, {
      headers: {
        "User-Agent": BROWSER_UA,
        "Cookie": cookieStr,
        "Referer": `https://www.youtube.com/watch?v=${videoId}`,
      },
      cache: "no-store",
    });
    const xmlB = await xmlRespB.text();
    log.push(`  Attempt B (with cookies): status=${xmlRespB.status}, length=${xmlB.length}`);

    // Attempt C: json3 format
    const xmlRespC = await fetch(track.baseUrl + "&fmt=json3", {
      headers: {
        "User-Agent": BROWSER_UA,
        "Cookie": cookieStr,
      },
      cache: "no-store",
    });
    const xmlC = await xmlRespC.text();
    log.push(`  Attempt C (json3): status=${xmlRespC.status}, length=${xmlC.length}`);

    if (xmlA.length > 0) {
      log.push(`  XML preview (A): ${xmlA.substring(0, 200)}`);
    }
    if (xmlB.length > 0) {
      log.push(`  XML preview (B): ${xmlB.substring(0, 200)}`);
    }
    if (xmlC.length > 0) {
      log.push(`  JSON3 preview (C): ${xmlC.substring(0, 200)}`);
    }

    return NextResponse.json({ log, success: xmlA.length > 0 || xmlB.length > 0 || xmlC.length > 0 });
  } catch (error) {
    log.push(`\nERROR: ${error}`);
    return NextResponse.json({ log, error: String(error) });
  }
}
