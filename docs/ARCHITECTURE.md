# Architecture

A Claude-Code-like coding agent: a VS Code extension (thin client) driving a
local Python backend (agent loop, tools, retrieval), which talks to an
external model-orchestrator for chat completions and embeddings. This backend
does not host or serve models -- that's a separate, already-running service.

```
extension/  (TypeScript, VS Code)
  src/extension.ts     -- activation, registers "Coding Assistant: Open Chat"
  src/chatPanel.ts      -- webview chat UI (v0: plain text turns only)
  src/backendClient.ts   -- WebSocket client for the backend's /ws/chat

backend/  (Python, uv-managed)
  coding_assistant/
    main.py              -- FastAPI app + uvicorn entrypoint
    settings.py            -- env-driven config (.env)
    api/
      health.py             -- GET /health
      chat.py                -- WS /ws/chat (v0 plain passthrough -- see below)
    llm/
      types.py                -- ChatMessage/ToolDefinition/ParsedAssistantMessage/...
      toolcall_parser.py       -- recovers tool calls + strips thinking from raw text
      client.py                 -- ModelOrchClient: chat() + embed()
    agent/                       -- NOT YET BUILT: the tool-call loop + prompts
    agent/tools/                  -- NOT YET BUILT: read_file/write_file/bash/search_code
    retrieval/                     -- NOT YET BUILT: chunking + hybrid dense/sparse index
    permissions/                    -- NOT YET BUILT: approval gate for risky tools
    session/                         -- NOT YET BUILT: per-workspace session state
```

## What's real vs. scaffolded today

**Built and tested end-to-end** (extension -> backend -> model-orchestrator,
verified against the live orchestrator at http://192.168.0.99:9900):
- `llm/client.py` + `llm/toolcall_parser.py` -- the model-orchestrator client
  and the parser that recovers structured tool calls and split-out thinking
  text from its raw response. This is the one piece of the whole system that
  is NOT a thin wrapper over a clean contract -- see the docstring at the top
  of `toolcall_parser.py` for exactly what's non-standard about the
  orchestrator's response shape and why it's permanent, not a stopgap.
- `api/chat.py` -- a plain chat relay over WebSocket. No tool execution yet:
  it just forwards user turns to model-orch and returns the parsed answer.
  This exists to prove the wire end-to-end before the agent loop replaces it.
- The extension's chat panel, talking to that endpoint over a real WebSocket
  connection, rendering turns and a "thinking..." status indicator.

**Not built yet** (next pieces, in dependency order):
1. `agent/tools/` -- read_file, write_file/edit_file, bash (sandboxed), search_code (grep), list_dir.
2. `agent/loop.py` -- the actual tool-call loop: call the model with tools ->
   execute any `ParsedToolCall`s -> feed results back as role="tool" messages
   -> repeat until a turn has no tool calls. `api/chat.py` gets replaced by
   this, not extended in place.
3. `permissions/gate.py` -- approval flow for bash/write, wired into the loop
   before those tools execute, with the extension surfacing the approve/deny
   prompt.
4. `retrieval/` -- tree-sitter chunking, bge-m3 dense+sparse embedding (via
   the same ModelOrchClient.embed already built), a lightweight vector store
   (sqlite-vec/LanceDB), lazy directory-scoped indexing for large monorepos.

## Known orchestrator gaps (confirmed by hand, not assumed)

See `llm/toolcall_parser.py` docstring and `settings.py` for the two load-bearing
ones (unstructured tool calls, thinking mixed into content). One more, tracked
here rather than in code since nothing consumes it yet:
- `stream: true` on `/v1/chat/completions` hangs indefinitely (confirmed:
  90s+, zero bytes) rather than erroring. `model_orch_streaming_enabled` in
  settings.py is off and should stay off until this is fixed upstream. The
  chat panel's "thinking..." status message is the interim-signal workaround
  until real token streaming is possible.

## Deploy

`backend/Makefile` has both Docker targets (build/docker-run/...) and systemd
targets (install/start/restart/...), mirroring the rest of this AI platform's
services (see `backend/deploy/systemd.service`). One thing that's different
from a typical stateless API service here: the backend's tools need direct
filesystem access to whatever workspace VS Code has open, so the systemd
(native `uv run start`, same machine as the editor) path is the primary one --
the Docker path only makes sense with the workspace bind-mounted in at a
matching path (see `docker-compose.yml`).
