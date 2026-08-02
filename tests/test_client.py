"""Tests for VertexMemoryBankClient — HTTP shapes mocked, no GCP calls."""

from __future__ import annotations

import json
from unittest import mock

import pytest

from client import VertexMemoryBankClient, MemoryBankError, _memory_id


class FakeResp:
    def __init__(self, status=200, payload=None, text=None):
        self.status_code = status
        self.ok = 200 <= status < 300
        self._payload = payload if payload is not None else {}
        self.text = text if text is not None else json.dumps(self._payload)

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


@pytest.fixture
def client():
    c = VertexMemoryBankClient("proj", "us-central1", "eng123")
    # Bypass real ADC.
    c._token = lambda: "fake-token"  # type: ignore
    return c


def _last_call(m):
    """Return (method, url, kwargs) of the last requests.request call."""
    args, kwargs = m.call_args
    return args[0], args[1], kwargs


def test_init_requires_all_fields():
    with pytest.raises(MemoryBankError):
        VertexMemoryBankClient("", "us-central1", "eng")


def test_parent_and_base(client):
    assert client._parent == "projects/proj/locations/us-central1/reasoningEngines/eng123"
    assert client._base == "https://us-central1-aiplatform.googleapis.com/v1beta1"


def test_global_location_parent_and_base():
    c = VertexMemoryBankClient("proj", "global", "eng123")
    assert c._parent == "projects/proj/locations/global/reasoningEngines/eng123"
    assert c._base == "https://global-aiplatform.googleapis.com/v1beta1"


def test_memory_id_helper():
    assert _memory_id("projects/p/locations/l/reasoningEngines/e/memories/999") == "999"
    assert _memory_id("") == ""


def test_retrieve_shape_and_parsing(client):
    payload = {"retrievedMemories": [
        {"memory": {"fact": "likes elixir", "name": ".../memories/1"}, "distance": 0.1},
        {"memory": {"fact": "uses uv", "name": ".../memories/2"}, "distance": 0.9},
    ]}
    with mock.patch("requests.request", return_value=FakeResp(payload=payload)) as m:
        out = client.retrieve({"user_id": "alan"}, "tooling", top_k=7)
    method, url, kw = _last_call(m)
    assert method == "POST"
    assert url.endswith("/memories:retrieve")
    assert kw["json"]["scope"] == {"user_id": "alan"}
    assert kw["json"]["similaritySearchParams"] == {"searchQuery": "tooling", "topK": 7}
    assert [o["fact"] for o in out] == ["likes elixir", "uses uv"]
    assert out[0]["id"] == "1"


def test_retrieve_max_distance_filters(client):
    payload = {"retrievedMemories": [
        {"memory": {"fact": "close", "name": "x/memories/1"}, "distance": 0.1},
        {"memory": {"fact": "far", "name": "x/memories/2"}, "distance": 0.8},
    ]}
    with mock.patch("requests.request", return_value=FakeResp(payload=payload)):
        out = client.retrieve({"user_id": "a"}, "q", max_distance=0.5)
    assert [o["fact"] for o in out] == ["close"]


def test_generate_from_conversation_role_mapping(client):
    with mock.patch("requests.request", return_value=FakeResp(payload={})) as m:
        client.generate_from_conversation(
            {"user_id": "a"},
            [{"role": "user", "content": "hi"},
             {"role": "assistant", "content": "hello"}],
        )
    _, url, kw = _last_call(m)
    assert url.endswith("/memories:generate")
    events = kw["json"]["direct_contents_source"]["events"]
    assert events[0]["content"]["role"] == "user"
    assert events[1]["content"]["role"] == "model"  # assistant → model
    assert kw["json"]["revision_labels"]["source"] == "capture"


def test_generate_from_conversation_truncates(client):
    long_text = "x" * 5000
    with mock.patch("requests.request", return_value=FakeResp(payload={})) as m:
        client.generate_from_conversation(
            {"u": "a"}, [{"role": "user", "content": long_text}])
    _, _, kw = _last_call(m)
    text = kw["json"]["direct_contents_source"]["events"][0]["content"]["parts"][0]["text"]
    assert len(text) == 4000


def test_generate_from_conversation_empty_noop(client):
    with mock.patch("requests.request") as m:
        out = client.generate_from_conversation({"u": "a"}, [])
    assert out == {}
    m.assert_not_called()


def test_generate_from_fact_wait_counts(client):
    payload = {"generatedMemories": [
        {"action": "CREATED"}, {"action": "UPDATED"}, {"action": "CREATED"}]}
    with mock.patch("requests.request", return_value=FakeResp(payload=payload)) as m:
        out = client.generate_from_fact({"u": "a"}, "a fact", wait=True)
    _, url, kw = _last_call(m)
    assert url.endswith("/memories:generate")
    assert kw["json"]["direct_memories_source"]["direct_memories"] == [{"fact": "a fact"}]
    assert out == {"created": 2, "updated": 1, "total": 3}


def test_generate_from_fact_fire_and_forget(client):
    with mock.patch("requests.request", return_value=FakeResp(payload={})):
        out = client.generate_from_fact({"u": "a"}, "fact", wait=False)
    assert out == {"queued": True}


def test_delete(client):
    with mock.patch("requests.request", return_value=FakeResp(status=200, text="")) as m:
        client.delete("42")
    method, url, _ = _last_call(m)
    assert method == "DELETE"
    assert url.endswith("/memories/42")


def test_correct_patch_shape(client):
    with mock.patch("requests.request", return_value=FakeResp(payload={})) as m:
        client.correct({"u": "a"}, "7", "new fact")
    method, url, kw = _last_call(m)
    assert method == "PATCH"
    assert url.endswith("/memories/7")
    assert kw["params"] == {"updateMask": "fact"}
    assert kw["json"] == {"fact": "new fact"}


def test_correct_404_falls_back_to_generate(client):
    calls = []

    def fake_request(method, url, **kw):
        calls.append((method, url))
        if method == "PATCH":
            return FakeResp(status=404, text="not found")
        return FakeResp(payload={"generatedMemories": [{"action": "CREATED"}]})

    with mock.patch("requests.request", side_effect=fake_request):
        client.correct({"u": "a"}, "missing", "new")
    assert any(m == "PATCH" for m, _ in calls)
    assert any(u.endswith("/memories:generate") for _, u in calls)


def test_error_raises(client):
    with mock.patch("requests.request",
                    return_value=FakeResp(status=403, text="denied")):
        with pytest.raises(MemoryBankError) as ei:
            client.retrieve({"u": "a"}, "q")
    assert "403" in str(ei.value)


def test_count_paginates(client):
    pages = [
        FakeResp(payload={"memories": [{"name": "x/1"}, {"name": "x/2"}],
                          "nextPageToken": "tok"}),
        FakeResp(payload={"memories": [{"name": "x/3"}]}),
    ]
    with mock.patch("requests.request", side_effect=pages) as m:
        n = client.count({"user_id": "a"})
    assert n == 3
    # second page must carry the page token
    second_kw = m.call_args_list[1].kwargs
    assert second_kw["params"]["pageToken"] == "tok"
    assert second_kw["params"]["$fields"] == "memories/name,nextPageToken"


def test_list_scope_filter_escaped(client):
    with mock.patch("requests.request",
                    return_value=FakeResp(payload={"memories": []})) as m:
        client.list_memories({"user_id": "alan"})
    _, _, kw = _last_call(m)
    assert 'scope=' in kw["params"]["filter"]
    assert "user_id" in kw["params"]["filter"]
