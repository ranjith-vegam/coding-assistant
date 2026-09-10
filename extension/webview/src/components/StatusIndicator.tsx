// A small spinning glyph + label -- matches the reference UI's "✻ Pondering…"
// treatment: one quiet inline row, not a bubble or a set of bouncing dots.
export function StatusIndicator() {
  return (
    <div className="status-row" aria-live="polite">
      <span className="status-spinner" aria-hidden="true">
        ✳
      </span>
      <span>Thinking…</span>
    </div>
  );
}
