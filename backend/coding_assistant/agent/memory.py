"""Per-workspace persistent memory: explicit corrections and preferences the
user states, saved so a later turn -- or a whole later session -- doesn't
repeat the same mistake or forget what the user already settled.

This is deliberately NOT the semantic/code retrieval layer discussed for
large-repo indexing (see docs/ARCHITECTURE.md's retrieval/ section, still
unbuilt: no embeddings, no vector store here). It's a flat, human-readable
file the model is told to consult and update -- the same idea as Claude
Code's own memory files (CLAUDE.md), just scoped to one workspace.
"""

from __future__ import annotations

from pathlib import Path

MEMORY_RELATIVE_PATH = Path(".coding-assistant") / "MEMORY.md"
# Kept small on purpose -- this is injected into every system prompt, and a
# huge memory file would eat into the same 16k budget conversation history
# competes for. Old notes are dropped from the top (oldest first) rather
# than refusing to save a new one.
MAX_MEMORY_CHARS = 4000

_HEADER = "# Coding Assistant Memory\n\nNotes the user has asked to be remembered across sessions.\n"


def memory_path(workspace_root: Path) -> Path:
    return workspace_root / MEMORY_RELATIVE_PATH


def load_memory(workspace_root: Path) -> str | None:
    """Returns the memory file's content, or None if it doesn't exist / is
    empty -- callers should skip the "known corrections" system-prompt
    section entirely in that case rather than show an empty one."""
    path = memory_path(workspace_root)
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    return text or None


def append_memory_note(workspace_root: Path, note: str) -> None:
    """Appends one note as a new bullet. Never overwrites existing notes --
    each call adds one line, oldest notes are dropped (not the file wiped)
    if the file grows past MAX_MEMORY_CHARS."""
    path = memory_path(workspace_root)
    path.parent.mkdir(parents=True, exist_ok=True)

    existing = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
    body = existing[len(_HEADER) :] if existing.startswith(_HEADER) else existing
    updated_body = body.rstrip() + f"\n- {note.strip()}\n"
    updated = _HEADER + updated_body

    if len(updated) > MAX_MEMORY_CHARS:
        # Keep the most recent notes -- drop whole bullet lines from the
        # front, never truncate mid-line (that would save a garbled note).
        lines = updated_body.strip("\n").split("\n")
        while lines and len(_HEADER) + sum(len(l) + 1 for l in lines) > MAX_MEMORY_CHARS:
            lines.pop(0)
        updated = _HEADER + "\n".join(lines) + "\n"

    path.write_text(updated, encoding="utf-8")
