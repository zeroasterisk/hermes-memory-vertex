# hermes-memory-vertex

A [Hermes Agent](https://github.com/NousResearch/hermes-agent) **memory-provider
plugin** backed by [Gemini Enterprise Agent Platform Memory Bank](https://docs.cloud.google.com/agent-builder/agent-engine/memory-bank/overview).
Gives your agent persistent, **cross-session and cross-agent** long-term memory —
managed by Google Cloud, with no vector DB to run.

> Inspired by [Shubhamsaboo/openclaw-vertexai-memorybank](https://github.com/Shubhamsaboo/openclaw-vertexai-memorybank)
> (the OpenClaw TypeScript plugin), ported to the Hermes Python `MemoryProvider` ABC.
> **Not** an officially supported Google product.

## Why

Hermes' built-in `MEMORY.md` / `USER.md` are file-backed and live in one profile.
This plugin adds **user-scoped memory that compounds over time** and is shared
across every agent/profile using the same scope:

- **Auto-recall** — before each turn, relevant memories are retrieved by
  similarity search and injected into context.
- **Auto-capture** — after each turn, the last user+assistant pair is sent to
  Memory Bank for server-side **fact extraction**, **deduplication**, and
  **contradiction resolution** (new facts update old ones in place).
- **Managed** — no embeddings, no vector store, no local DB. Your data stays in
  your GCP project.
- **Token-efficient** — memories are extracted *facts*, not raw transcripts.

## How it maps to Hermes

| Hermes `MemoryProvider` hook | Gemini Enterprise Agent Platform Memory Bank operation |
|---|---|
| `is_available()` | checks config present (no network) |
| `initialize()` | resolves scope from gateway `user_id`, lazy ADC token |
| `queue_prefetch()` / `prefetch()` | background `memories:retrieve`, cached |
| `sync_turn()` | background `memories:generate` (events) — fire-and-forget |
| `on_memory_write()` | mirrors built-in `MEMORY.md`/`USER.md` writes |
| `get_tool_schemas()` | `memorybank_search/remember/forget/correct/stats` |

## Prerequisites

1. A GCP project with the **Vertex AI API** enabled and billing on.
2. **Application Default Credentials** available to Hermes:
   ```bash
   gcloud auth application-default login
   # or point GOOGLE_APPLICATION_CREDENTIALS at a service-account key
   ```
   The principal needs `aiplatform.*` (Vertex AI User or Agent Platform admin/user is sufficient).
3. A **Gemini Enterprise Agent Platform** instance (provides the `reasoning_engine_id`):
   ```bash
   pip install "google-cloud-aiplatform>=1.111.0"
   python create_engine.py --project YOUR_PROJECT --location us-central1
   ```
   Copy the printed `reasoning_engine_id`.

## Install

```bash
# Clone into your Hermes plugins dir (or a category subfolder)
git clone https://github.com/zeroasterisk/hermes-memory-vertex \
  ~/.hermes/plugins/memory/vertex-memory

# Configure (writes $HERMES_HOME/vertex_memory.json; ADC = no secret stored)
hermes memory setup     # pick "vertex-memory" and answer the prompts
# …or set it directly:
hermes config set memory.provider vertex-memory
```

Minimal `$HERMES_HOME/vertex_memory.json`:
```json
{
  "project_id": "your-gcp-project",
  "location": "us-central1",
  "reasoning_engine_id": "1234567890",
  "scope_key": "user_id",
  "top_k": 10
}
```

Restart Hermes. Verify:
```bash
hermes vertex-memory status
```

## Configuration

| Key | Required | Default | Description |
|---|---|---|---|
| `project_id` | ✅ | — | GCP project id |
| `location` | ✅ | `us-central1` | GCP region |
| `reasoning_engine_id` | ✅ | — | Agent Engine reasoning engine id |
| `scope_key` | | `user_id` | scope dimension (`user_id` = cross-agent sharing) |
| `scope_value` | | gateway `user_id` ⇒ `hermes-user` | static scope value for CLI |
| `top_k` | | `10` | max memories per recall |
| `max_distance` | | none | relevance cutoff (lower = stricter) |

All settings may also be supplied via env vars: `VERTEX_MEMORY_PROJECT_ID`,
`VERTEX_MEMORY_LOCATION`, `VERTEX_MEMORY_ENGINE_ID`, `VERTEX_MEMORY_SCOPE_KEY`,
`VERTEX_MEMORY_SCOPE_VALUE`, `VERTEX_MEMORY_TOP_K`, `VERTEX_MEMORY_MAX_DISTANCE`.

### Scoping (important)

`scope` controls **both** who can see a memory **and** what gets consolidated
together — matching is *exact on all keys* and **immutable** per memory. Use
`scope_key: user_id` (the default) to share memory across all your agents for
the same user. Choose your scoping before backfilling.

## Agent tools

| Tool | What it does |
|---|---|
| `memorybank_search` | semantic search → facts + ids + scores |
| `memorybank_remember` | store a durable fact (via consolidation) |
| `memorybank_forget` | delete a memory by id |
| `memorybank_correct` | update a memory's fact in place (PATCH, falls back to create) |
| `memorybank_stats` | total memory count + scope |

## CLI

```bash
hermes vertex-memory status
hermes vertex-memory search "deployment region" --top-k 5 --show-ids
hermes vertex-memory list --count-only
hermes vertex-memory remember "Deploys use us-central1"
hermes vertex-memory forget 1234567890
```

## Privacy

Auto-capture sends the **last user+assistant message pair** to your Vertex AI
Memory Bank instance for extraction. Content stays within your GCP project.
Set `memory.provider` back to `builtin` to disable.

## Pricing (2026)

Storage ~$0.25 / 1k memories / mo · Retrieval ~$0.50 / 1k returned (first
1k/mo free) · Generation = Gemini token cost only. See
[Vertex AI pricing](https://cloud.google.com/vertex-ai/pricing#vertex-ai-agent-engine).

## Development

```bash
pip install -r requirements-dev.txt
pytest -q              # runs fully mocked — no GCP calls
```

## License

[MIT](LICENSE)
