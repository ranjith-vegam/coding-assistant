"""Per-project static context: a human-authored SAMIXA.md at the workspace
root, read once when a chat session starts and folded into the system
prompt.

This is the other half of the CLAUDE.md analogy -- see agent/memory.py's
docstring. The split:
  - SAMIXA.md   (this file)   -- static, human-authored, edited rarely.
                                  Architecture, conventions, "how this repo
                                  works". Re-read fresh every session start,
                                  never modified by the assistant itself.
  - .samixa/MEMORY.md (memory.py) -- dynamic, tool-appended. Specific
                                  corrections/preferences learned mid-session.

Both get folded into the same system prompt (see agent/prompts.py), but
kept as separate files/sections deliberately -- conflating "how the repo
works" with "things I was told not to repeat" would make either harder to
skim and edit by hand.
"""

from __future__ import annotations

from pathlib import Path

PROJECT_DOC_RELATIVE_PATH = Path("SAMIXA.md")
# Same reasoning as MAX_MEMORY_CHARS: this is injected into every system
# prompt on top of conversation history, against the same 16k budget. A
# long SAMIXA.md is truncated (from the end) rather than blowing the
# context window silently -- better a partial doc than none, and better an
# obvious "(truncated)" note than a mysteriously-cut-off model.
MAX_PROJECT_DOC_CHARS = 6000


def project_doc_path(workspace_root: Path) -> Path:
    return workspace_root / PROJECT_DOC_RELATIVE_PATH


def load_project_doc(workspace_root: Path) -> str | None:
    """Returns SAMIXA.md's content (truncated to MAX_PROJECT_DOC_CHARS if
    needed), or None if it doesn't exist / is empty -- callers should skip
    the system-prompt section entirely in that case rather than show an
    empty one."""
    path = project_doc_path(workspace_root)
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return None
    if len(text) > MAX_PROJECT_DOC_CHARS:
        text = text[:MAX_PROJECT_DOC_CHARS] + "\n... (truncated -- SAMIXA.md is longer than fits here)"
    return text
