# coding-assistant-backend

Local agent backend for the VS Code coding assistant. Runs on the developer's
own machine (or a reachable dev box), talks to the existing model-orchestrator
service for chat completions and embeddings, and exposes a WebSocket API that
the VS Code extension drives.

This service does **not** host or serve models itself -- model orchestration
is handled elsewhere (see `MODEL_ORCH_BASE_URL`). This backend owns: the agent
loop, tool execution (filesystem/bash/search), the workspace retrieval index,
and the permission-approval flow.

## Development

```bash
uv sync                # install deps into .venv
cp .env.example .env   # fill in model-orchestrator URL/token
uv run start           # runs coding_assistant.main:main
```

## Layout

```
coding_assistant/
├── main.py            # FastAPI app + uvicorn entrypoint
├── settings.py         # env-driven configuration
├── api/                 # HTTP/WS routes the extension talks to
├── llm/                 # model-orchestrator client + tool-call/thinking parsing
├── agent/                # the tool-call loop, prompts, tool implementations
├── retrieval/            # workspace indexer + hybrid dense/sparse search
├── permissions/           # approval gate for risky tools (bash, write)
└── session/               # per-workspace session state
```

See `../docs/ARCHITECTURE.md` for the overall design and `Makefile` /
`deploy/systemd.service` for how this runs standalone or in Docker.
