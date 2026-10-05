# hermes-memory-vertex (deprecated)

> **This repository is deprecated.** The Hermes native Vertex AI Memory Bank
> provider now lives in
> [Shubhamsaboo/google-memorybank-plugin](https://github.com/Shubhamsaboo/google-memorybank-plugin)
> under [`hermes/vertex-memory/`](https://github.com/Shubhamsaboo/google-memorybank-plugin/tree/main/hermes/vertex-memory),
> alongside the OpenClaw plugin and Hermes MCP server it shares memories with.
> No further changes will land here.

## Migrate

```bash
# remove the old checkout
rm -rf ~/.hermes/plugins/memory/vertex-memory ~/.hermes/plugins/vertex-memory

# install the maintained provider
hermes plugins install Shubhamsaboo/google-memorybank-plugin/hermes/vertex-memory
hermes plugins enable vertex-memory
hermes config set memory.provider vertex-memory
```

Config carries over unchanged: same plugin name (`vertex-memory`), same keys,
same `$HERMES_HOME/vertex-memory/config.json` (legacy `vertex_memory.json` is
still read). Memories live in your Memory Bank instance, so nothing to export.

The maintained version adds stricter `memory_id` validation, project-number
alias handling, and correction recovery (restores the original fact if a
delete-and-regenerate fails).
