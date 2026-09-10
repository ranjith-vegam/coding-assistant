import { useEffect } from "react";
import { describeCall } from "../toolPresentation";

interface Props {
  name: string;
  arguments: Record<string, unknown>;
  onApprove: () => void;
  onDeny: () => void;
}

function questionFor(name: string, args: Record<string, unknown>): string {
  const { target } = describeCall(name, args);
  switch (name) {
    case "write_file":
      return `Create or overwrite ${target || "this file"}?`;
    case "edit_file":
      return `Make this edit to ${target || "this file"}?`;
    case "run_command":
      return "Run this command?";
    default:
      return `Allow ${name}?`;
  }
}

function Preview({ name, arguments: args }: { name: string; arguments: Record<string, unknown> }) {
  if (name === "edit_file") {
    return (
      <div className="approval-diff">
        {"old_string" in args && <pre className="approval-diff-old">- {String(args.old_string ?? "")}</pre>}
        {"new_string" in args && <pre className="approval-diff-new">+ {String(args.new_string ?? "")}</pre>}
      </div>
    );
  }
  if (name === "write_file") {
    return <pre className="approval-diff-new">{String(args.content ?? "")}</pre>;
  }
  if (name === "run_command") {
    return <pre className="approval-command">$ {String(args.command ?? "")}</pre>;
  }
  return <pre className="approval-fallback">{JSON.stringify(args, null, 2)}</pre>;
}

// Modeled on Anthropic's own VS Code extension's edit-approval prompt
// (verified against a real screenshot): a distinct, prominent card -- not an
// inline row -- with a bold question, a diff-style preview of the actual
// change, and full-width stacked actions with keyboard-shortcut hints.
export function ApprovalCard({ name, arguments: args, onApprove, onDeny }: Props) {
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      const key = event.key.toLowerCase();
      if (key === "1" || key === "y") {
        event.preventDefault();
        onApprove();
      } else if (key === "2" || key === "n" || key === "escape") {
        event.preventDefault();
        onDeny();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onApprove, onDeny]);

  return (
    <div className="approval-card">
      <div className="approval-card-question">{questionFor(name, args)}</div>
      <Preview name={name} arguments={args} />
      <div className="approval-card-actions">
        <button className="approval-card-btn primary" onClick={onApprove}>
          <span className="key-hint">1</span> Approve
        </button>
        <button className="approval-card-btn" onClick={onDeny}>
          <span className="key-hint">2</span> Deny
        </button>
      </div>
    </div>
  );
}
