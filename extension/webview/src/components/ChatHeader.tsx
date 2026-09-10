import { useState } from "react";
import { ChatSummary } from "../../../shared/protocol";

interface Props {
  title: string;
  chats: ChatSummary[];
  activeChatId: string | null;
  turnActive: boolean;
  onOpenHistory: () => void; // fetches the latest chat list right before showing it
  onSwitchChat: (chatId: string) => void;
  onNewChat: () => void;
}

function formatRelativeTime(epochSeconds: number): string {
  const diffMs = Date.now() - epochSeconds * 1000;
  const minutes = Math.round(diffMs / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}

// Mirrors the top bar in Anthropic's own VS Code extension (verified against
// a real screenshot): a conversation title with a dropdown chevron for past
// chats, and a "+" for a new one -- not a separate sidebar.
export function ChatHeader({ title, chats, activeChatId, turnActive, onOpenHistory, onSwitchChat, onNewChat }: Props) {
  const [open, setOpen] = useState(false);

  const toggle = () => {
    if (!open) onOpenHistory();
    setOpen((v) => !v);
  };

  return (
    <div className="chat-header">
      <button className="chat-header-title" onClick={toggle} aria-expanded={open}>
        <span className="chat-header-title-text">{title}</span>
        <span className={`header-chevron${open ? " open" : ""}`} aria-hidden="true">
          <svg width="10" height="10" viewBox="0 0 12 12" fill="none">
            <path d="M2.5 4.5L6 8l3.5-3.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </span>
      </button>
      <button className="chat-header-new" onClick={onNewChat} disabled={turnActive} title="New chat" aria-label="New chat">
        +
      </button>

      {open && (
        <div className="chat-history-dropdown">
          {chats.length === 0 && <div className="chat-history-empty">No past chats yet.</div>}
          {chats.map((chat) => (
            <button
              key={chat.chat_id}
              className={`chat-history-item${chat.chat_id === activeChatId ? " active" : ""}`}
              onClick={() => {
                onSwitchChat(chat.chat_id);
                setOpen(false);
              }}
            >
              <span className="chat-history-item-title">{chat.title}</span>
              <span className="chat-history-item-time">{formatRelativeTime(chat.updated_at)}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
