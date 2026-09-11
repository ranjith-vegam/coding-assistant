"""Per-session checkpoints: a snapshot of on-disk file state captured right
before each user turn, so a rewind can restore code (and conversation) back
to before a request that went wrong -- modeled on Claude Code's own
checkpoint/rewind feature (confirmed against its docs, 2026-09-10):
checkpoints are created per user prompt, restoring reverts tracked files and
optionally truncates the conversation back to that point.

Same limitation Claude Code has, deliberately: only write_file/edit_file are
tracked. Bash/run_command changes are NOT captured -- arbitrary shell effects
(deleted files, moved files, external state) can't be reliably snapshotted
or reversed generically, so pretending to support that would be dishonest.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Checkpoint:
    id: str
    # Monotonic creation order -- used for discard_after instead of
    # created_at (wall-clock time.time() can collide for checkpoints created
    # in the same tick; this can't).
    seq: int
    # Index into the session's `history` list of the user message this
    # checkpoint precedes -- restoring the conversation truncates back to here.
    history_index: int
    # repo-relative path -> original content, or None if the file didn't exist
    # yet. Populated lazily: the FIRST time a file is touched within this
    # checkpoint's turn, so restoring undoes the whole turn's changes to it,
    # not just its last edit.
    file_snapshots: dict[str, str | None] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


@dataclass
class RestoreResult:
    restored: list[str]
    skipped: list[str]


class CheckpointStore:
    def __init__(self) -> None:
        self._checkpoints: list[Checkpoint] = []
        self._next_id = 0

    def start_checkpoint(self, history_index: int) -> Checkpoint:
        checkpoint = Checkpoint(id=f"ckpt_{self._next_id}", seq=self._next_id, history_index=history_index)
        self._next_id += 1
        self._checkpoints.append(checkpoint)
        return checkpoint

    def get(self, checkpoint_id: str) -> Checkpoint | None:
        return next((c for c in self._checkpoints if c.id == checkpoint_id), None)

    def record_pre_edit_state(self, checkpoint: Checkpoint, path: Path, workspace_root: Path) -> None:
        rel = str(path.resolve().relative_to(workspace_root.resolve()))
        if rel in checkpoint.file_snapshots:
            return
        checkpoint.file_snapshots[rel] = (
            path.read_text(encoding="utf-8", errors="replace") if path.is_file() else None
        )

    def discard_after(self, checkpoint_id: str) -> None:
        """Drops checkpoints created after this one -- once rewound past them
        they refer to turns that no longer exist."""
        target = self.get(checkpoint_id)
        if target is None:
            return
        self._checkpoints = [c for c in self._checkpoints if c.seq <= target.seq]


def restore_files(checkpoint: Checkpoint, workspace_root: Path) -> RestoreResult:
    restored: list[str] = []
    skipped: list[str] = []
    for rel_path, original_content in checkpoint.file_snapshots.items():
        target = workspace_root / rel_path
        try:
            if original_content is None:
                if target.exists():
                    target.unlink()
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(original_content, encoding="utf-8")
            restored.append(rel_path)
        except OSError:
            skipped.append(rel_path)
    return RestoreResult(restored=restored, skipped=skipped)
