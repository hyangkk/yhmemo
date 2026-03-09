#!/usr/bin/env python3
"""시세조회 슬랙 테스트 스크립트"""
import json, os, time, urllib.request

TOKEN = os.environ["SLACK_BOT_TOKEN"]
CHANNEL = "C0AKRJZ395W"  # ai-invest

def slack_post(channel, text):
    data = json.dumps({"channel": channel, "text": text}).encode("utf-8")
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=data,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json; charset=utf-8",
        },
    )
    resp = urllib.request.urlopen(req)
    return json.loads(resp.read())

def get_replies(channel, ts):
    req = urllib.request.Request(
        f"https://slack.com/api/conversations.replies?channel={channel}&ts={ts}",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    resp = urllib.request.urlopen(req)
    return json.loads(resp.read())

def get_history(channel, oldest, limit=5):
    req = urllib.request.Request(
        f"https://slack.com/api/conversations.history?channel={channel}&limit={limit}&oldest={oldest}",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    resp = urllib.request.urlopen(req)
    return json.loads(resp.read())

# Send command
cmd = "\u0021\uc2dc\uc138\uc870\ud68c 005930"  # !시세조회 005930
result = slack_post(CHANNEL, cmd)
ts = result.get("ts", "")
print(f"Sent: ok={result['ok']}, ts={ts}")
print(f"Text: {result.get('message', {}).get('text', '')}")

# Wait for bot response
print("Waiting 20s for bot response...")
time.sleep(20)

# Check thread
replies = get_replies(CHANNEL, ts)
print("\n=== Thread Replies ===")
for m in replies.get("messages", []):
    print(f"\n{m.get('text', '')[:600]}")

# Check channel
hist = get_history(CHANNEL, ts)
print("\n=== Channel Messages After ===")
for m in hist.get("messages", []):
    print(f"\n{m.get('text', '')[:600]}")
