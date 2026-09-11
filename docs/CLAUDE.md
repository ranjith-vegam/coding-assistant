# Coding Assistant — Project Context

A Claude-Code-like coding agent, built from scratch: a VS Code extension
(thin client) driving a local Python backend (agent loop, tools, retrieval)
that talks to an existing, separately-run model-orchestrator service. Backed
by locally hosted models (Qwen family) via that orchestrator — this project
does not host or serve models itself.

This file is written so a fresh Claude Code session opened in this directory
has full context without re-deriving anything from scratch. It reflects what
is **actually built and verified**, not aspirational design — every claim
below was checked against real code or a real live test at the time it was
written (last updated 2026-09-11).

## Architecture

```
coding-assitant/
├── backend/     Python, uv-managed, FastAPI + WebSocket
├── extension/   TypeScript, VS Code extension host + React webview
└── docs/        (currently just ARCHITECTURE.md, written early on --
                  this CLAUDE.md is the more current/authoritative doc now)
```

**External dependencies this project does NOT own, both already running:**
- **model-orchestrator** — `http://192.168.0.99:9900`, OpenAI-ish REST API
  (`/v1/chat/completions`, `/v1/embeddings`), serving `Qwen3.8-27B` (chat) and
  `bge-m3` (embeddings, dense+sparse). See "Known orchestrator quirks" below
  — its behavior is NOT standard OpenAI-compatible in several load-bearing ways.
- **Redis** — `redis://localhost:6336/0` (maps to a `redis-stack` container,
  `redis-stack-harshit`, host port 6336 → container 6379). Used for chat
  persistence. Plain string+JSON keys, not RedisJSON — works against any Redis.

Data flow for one message: VS Code extension → WebSocket → backend agent
loop → model-orchestrator (tool-call loop, possibly several round trips) →
results streamed back as discrete events → rendered in the React webview.

## What's actually built

### Backend (`backend/samixa_code/`)

**LLM client & parsing** (`llm/`)
- `client.py` — `ModelOrchClient`: `chat()` and `embed()` against the real
  orchestrator. Raises `ModelOrchError`, or the more specific
  `ContextLengthExceededError` when the 400 is specifically about context
  length (pattern-matched on the error message text).
- `toolcall_parser.py` — **load-bearing, not a stopgap.** The orchestrator
  passes the model's native Hermes-style `<tool_call><function=...>` tags
  straight through as plain text in `content`, and mixes reasoning
  (`</think>` marker, no reliable opening tag) into the same field. This
  module recovers structure from that. Confirmed permanent: the
  orchestrator is a shared multi-client service and will never parse tool
  calls for us. Tests are pinned to real captured responses, not synthetic
  examples — keep them that way if the orchestrator's output shape changes.
- `token_budget.py` — three-phase context-window trimming (see "Hard-won
  lessons" below for why all three phases exist and what happens without them).
- `types.py` — `ChatMessage` (role/content/tool_call_id/name/is_error),
  `ParsedAssistantMessage` (includes `prompt_tokens`/`completion_tokens` from
  the real `usage` block, used to self-calibrate the token estimator).

**Agent** (`agent/`)
- `loop.py` — `AgentLoop`: the actual tool-call loop (call model → execute
  tool calls → feed results back → repeat, bounded at `MAX_TOOL_TURNS=20`,
  then a forced tools-withheld wrap-up call so a stuck turn still produces
  *something* rather than silence). Owns: token-budget calibration (self-
  corrects from real `usage.prompt_tokens`, seeded pessimistic at 3.0x since
  the raw char-based estimate is confirmed unreliable — see below), the
  context-length retry loop (shrink-and-retry, the actual guarantee against
  overflow, not just the pre-emptive estimate), and per-turn checkpoints for
  rewind.
- `checkpoints.py` — `CheckpointStore`: one checkpoint per user turn,
  snapshotting a file's original content the FIRST time `write_file`/
  `edit_file` touches it within that turn (so restoring undoes the whole
  turn's changes to that file, not just the last edit). **RAM-only, never
  persisted** — lost on backend restart or reconnect. `run_command`/bash
  changes are deliberately NOT tracked (matches Claude Code's own documented
  limitation — arbitrary shell effects can't be reliably snapshotted/reversed).
- `memory.py` — `.samixa/MEMORY.md` in the **workspace itself** (not a temp
  file, renamed from `.coding-assistant/` during the "Samixa Code" rebrand):
  the `remember` tool appends notes here; loaded into every session's system
  prompt. This is genuinely persistent and version-controllable, unlike
  checkpoints.
- `project_doc.py` — the other half of the CLAUDE.md analogy: reads a
  root-level `SAMIXA.md` (static, human-authored — architecture,
  conventions, "how this repo works") fresh at the start of every chat
  session and folds it into the system prompt, same as memory but never
  written to by the assistant itself. Optional — sessions work fine without
  one, `load_project_doc` returns `None` if it's absent.
- `history_replay.py` — reconstructs frontend-displayable timeline items
  from a stored raw `ChatMessage` history (used when a chat is loaded from
  Redis). Re-parses each assistant message's raw content and pairs recovered
  tool_calls with the following "tool" messages **by position, not id** —
  `toolcall_parser.py` mints a fresh random id every parse, so a re-parsed
  id will never match the one that was live originally. Order is the only
  stable correspondence (and it is stable, by construction of `_execute_one`).
- `prompts.py` — system prompt, explicitly more repetitive/directive than
  you'd write for a frontier model (a ~30B local model is measurably less
  reliable at multi-step tool planning). Notably instructs "call at most ONE
  tool per response" — added after a live incident where the model bundled 6
  tool calls into one response and blew the context budget (see below);
  helps but isn't a complete fix, hence the structural token_budget work.
- `tools/` — `read_file`, `list_dir`, `search_code` (ripgrep), `write_file`,
  `edit_file`, `run_command`, `remember`. All file tools go through
  `resolve_in_workspace` (path-traversal guard). Every tool caps its output
  size hard (see `MAX_RETURNED_CHARS`/`MAX_OUTPUT_CHARS` in each) because of
  the 16k context window — these caps are load-bearing, not just tidiness.

**Persistence** (`chat_store.py`, `api/chat.py`)
- Redis schema: `coding-assistant:{user_id}:chat_ids` (ZSET, recency-ordered)
  and `coding-assistant:chat:{chat_id}` (JSON blob: title/timestamps/messages).
- `api/chat.py`'s `/ws/chat` WebSocket is the one entrypoint. One connection
  can move between chats (`new_chat`/`switch_chat`) without reconnecting — a
  `session` dict (not fixed local variables) holds whichever chat is
  currently active so the reader/turn-processor tasks always see the
  current one. History persists to Redis after every turn and every rewind.
- **Concurrency structure is load-bearing, not incidental**: reading from
  the WebSocket and running a turn are two separate `asyncio` tasks. A
  single `while True: receive_json()` loop that also awaits `run_turn()`
  inline deadlocks — `run_turn` blocks on an approval future that only the
  blocked receive loop could resolve. Cancel/rewind/new_chat/switch_chat/
  list_chats are all handled by the always-running reader task, applied to
  whatever's active in `session`.

**Full wire protocol** — see the docstring at the top of `api/chat.py` for
the authoritative, currently-accurate list of every message/event type
(`init`, `send`, `approval_response`, `cancel`, `rewind`, `new_chat`,
`switch_chat`, `list_chats` in; `status`, `message`, `tool_call`,
`tool_result`, `approval_request`, `checkpoint_created`, `rewound`,
`chat_ready`, `chat_list`, `cancelled`, `error`, `connection` out).

### Extension (`extension/`)

- `src/` — extension host (Node/TS): `extension.ts` (activation, commands),
  `chatPanel.ts` (webview host + message bridge; owns identity/session
  lifecycle — see below), `backendClient.ts` (WebSocket client, tracks
  connection status and active chat_id for reconnect), `identity.ts` (pure
  storage helpers, NO native prompts — see identity below).
- `webview/src/` — the React UI. Flat, IDE-native design modeled closely on
  Anthropic's own VS Code extension (verified against real screenshots
  fetched from their docs, not guessed): no chat bubbles, compact one-line
  tool-call rows (`● Read greeter.py`), a chat header with title + history
  dropdown + "+" new chat (mirrors their top bar), markdown rendering via
  `marked`+`DOMPurify`.
- **Identity is entirely in-webview** (`SignIn.tsx`), not a native VS Code
  input box — this was explicitly requested and corrected once already
  (don't regress it). `chatPanel.ts` defers connecting to the backend until
  identity is resolved: it checks `globalState` on mount, and if nothing's
  there, waits for a `submit_identity` message from the webview before
  constructing `BackendClient` at all.
- **Approval is a card inside the chat, not a native dialog** (`ApprovalCard.tsx`)
  — same reasoning, established early and consistently maintained.
- **Rewind button**: top-right of the user message card, hidden until
  hover (`.user-prompt-card:hover .rewind-button`), inline confirm (no
  native dialog). Historical (Redis-loaded) messages never get one —
  checkpoints are RAM-only, so a stale checkpoint_id would just fail; this
  is correct behavior, not a bug to "fix" by trying to persist checkpoints.

## Hard-won lessons (do not silently regress these)

1. **The context window is 16384 tokens TOTAL (input+output), confirmed
   live**, not a nominal/soft limit. A single `read_file` call, or a model
   bundling several tool calls into one response, WILL overflow it if not
   actively guarded. Three independent layers exist because the first two
   weren't enough on their own, verified by hitting the real 400 twice more
   after each earlier fix:
   - Drop whole old conversation turns, oldest first (`token_budget.py` phase 1).
   - Drop whole old tool-call rounds *within* the current turn if it alone
     is too big (phase 2) — added because a single long turn was eating the
     entire budget and (as a side effect) looked like "no memory between
     messages" since phase 1 alone was dropping everything old to compensate.
   - Shrink oversized tool-result *content* directly when even the
     un-droppable floor is still too big (phase 3) — added after discovering
     live that a model can bundle multiple tool calls into ONE response,
     making that whole bundle a single indivisible unit (can't drop one tool
     result without orphaning its tool_call tag), so message-level dropping
     alone had nothing left to trim.
   - On top of all three: a **reactive** shrink-and-retry loop on the actual
     `ContextLengthExceededError` (`MAX_CONTEXT_RETRIES` in `loop.py`) — this
     is the real guarantee. Pre-emptive estimation (even self-calibrated from
     real `usage.prompt_tokens`) is confirmed NOT reliable enough alone: the
     real/estimated gap behaves like a roughly fixed overhead, not a
     proportional one, so a single multiplicative calibration constant
     tuned from small requests can under-shoot for a big one it hasn't seen
     recently. Don't remove the reactive retry thinking calibration alone covers it.

2. **Deadlock class**: any change to `api/chat.py` that makes the WebSocket
   read loop also directly `await` a long-running turn will deadlock the
   moment an approval is needed mid-turn. Keep reading and turn-processing
   as separate tasks.

3. **The one-shot event race**: anything posted from the extension host to
   the webview via `postMessage` *before* the webview's `message` listener
   has attached is silently lost (no buffering). Both `connection` status
   and `identity` status are handled via a `ready`-request/response
   round-trip for exactly this reason — don't reintroduce a bare one-shot
   post for new host→webview state without the same pattern.

4. **CSS classes fighting each other looks like "invisible" or "odd" UI**,
   not necessarily a logic bug — the chat-header chevron bug (two classes
   sizing/positioning the same element differently) and the rewind-button
   visibility complaint were both this, not broken JS.

5. Tool-call ids are **not stable across a re-parse** — `toolcall_parser.py`
   mints a fresh random id every call. Never build matching logic (live or
   in `history_replay.py`) that assumes a re-parsed id equals the original.

## Known orchestrator quirks (not ours to fix, must route around)

- `stream: true` hangs indefinitely (confirmed: 90s+, zero bytes) rather
  than erroring. Streaming is disabled (`model_orch_streaming_enabled=false`).
- Tool calls arrive as raw text tags in `content`, not structured
  `tool_calls`/`finish_reason:"tool_calls"` — permanent, confirmed with the
  user: the orchestrator is shared across many clients and won't parse for us.
- Reasoning (`</think>` marker) is mixed into the same `content` field, not
  split into its own field.
- `/tokenize` returns 500 on real calls — no exact tokenizer available to us,
  hence the estimate+calibration+reactive-retry approach in `token_budget.py`.

## What's NOT built yet (deliberately deferred)

- Code retrieval/indexing (no embeddings/vector search — `retrieval/` is an
  empty stub package; `search_code`/`read_file` against the live filesystem
  is the whole story today, same as Claude Code's own zero-index approach).
- Native VS Code diff view for approvals (text preview only, no side-by-side
  diff editor tab).
- Fine-grained rewind (only "restore code + conversation together" exists).
- "Don't ask again" / auto-approve trust settings.
- Real authentication (identity is just an email-derived id, not verified).
- Token-by-token streaming (blocked on the orchestrator hang above).
- Persisted (non-RAM) checkpoints — a real limitation if reload-then-rewind
  is ever requested; would need checkpoints written to Redis alongside chats.

## Running it

```bash
# Backend
cd backend
uv sync --extra dev
cp .env.example .env   # already done in this checkout; edit if endpoints differ
uv run start           # binds 0.0.0.0:8765

# Extension (from VS Code, with extension/ as the opened folder)
cd extension
npm install
npm run compile        # or `npm run watch` during development
# F5 / Run and Debug -> "Run Extension" launches the Extension Development Host
```

Testing:
```bash
cd backend && make test         # 85 tests, pure unit/integration, fakeredis for Redis
cd extension && npm run compile # type-checks + bundles; no test runner configured yet
```

Live smoke-testing pattern used throughout this project's history (worth
reusing rather than reinventing): spin up a throwaway backend instance on a
**different port** than whatever the user has running (`uvicorn ... --port
87xx`), talk to it with a small `asyncio`/`websockets` script, tear down
after. Never touch a port already owned by a long-running instance without
confirming first (`fuser <port>/tcp`, check process start time) — this
project shares a machine with other long-running services.

## Packaging / sharing

```bash
cd extension && npm run package   # -> coding-assistant-0.1.0.vsix, ~740KB
```
`.vscodeignore` keeps this to just `package.json` + `dist/` (compiled
bundles only). A colleague installs via Extensions view → "…" → Install
from VSIX, but still needs a reachable backend + Redis + model-orchestrator
— see the last message in chat history for the full sharing writeup, or ask
for it again; it's not duplicated here since it doesn't affect how the code
itself works.

## Repo state as of writing

Single git history commit ("Coding Assistant"); working tree has uncommitted
changes on top of it as of 2026-09-11 (most recently: rewind-button
top-right/hover repositioning, composer hint text removal). Check `git
status`/`git diff` at the start of a new session rather than assuming HEAD
reflects everything described above.
