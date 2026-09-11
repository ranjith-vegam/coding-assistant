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
// a real screenshot): a conversation title, a history control for past
// chats, and a "+" for a new one -- not a separate sidebar. History is its
// own clock-icon button (not a chevron glued to the title) so the title
// reads as a plain label and the two actions ("see history" vs "start
// fresh") are visually distinct, same split as Claude Code's own web UI.
export function ChatHeader({ title, chats, activeChatId, turnActive, onOpenHistory, onSwitchChat, onNewChat }: Props) {
  const [open, setOpen] = useState(false);

  const toggleHistory = () => {
    if (!open) onOpenHistory();
    setOpen((v) => !v);
  };

  return (
    <div className="chat-header">
      <div className="chat-header-title">
        <span className="chat-header-title-text">{title}</span>
      </div>

      <button
        className={`chat-header-icon-button${open ? " open" : ""}`}
        onClick={toggleHistory}
        aria-expanded={open}
        title="Chat history"
        aria-label="Chat history"
      >
        <svg width="15" height="15" viewBox="0 0 16 16" fill="none" aria-hidden="true">
          <circle cx="8" cy="8.5" r="6" stroke="currentColor" strokeWidth="1.3" />
          <path d="M8 5.2V8.5l2.4 1.4" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      <button
        className="chat-header-icon-button chat-header-new"
        onClick={onNewChat}
        disabled={turnActive}
        title="New chat"
        aria-label="New chat"
      >
        <svg width="15" height="15" viewBox="0 0 16 16" fill="none" aria-hidden="true">
          <path d="M8 3v10M3 8h10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
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
