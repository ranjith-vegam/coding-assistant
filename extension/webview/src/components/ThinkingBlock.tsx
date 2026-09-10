import { useState } from "react";

// Collapsed by default -- reasoning traces are useful to check but not what
// you want to read every turn. The body scrolls internally (max-height +
// overflow-y: auto) instead of growing unbounded, so a long reasoning trace
// is fully readable rather than clipped against the panel's own scroll area.
export function ThinkingBlock({ text }: { text: string }) {
  const [open, setOpen] = useState(false);

  return (
    <div className={`thinking-card${open ? " open" : ""}`}>
      <button className="thinking-summary" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <span className="chevron" aria-hidden="true">
          ▸
        </span>
        <span>Thinking</span>
      </button>
      {open && <div className="thinking-body">{text}</div>}
    </div>
  );
}
