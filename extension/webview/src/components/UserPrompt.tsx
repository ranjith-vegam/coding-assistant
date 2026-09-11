import { useState } from "react";

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
          >
            <svg width="12" height="12" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <path d="M4 4.5A6 6 0 1 1 3 9" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" fill="none" />
              <path d="M4 2v3h3" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" fill="none" />
            </svg>
            Rewind
          </button>
        )}
      </div>
      {confirming && (
        <div className="rewind-confirm">
          <span>Rewind code + conversation to here?</span>
          <button
            className="tool-link-btn approve"
            onClick={() => {
              setConfirming(false);
              onRewind();
            }}
          >
            Yes, rewind
          </button>
          <button className="tool-link-btn" onClick={() => setConfirming(false)}>
            Cancel
          </button>
        </div>
      )}
    </div>
  );
}
