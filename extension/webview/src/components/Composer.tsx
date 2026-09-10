import { KeyboardEvent, MutableRefObject, useEffect, useRef, useState } from "react";

interface Props {
  onSend: (text: string) => void;
  onCancel: () => void;
  connected: boolean;
  turnActive: boolean;
  // Imperative escape hatch so App can push text in (e.g. restoring a
  // prompt after a rewind, same as Claude Code handing the original prompt
  // back into the input) without fully lifting this component's text state.
  controlRef?: MutableRefObject<{ set: (text: string) => void } | null>;
}

const MAX_HEIGHT_PX = 200;

// One unified rounded card -- textarea on top, a slim toolbar row underneath
// -- matching Anthropic's own VS Code extension's composer shape. The send
// button morphs into a Stop button while a turn is in flight, same as
// Claude Code's own UX, so a runaway tool-call chain is always interruptible.
export function Composer({ onSend, onCancel, connected, turnActive, controlRef }: Props) {
  const [text, setText] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!controlRef) return;
    controlRef.current = {
      set: (value: string) => {
        setText(value);
        // autoGrow reads the DOM element directly; give React a tick to
        // apply the new value before measuring scrollHeight.
        requestAnimationFrame(() => {
          const el = textareaRef.current;
          if (el) {
            el.style.height = "auto";
            el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT_PX)}px`;
            el.focus();
          }
        });
      },
    };
    return () => {
      controlRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- controlRef identity is stable from App
  }, []);

  const send = () => {
    const trimmed = text.trim();
    if (!trimmed) return;
    onSend(trimmed);
    setText("");
    const el = textareaRef.current;
    if (el) el.style.height = "auto";
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (!turnActive) send();
    }
  };

  const autoGrow = () => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT_PX)}px`;
  };

  return (
    <div className="composer">
      <div className="composer-card">
        <textarea
          ref={textareaRef}
          className="composer-input"
          rows={1}
          placeholder={turnActive ? "Working… (Stop to interrupt)" : "Ask the coding assistant to do something…"}
          value={text}
          onChange={(event) => setText(event.target.value)}
          onInput={autoGrow}
          onKeyDown={handleKeyDown}
        />
        <div className="composer-toolbar">
          <span className="composer-connection" title={connected ? "Connected to backend" : "Reconnecting…"}>
            <span className={`composer-connection-dot ${connected ? "on" : "off"}`} />
            {connected ? "Connected" : "Reconnecting…"}
          </span>
          <span className="composer-hint">
            {turnActive ? "" : "Enter to send · Shift+Enter for a new line"}
          </span>
          {turnActive ? (
            <button className="send-button stop" onClick={onCancel} aria-label="Stop">
              <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true">
                <rect x="0" y="0" width="10" height="10" rx="1.5" fill="currentColor" />
              </svg>
            </button>
          ) : (
            <button className="send-button" onClick={send} disabled={!text.trim()} aria-label="Send message">
              <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                <path d="M2 8h11M9 4l4 4-4 4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
