import { NextResponse } from "next/server";
import { Innertube } from "youtubei.js";

export const dynamic = "force-dynamic";
export const maxDuration = 30;

export async function GET(request: Request) {
  const url = new URL(request.url);
  const videoId = url.searchParams.get("v") || "dQw4w9WgXcQ";
  const log: string[] = [];

  try {
    // Test: youtubei.js library
    log.push("Step 1: Testing youtubei.js...");
    try {
      const yt = await Innertube.create();
      log.push("  Innertube created");

      const info = await yt.getInfo(videoId);
      log.push(`  Video: ${info.basic_info.title}`);
      log.push(`  Duration: ${info.basic_info.duration}s`);

      const transcript = await info.getTranscript();
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const tAny = transcript as any;

      log.push(`  Transcript keys: ${Object.keys(tAny || {}).join(", ")}`);

      const body = tAny?.transcript?.content?.body;
      if (body) {
        const segList = body?.initialSegments || [];
        log.push(`  Segments: ${segList.length}`);

        if (segList.length > 0) {
          // Parse first 3 segments
          for (const seg of segList.slice(0, 3)) {
            const renderer = seg?.transcriptSegmentRenderer;
            if (renderer) {
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              const text = renderer.snippet?.runs?.map((r: any) => r.text || "").join("") || "";
              log.push(`  [${renderer.startMs}ms] ${text}`);
            }
          }
          log.push("  SUCCESS!");
        }
      } else {
        log.push(`  Transcript structure: ${JSON.stringify(tAny).substring(0, 500)}`);
      }
    } catch (e) {
      log.push(`  Error: ${e instanceof Error ? e.message : String(e)}`);
      if (e instanceof Error && e.stack) {
        log.push(`  Stack: ${e.stack.split("\n").slice(0, 3).join(" -> ")}`);
      }
    }

    return NextResponse.json({ log });
  } catch (error) {
    log.push(`\nERROR: ${error}`);
    return NextResponse.json({ log, error: String(error) });
  }
}
