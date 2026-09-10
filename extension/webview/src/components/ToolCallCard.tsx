import { useState } from "react";
import { ApprovalCard } from "./ApprovalCard";
import { describeCall, summarizeResult } from "../toolPresentation";

interface Props {
  name: string;
  arguments: Record<string, unknown>;
  content: string | null;
  status: "pending" | "done" | "error";
  awaitingApproval: boolean;
  decision: "approved" | "denied" | null;
  onApprove: () => void;
  onDeny: () => void;
}

// A single compact line -- "● Read greeter.py" -- matching Anthropic's own
// VS Code extension (verified against its published screenshot) rather than
// a heavy bordered card. Full arguments/result are one "Show more" click
// away, in a scrollable block, never a native dialog for approval.
export function ToolCallCard({ name, arguments: args, content, status, awaitingApproval, decision, onApprove, onDeny }: Props) {
  const [expanded, setExpanded] = useState(false);
  const needsDecision = awaitingApproval && decision === null;
  const { verb, target } = describeCall(name, args);
  const dotClass = needsDecision ? "awaiting" : status;

  return (
    <div className="tool-row">
      <div className="tool-row-main">
        <span className={`tool-dot ${dotClass}`} aria-hidden="true" />
        <span className="tool-verb">{verb}</span>
        {target && <span className="tool-target">{target}</span>}
      </div>

      {needsDecision && <ApprovalCard name={name} arguments={args} onApprove={onApprove} onDeny={onDeny} />}

      {decision && <div className="tool-detail">{decision === "approved" ? "approved" : "denied by you"}</div>}

      {!needsDecision && (
        <div className="tool-detail-row">
          <span className="tool-detail">
            {content !== null ? summarizeResult(name, content) : status === "pending" ? "running…" : ""}
          </span>
          {(content !== null || Object.keys(args).length > 0) && (
            <button className="tool-link-btn" onClick={() => setExpanded((v) => !v)}>
              {expanded ? "Show less" : "Show more"}
            </button>
          )}
        </div>
      )}

      {expanded && (
        <div className="tool-expanded">
          <div className="tool-section-label">arguments</div>
          <pre className="tool-pre">{JSON.stringify(args, null, 2)}</pre>
          {content !== null && (
            <>
              <div className="tool-section-label">result</div>
              <pre className="tool-pre">{content}</pre>
            </>
          )}
        </div>
      )}
    </div>
  );
}
