import { Fragment, useEffect, useReducer, useRef } from "react";
import { BackendEvent, ChatSummary, ReplayItem } from "../../shared/protocol";
import { AssistantText } from "./components/AssistantText";
import { ChatHeader } from "./components/ChatHeader";
import { Composer } from "./components/Composer";
import { SignIn } from "./components/SignIn";
import { StatusIndicator } from "./components/StatusIndicator";
import { ThinkingBlock } from "./components/ThinkingBlock";
import { ToolCallCard } from "./components/ToolCallCard";
import { UserPrompt } from "./components/UserPrompt";
import { vscodeApi } from "./vscodeApi";

type ToolStatus = "pending" | "done" | "error";
type Decision = "approved" | "denied" | null;

type TimelineItem =
  | { kind: "user"; id: string; text: string; checkpointId: string | null }
  | { kind: "assistant"; id: string; text: string; thinking: string | null }
  | {
      kind: "tool";
      id: string;
      name: string;
      arguments: Record<string, unknown>;
      content: string | null;
      status: ToolStatus;
      awaitingApproval: boolean;
      decision: Decision;
    }
  | { kind: "error"; id: string; message: string }
  | { kind: "note"; id: string; text: string };

interface State {
  items: TimelineItem[];
  thinking: boolean;
  connected: boolean;
  turnActive: boolean;
  // Set by the "rewound" case below (which has full access to current state,
  // unlike the message-listener's stale closure) and consumed by an effect
  // that resets the composer's text -- see the comment on that effect.
  restoredComposerText: string | null;
  chatId: string | null;
  chatTitle: string;
  chats: ChatSummary[];
  // "loading" until the host's "ready" reply lands -- kept distinct from
  // "needed" so the sign-in form doesn't flash on screen for an instant
  // before the host confirms an identity is already stored.
  identityStatus: "loading" | "needed" | "ready";
}

function replayItemToTimelineItem(item: ReplayItem): TimelineItem {
  if (item.kind === "user") {
    // Historical items loaded from Redis have no live checkpoint -- rewind
    // is only possible for the current in-memory session (checkpoints are
    // RAM-only on the backend, see agent/checkpoints.py), so this correctly
    // hides the Rewind button on reloaded history rather than showing one
    // that would just fail.
    return { kind: "user", id: item.id, text: item.text, checkpointId: null };
  }
  if (item.kind === "assistant") {
    return { kind: "assistant", id: item.id, text: item.text, thinking: item.thinking };
  }
  return {
    kind: "tool",
    id: item.id,
    name: item.name,
    arguments: item.arguments,
    content: item.content,
    status: item.is_error ? "error" : item.content !== null ? "done" : "pending",
    awaitingApproval: false,
    decision: null,
  };
}

type Action = { type: "backend"; event: BackendEvent } | { type: "userSend"; text: string } | { type: "decide"; id: string; approved: boolean };

let seq = 0;
const nextId = (prefix: string) => `${prefix}-${seq++}`;

function reducer(state: State, action: Action): State {
  if (action.type === "userSend") {
    return {
      ...state,
      turnActive: true,
      items: [...state.items, { kind: "user", id: nextId("user"), text: action.text, checkpointId: null }],
    };
  }

  if (action.type === "decide") {
    return {
      ...state,
      items: state.items.map((item) =>
        item.kind === "tool" && item.id === action.id
          ? { ...item, awaitingApproval: false, decision: action.approved ? "approved" : "denied" }
          : item
      ),
    };
  }

  const event = action.event;
  switch (event.type) {
    case "status":
      return { ...state, thinking: true };

    case "checkpoint_created": {
      // Attach to the most recent user item that doesn't have one yet --
      // checkpoint_created always arrives for the turn that was just queued,
      // and turns are processed one at a time, so this is unambiguous.
      let attached = false;
      const items = state.items.map((item): TimelineItem => {
        if (!attached && item.kind === "user" && item.checkpointId === null) {
          attached = true;
          return { ...item, checkpointId: event.id };
        }
        return item;
      });
      return { ...state, items };
    }

    case "tool_call":
      return {
        ...state,
        thinking: false,
        items: [
          ...state.items,
          {
            kind: "tool",
            id: event.id,
            name: event.name,
            arguments: event.arguments,
            content: null,
            status: "pending",
            awaitingApproval: false,
            decision: null,
          },
        ],
      };

    case "approval_request":
      return {
        ...state,
        thinking: false,
        items: state.items.map((item) => (item.kind === "tool" && item.id === event.id ? { ...item, awaitingApproval: true } : item)),
      };

    case "tool_result":
      return {
        ...state,
        thinking: false,
        items: state.items.map((item) =>
          item.kind === "tool" && item.id === event.id
            ? { ...item, content: event.content, status: (event.is_error ? "error" : "done") as ToolStatus }
            : item
        ),
      };

    case "message":
      return {
        ...state,
        thinking: false,
        turnActive: event.final ? false : state.turnActive,
        items: [...state.items, { kind: "assistant", id: nextId("assistant"), text: event.text, thinking: event.thinking }],
      };

    case "error":
      return {
        ...state,
        thinking: false,
        turnActive: false,
        items: [...state.items, { kind: "error", id: nextId("error"), message: event.message }],
      };

    case "cancelled":
      return {
        ...state,
        thinking: false,
        turnActive: false,
        items: [...state.items, { kind: "note", id: nextId("note"), text: "Cancelled." }],
      };

    case "rewound": {
      const index = state.items.findIndex((item) => item.kind === "user" && item.checkpointId === event.checkpoint_id);
      if (index === -1) {
        // Checkpoint from before this webview instance existed (e.g. panel
        // reopened) -- nothing local to roll back, just report what happened.
        return {
          ...state,
          items: [...state.items, { kind: "note", id: nextId("note"), text: rewindSummary(event) }],
        };
      }

      const rewoundUserItem = state.items[index];
      const keptItems = event.restored_conversation ? state.items.slice(0, index) : state.items;
      const restoredText =
        event.restored_conversation && rewoundUserItem.kind === "user" ? rewoundUserItem.text : null;

      return {
        ...state,
        turnActive: false,
        items: [...keptItems, { kind: "note", id: nextId("note"), text: rewindSummary(event) }],
        restoredComposerText: restoredText,
      };
    }

    case "connection":
      return { ...state, connected: event.status === "open" };

    case "chat_ready":
      return {
        ...state,
        thinking: false,
        turnActive: false,
        chatId: event.chat_id,
        chatTitle: event.title,
        items: event.items.map(replayItemToTimelineItem),
      };

    case "chat_list":
      return { ...state, chats: event.chats };

    case "identity":
      return { ...state, identityStatus: event.email ? "ready" : "needed" };

    default:
      return state;
  }
}

function rewindSummary(event: Extract<BackendEvent, { type: "rewound" }>): string {
  const parts: string[] = [];
  if (event.restored_code) {
    parts.push(`restored ${event.restored_files.length} file${event.restored_files.length === 1 ? "" : "s"}`);
    if (event.skipped_files.length > 0) {
      parts.push(`skipped ${event.skipped_files.length}`);
    }
  }
  if (event.restored_conversation) {
    parts.push("conversation rewound");
  }
  return `Rewound — ${parts.join(", ")}.`;
}

const initialState: State = {
  items: [],
  thinking: false,
  connected: false,
  turnActive: false,
  restoredComposerText: null,
  chatId: null,
  chatTitle: "New Chat",
  chats: [],
  identityStatus: "loading",
};

export function App() {
  const [state, dispatch] = useReducer(reducer, initialState);
  const logRef = useRef<HTMLDivElement>(null);
  const composerTextRef = useRef<{ set: (text: string) => void } | null>(null);

  useEffect(() => {
    const listener = (event: MessageEvent<BackendEvent>) => dispatch({ type: "backend", event: event.data });
    window.addEventListener("message", listener);
    // Ask the host for the CURRENT connection status now that this listener
    // is actually attached -- the socket can (and does, in practice) open
    // before this bundle finishes loading/mounting, so the one-shot
    // "connection: open" event it fired earlier may already have been lost.
    vscodeApi.postMessage({ type: "ready" });
    return () => window.removeEventListener("message", listener);
  }, []);

  useEffect(() => {
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [state.items, state.thinking]);

  // A rewind that restored the conversation hands the original prompt back
  // into the input, same as Claude Code's own /rewind -- so it can be
  // re-sent or edited rather than retyped from scratch.
  useEffect(() => {
    if (state.restoredComposerText !== null) {
      composerTextRef.current?.set(state.restoredComposerText);
    }
  }, [state.restoredComposerText]);

  const handleSend = (text: string) => {
    dispatch({ type: "userSend", text });
    vscodeApi.postMessage({ type: "send", text });
  };

  const handleDecision = (id: string, approved: boolean) => {
    dispatch({ type: "decide", id, approved });
    vscodeApi.postMessage({ type: "approval_response", id, approved });
  };

  const handleCancel = () => {
    vscodeApi.postMessage({ type: "cancel" });
  };

  const handleRewind = (checkpointId: string) => {
    vscodeApi.postMessage({ type: "rewind", checkpoint_id: checkpointId, restore_code: true, restore_conversation: true });
  };

  const handleNewChat = () => vscodeApi.postMessage({ type: "new_chat" });
  const handleSwitchChat = (chatId: string) => vscodeApi.postMessage({ type: "switch_chat", chat_id: chatId });
  const handleOpenHistory = () => vscodeApi.postMessage({ type: "list_chats" });
  const handleSubmitIdentity = (email: string) => vscodeApi.postMessage({ type: "submit_identity", email });

  if (state.identityStatus === "loading") {
    return <div className="root" />;
  }

  if (state.identityStatus === "needed") {
    return (
      <div className="root">
        <SignIn onSubmit={handleSubmitIdentity} />
      </div>
    );
  }

  return (
    <div className="root">
      <ChatHeader
        title={state.chatTitle}
        chats={state.chats}
        activeChatId={state.chatId}
        turnActive={state.turnActive}
        onOpenHistory={handleOpenHistory}
        onSwitchChat={handleSwitchChat}
        onNewChat={handleNewChat}
      />
      <div className="log" ref={logRef}>
        {state.items.length === 0 && (
          <div className="empty-state">Ask the coding assistant to explore, explain, or change something in this workspace.</div>
        )}
        {state.items.map((item) => {
          switch (item.kind) {
            case "user":
              return (
                <UserPrompt
                  key={item.id}
                  text={item.text}
                  canRewind={item.checkpointId !== null && !state.turnActive}
                  onRewind={() => item.checkpointId && handleRewind(item.checkpointId)}
                />
              );
            case "assistant":
              return (
                <Fragment key={item.id}>
                  {item.thinking && <ThinkingBlock text={item.thinking} />}
                  {item.text && <AssistantText text={item.text} />}
                </Fragment>
              );
            case "tool":
              return (
                <ToolCallCard
                  key={item.id}
                  name={item.name}
                  arguments={item.arguments}
                  content={item.content}
                  status={item.status}
                  awaitingApproval={item.awaitingApproval}
                  decision={item.decision}
                  onApprove={() => handleDecision(item.id, true)}
                  onDeny={() => handleDecision(item.id, false)}
                />
              );
            case "error":
              return (
                <div key={item.id} className="error-banner">
                  {item.message}
                </div>
              );
            case "note":
              return (
                <div key={item.id} className="note-banner">
                  {item.text}
                </div>
              );
            default:
              return null;
          }
        })}
        {state.thinking && <StatusIndicator />}
      </div>
      <Composer
        onSend={handleSend}
        onCancel={handleCancel}
        connected={state.connected}
        turnActive={state.turnActive}
        controlRef={composerTextRef}
      />
    </div>
  );
}
