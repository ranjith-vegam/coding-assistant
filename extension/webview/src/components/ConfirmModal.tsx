import { createPortal } from "react-dom";

interface Props {
  title: string;
  body: string;
  confirmLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
  // Red confirm button for a destructive/irreversible action (delete) --
  // the default (accent-colored) reads as neutral/constructive (rewind).
  danger?: boolean;
}

// A centered overlay (portaled to <body>, so it sits above the whole panel
// regardless of scroll position and isn't clipped by any ancestor's
// overflow) for any "are you sure?" action -- shared by the rewind
// confirmation (UserPrompt.tsx) and chat deletion (ChatHeader.tsx) instead
// of each rolling its own inline confirm banner.
export function ConfirmModal({ title, body, confirmLabel, onConfirm, onCancel, danger }: Props) {
  return createPortal(
    <div className="modal-backdrop" onClick={onCancel}>
      <div className="modal-card" onClick={(event) => event.stopPropagation()}>
        <div className="modal-title">{title}</div>
        <div className="modal-body">{body}</div>
        <div className="modal-actions">
          <button className="modal-btn" onClick={onCancel}>
            Cancel
          </button>
          <button className={`modal-btn primary${danger ? " danger" : ""}`} onClick={onConfirm}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>,
    document.body
  );
}
