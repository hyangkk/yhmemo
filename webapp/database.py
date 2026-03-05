import os
from typing import List, Optional
from supabase import create_client, Client
from models import Grant

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

_client: Optional[Client] = None


def get_client() -> Client:
    global _client
    if _client is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise ValueError(
                "SUPABASE_URL and SUPABASE_KEY environment variables must be set"
            )
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client


def upsert_grants(grants: List[Grant]) -> int:
    client = get_client()
    data = [g.model_dump(mode="json", exclude_none=True) for g in grants]
    result = client.table("grants").upsert(data, on_conflict="url").execute()
    return len(result.data)


def fetch_grants(limit: int = 100, offset: int = 0) -> List[Grant]:
    client = get_client()
    result = (
        client.table("grants")
        .select("*")
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return [Grant(**row) for row in result.data]


def fetch_grant_by_id(grant_id: str) -> Optional[Grant]:
    client = get_client()
    result = client.table("grants").select("*").eq("id", grant_id).single().execute()
    if result.data:
        return Grant(**result.data)
    return None
