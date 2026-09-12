"""REST client for Vertex AI Memory Bank (Agent Engine).

Thin, dependency-light wrapper over the v1beta1 `reasoningEngines/*/memories*`
endpoints. Auth via Application Default Credentials (ADC). Uses `requests` for
HTTP and `google.auth` for token management — both already present in a Hermes
environment that talks to Google Cloud.

API reference (captured during build):
  POST   {parent}/memories:retrieve   — similarity search (recall)
  POST   {parent}/memories:generate   — write via consolidation (capture/remember)
  GET    {parent}/memories            — list (paginated, max pageSize=100)
  DELETE {parent}/memories/{id}       — forget
  PATCH  {parent}/memories/{id}       — correct (update fact in place)
where {parent} = projects/{p}/locations/{l}/reasoningEngines/{e}
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_API_VERSION = "v1beta1"
_TEXT_TRUNCATE = 4000   # max chars per conversation event
_DEFAULT_TIMEOUT = 30


class MemoryBankError(RuntimeError):
    """Raised on a non-2xx Memory Bank API response."""


class VertexMemoryBankClient:
    """Minimal Vertex AI Memory Bank REST client (ADC-authenticated)."""

    def __init__(self, project_id: str, location: str, reasoning_engine_id: str):
        if not (project_id and location and reasoning_engine_id):
            raise MemoryBankError(
                "project_id, location, and reasoning_engine_id are all required")
        self.project_id = project_id
        self.location = location
        self.reasoning_engine_id = reasoning_engine_id
        self._base = f"https://{location}-aiplatform.googleapis.com/{_API_VERSION}"
        self._parent = (
            f"projects/{project_id}/locations/{location}"
            f"/reasoningEngines/{reasoning_engine_id}"
        )
        self._creds = None
        self._auth_req = None
        self._lock = threading.Lock()

    # -- auth -----------------------------------------------------------------

    def _token(self) -> str:
        """Return a fresh ADC access token, refreshing as needed."""
        with self._lock:
            if self._creds is None:
                import google.auth
                from google.auth.transport.requests import Request
                self._creds, _ = google.auth.default(
                    scopes=["https://www.googleapis.com/auth/cloud-platform"])
                self._auth_req = Request()
            if not self._creds.valid:
                self._creds.refresh(self._auth_req)
            return self._creds.token

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token()}",
            "Content-Type": "application/json",
            "User-Agent": "hermes-memory-vertex/1.0",
        }

    # -- HTTP -----------------------------------------------------------------

    def _request(self, method: str, path: str, *, body: Optional[dict] = None,
                 params: Optional[dict] = None, timeout: int = _DEFAULT_TIMEOUT) -> dict:
        import requests
        url = f"{self._base}/{path}"
        resp = requests.request(
            method, url, headers=self._headers(),
            json=body if body is not None else None,
            params=params, timeout=timeout,
        )
        if not resp.ok:
            raise MemoryBankError(
                f"Memory Bank API {resp.status_code}: {resp.text[:500]}")
        if resp.text:
            try:
                return resp.json()
            except ValueError:
                return {}
        return {}

    # -- operations -----------------------------------------------------------

    def retrieve(self, scope: Dict[str, str], query: str, *, top_k: int = 10,
                 max_distance: Optional[float] = None) -> List[Dict[str, Any]]:
        """Similarity search. Returns [{fact, id, distance}]."""
        result = self._request(
            "POST", f"{self._parent}/memories:retrieve",
            body={"scope": scope,
                  "similaritySearchParams": {"searchQuery": query, "topK": top_k}},
        )
        out: List[Dict[str, Any]] = []
        for item in result.get("retrievedMemories", []):
            mem = item.get("memory", {})
            dist = item.get("distance")
            if max_distance is not None and dist is not None and dist > max_distance:
                continue
            out.append({
                "fact": mem.get("fact", ""),
                "id": _memory_id(mem.get("name", "")),
                "distance": dist,
            })
        return out

    def generate_from_conversation(self, scope: Dict[str, str],
                                   messages: List[Dict[str, str]], *,
                                   source: str = "capture") -> dict:
        """Write the last user+assistant pair via consolidation (events format)."""
        pair = [m for m in messages if m.get("role") in ("user", "assistant")][-2:]
        if not pair:
            return {}
        events = [{
            "content": {
                "role": "model" if m["role"] == "assistant" else "user",
                "parts": [{"text": (m.get("content") or "")[:_TEXT_TRUNCATE]}],
            }
        } for m in pair]
        return self._request(
            "POST", f"{self._parent}/memories:generate",
            body={"scope": scope,
                  "direct_contents_source": {"events": events},
                  "revision_labels": {"source": source}},
        )

    def generate_from_fact(self, scope: Dict[str, str], fact: str, *,
                           source: str = "remember", wait: bool = False) -> dict:
        """Write a raw fact via consolidation (direct_memories_source)."""
        result = self._request(
            "POST", f"{self._parent}/memories:generate",
            body={"scope": scope,
                  "direct_memories_source": {"direct_memories": [{"fact": fact}]},
                  "revision_labels": {"source": source}},
        )
        if not wait:
            return {"queued": True}
        generated = result.get("generatedMemories", [])
        created = sum(1 for m in generated if m.get("action") == "CREATED")
        updated = sum(1 for m in generated if m.get("action") == "UPDATED")
        return {"created": created, "updated": updated, "total": len(generated)}

    def get_memory(self, memory_id: str) -> Dict[str, Any]:
        """GET a single memory by (bare or full-name) id."""
        name = memory_id if "/" in memory_id else f"{self._parent}/memories/{memory_id}"
        return self._request("GET", name)

    def _assert_owned_by_scope(self, memory_id: str, expected_scope: Dict[str, str]) -> None:
        """Fail-closed scope guard for mutating operations (forget/correct).

        A single reasoning engine can hold memories for many scopes (different
        users, different agents), and ADC credentials are typically broad
        enough to read/write any of them. Without this check, a caller could
        forget/correct a same-engine memory belonging to a DIFFERENT scope
        than the one this provider instance is configured for — the API layer
        alone does not enforce per-caller scope isolation. On any mismatch,
        missing scope, or lookup failure this raises and performs no mutation;
        callers must not catch it and continue.
        """
        try:
            memory = self.get_memory(memory_id)
        except MemoryBankError as e:
            raise MemoryBankError(
                f"Cannot verify memory scope before mutating (lookup failed): {e}") from e
        actual_scope = memory.get("scope")
        if not actual_scope or actual_scope != expected_scope:
            raise MemoryBankError(
                "Refusing to mutate: memory does not belong to the configured scope.")

    def delete(self, memory_id: str, *, scope: Dict[str, str]) -> None:
        self._assert_owned_by_scope(memory_id, scope)
        self._request("DELETE", f"{self._parent}/memories/{memory_id}")

    def correct(self, scope: Dict[str, str], memory_id: str, fact: str, *,
                max_attempts: int = 3) -> dict:
        """PATCH a memory's fact in place with exponential backoff.

        If the memory is missing (404), fall back to a consolidation write.
        Scope ownership is verified BEFORE any mutation (including the 404
        fallback path, which only regenerates — never patches — a memory that
        already failed the ownership check).
        """
        self._assert_owned_by_scope(memory_id, scope)
        last_err: Optional[Exception] = None
        for attempt in range(max_attempts):
            try:
                return self._request(
                    "PATCH", f"{self._parent}/memories/{memory_id}",
                    params={"updateMask": "fact"},
                    body={"fact": fact},
                )
            except MemoryBankError as e:
                last_err = e
                if "404" in str(e):
                    # Memory gone — recreate via consolidation pipeline.
                    return self.generate_from_fact(scope, fact, source="correct-fallback")
                time.sleep(0.5 * (2 ** attempt))
        raise MemoryBankError(f"correct failed after {max_attempts} attempts: {last_err}")

    def list_memories(self, scope: Dict[str, str], *,
                      names_only: bool = False) -> List[Dict[str, Any]]:
        """List all memories in scope (paginated). max pageSize=100 server-side."""
        all_items: List[Dict[str, Any]] = []
        page_token = None
        scope_filter = 'scope="%s"' % json.dumps(scope).replace('"', '\\"')
        while True:
            params = {"pageSize": 100, "filter": scope_filter}
            if names_only:
                params["$fields"] = "memories/name,nextPageToken"
            if page_token:
                params["pageToken"] = page_token
            result = self._request("GET", f"{self._parent}/memories", params=params)
            all_items.extend(result.get("memories", []))
            page_token = result.get("nextPageToken")
            if not page_token:
                break
        return all_items

    def count(self, scope: Dict[str, str]) -> int:
        """Count memories in scope (lightweight field-masked pagination)."""
        return len(self.list_memories(scope, names_only=True))


def _memory_id(resource_name: str) -> str:
    """Extract trailing id from .../memories/{id}."""
    return resource_name.rsplit("/", 1)[-1] if resource_name else ""
