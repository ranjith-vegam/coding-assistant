// Wire types shared between the extension host (src/) and the webview
// (webview/src/) -- kept dependency-free (no `vscode`, no `ws`) so it can be
// imported from both a Node context and a browser-sandboxed webview context.
// Mirrors backend/coding_assistant/api/chat.py's wire protocol exactly.

// One reconstructed timeline entry from a stored chat -- see the backend's
// agent/history_replay.py for how these are built from raw history. Shaped
// closely to (but not identical to -- no live "pending" states here) the
// webview's own TimelineItem.
export type ReplayItem =
  | { kind: "user"; id: string; text: string }
  | { kind: "assistant"; id: string; text: string; thinking: string | null }
  | { kind: "tool"; id: string; name: string; arguments: Record<string, unknown>; content: string | null; is_error: boolean };

export interface ChatSummary {
  chat_id: string;
  title: string;
  workspace_root: string;
  updated_at: number;
}

export type BackendEvent =
  | { type: "status"; status: "thinking" }
  | { type: "message"; text: string; thinking: string | null; final: boolean }
  | { type: "tool_call"; id: string; name: string; arguments: Record<string, unknown> }
  | { type: "tool_result"; id: string; name: string; content: string; is_error: boolean }
  | { type: "approval_request"; id: string; name: string; arguments: Record<string, unknown> }
  | { type: "checkpoint_created"; id: string }
  | {
      type: "rewound";
      checkpoint_id: string;
      restored_code: boolean;
      restored_conversation: boolean;
      restored_files: string[];
      skipped_files: string[];
    }
  | { type: "chat_ready"; chat_id: string; title: string; items: ReplayItem[] }
  // Sent once, right after a chat's first turn completes, when a real
  // (LLM-generated -- see backend agent/title.py) title replaces "New Chat".
  // ALSO sent any time in response to a client "rename_chat" (a manual
  // rename), not just the one-time auto-generated case.
  | { type: "chat_renamed"; chat_id: string; title: string }
  | { type: "chat_deleted"; chat_id: string }
  | { type: "chat_list"; chats: ChatSummary[] }
  | { type: "cancelled" }
  | { type: "error"; message: string }
  | { type: "connection"; status: "open" | "closed" }
  // Not actually from the Python backend -- posted by chatPanel.ts itself,
  // over the same channel, to tell the webview whether an identity is
  // already stored (so it can skip straight to chat) or the sign-in form
  // needs to be shown. email/token are both null until one is saved.
  | { type: "identity"; email: string | null; token: string | null };

// Messages the webview posts back to the extension host. The approval
// decision is made in-webview (inline in the tool-call card, not a native
// dialog) and relayed to the backend as-is -- the host does no UI of its own
// for this any more.
export type WebviewOutboundMessage =
  | { type: "send"; text: string }
  | { type: "approval_response"; id: string; approved: boolean }
  | { type: "cancel" }
  | { type: "rewind"; checkpoint_id: string; restore_code: boolean; restore_conversation: boolean }
  | { type: "new_chat" }
  | { type: "switch_chat"; chat_id: string }
  | { type: "list_chats" }
  | { type: "delete_chat"; chat_id: string }
  | { type: "rename_chat"; chat_id: string; title: string }
  // Submitted from the in-webview sign-in form (see SignIn.tsx) -- NOT a
  // native VS Code input box. chatPanel.ts persists it and only then starts
  // the actual backend connection.
  | { type: "submit_identity"; email: string }
  // Posted once on mount -- lets the host reply with the CURRENT connection
  // AND identity status instead of the webview relying on catching a
  // one-shot event at exactly the right moment (see backendClient.ts).
  | { type: "ready" };
