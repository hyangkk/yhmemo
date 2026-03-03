#!/usr/bin/env python3
"""Notion API에서 공유된 데이터베이스 목록을 검색합니다."""
import os
import json
import urllib.request

NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")

headers = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}

# Search for all databases
req = urllib.request.Request(
    "https://api.notion.com/v1/search",
    data=json.dumps({"filter": {"value": "database", "property": "object"}}).encode(),
    headers=headers,
    method="POST",
)

with urllib.request.urlopen(req, timeout=15) as resp:
    data = json.loads(resp.read().decode())
    for db in data.get("results", []):
        title = ""
        for t in db.get("title", []):
            title += t.get("plain_text", "")
        print(f"ID: {db['id']}  Title: {title}")
