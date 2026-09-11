import { useState } from "react";
import { createPortal } from "react-dom";

interface Props {
  text: string;
  canRewind: boolean;
  onRewind: () => void;
}

// The user's own message, shown as a quiet full-width card -- matching
// Anthropic's own VS Code extension, which does NOT right-align a chat
// bubble for the user. A Rewind control sits in the top-right corner of the
// card, revealed on hover (same placement convention as an edit/copy button
// on a chat message), modeled on Claude Code's own checkpoint/rewind
// feature: restores the workspace's files to their state before this
// message, and truncates the conversation back to here (the original text
// is handed back into the composer, matching Claude Code's own behavior).
//
// Icon-only (a circular-arrow glyph, no "Rewind" label) so it reads as a
// quiet corner control, not a labeled action competing with the message
// text. Confirmation is a centered modal over the whole panel (via a portal
// to <body>, so it isn't clipped by .log's overflow/scroll) instead of an
// inline confirm banner squeezed under one specific message.
export function UserPrompt({ text, canRewind, onRewind }: Props) {
  const [confirming, setConfirming] = useState(false);

  return (
    <div className="user-prompt-row">
      <div className={`user-prompt-card${canRewind ? " has-rewind" : ""}`}>
        <div className="user-prompt">{text}</div>
        {canRewind && (
          <button
            className={`rewind-button${confirming ? " pinned" : ""}`}
            onClick={() => setConfirming(true)}
            title="Restore code and conversation to before this message"
            aria-label="Restore code and conversation to before this message"
          >
            <svg width="13" height="13" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <path
                d="M3.5 8a4.5 4.5 0 1 1 1.5 3.35"
                stroke="currentColor"
                strokeWidth="1.4"
                strokeLinecap="round"
                fill="none"
              />
              <path d="M3.5 5v3h3" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" fill="none" />
            </svg>
          </button>
        )}
      </div>
      {confirming &&
        createPortal(
          <div className="modal-backdrop" onClick={() => setConfirming(false)}>
            <div className="modal-card" onClick={(event) => event.stopPropagation()}>
              <div className="modal-title">Rewind to here?</div>
              <div className="modal-body">
                This restores the workspace's files to their state before this message, and removes everything after
                it from the conversation.
              </div>
              <div className="modal-actions">
                <button className="modal-btn" onClick={() => setConfirming(false)}>
                  Cancel
                </button>
                <button
                  className="modal-btn primary"
                  onClick={() => {
                    setConfirming(false);
                    onRewind();
                  }}
                >
                  Rewind
                </button>
              </div>
            </div>
          </div>,
          document.body
        )}
    </div>
  );
}
