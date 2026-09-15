import { KeyboardEvent, useState } from "react";
import { ChatSummary } from "../../../shared/protocol";
import { ConfirmModal } from "./ConfirmModal";

interface Props {
  title: string;
  chats: ChatSummary[];
  activeChatId: string | null;
  turnActive: boolean;
  onOpenHistory: () => void; // fetches the latest chat list right before showing it
  onSwitchChat: (chatId: string) => void;
  onNewChat: () => void;
  onDeleteChat: (chatId: string) => void;
  onRenameChat: (chatId: string, title: string) => void;
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
export function ChatHeader({
  title,
  chats,
  activeChatId,
  turnActive,
  onOpenHistory,
  onSwitchChat,
  onNewChat,
  onDeleteChat,
  onRenameChat,
}: Props) {
  const [open, setOpen] = useState(false);
  // Which row is being renamed inline, and its in-progress text -- null
  // means no row is in edit mode (the normal case).
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const [deletingChat, setDeletingChat] = useState<ChatSummary | null>(null);

  const toggleHistory = () => {
    if (!open) onOpenHistory();
    setOpen((v) => !v);
  };

  const startEditing = (chat: ChatSummary) => {
    setEditingId(chat.chat_id);
    setEditValue(chat.title);
  };

  const commitEdit = () => {
    const chatId = editingId;
    const trimmed = editValue.trim();
    setEditingId(null);
    if (chatId && trimmed) {
      onRenameChat(chatId, trimmed);
    }
  };

  const handleEditKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") {
      event.preventDefault();
      commitEdit();
    } else if (event.key === "Escape") {
      event.preventDefault();
      setEditingId(null);
    }
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
          {chats.map((chat) => {
            const isEditing = editingId === chat.chat_id;
            return (
              <div key={chat.chat_id} className={`chat-history-item${chat.chat_id === activeChatId ? " active" : ""}`}>
                {isEditing ? (
                  <input
                    className="chat-history-item-input"
                    value={editValue}
                    autoFocus
                    onChange={(event) => setEditValue(event.target.value)}
                    onKeyDown={handleEditKeyDown}
                    onBlur={commitEdit}
                    onClick={(event) => event.stopPropagation()}
                  />
                ) : (
                  <button
                    className="chat-history-item-main"
                    onClick={() => {
                      onSwitchChat(chat.chat_id);
                      setOpen(false);
                    }}
                  >
                    <span className="chat-history-item-title">{chat.title}</span>
                    <span className="chat-history-item-time">{formatRelativeTime(chat.updated_at)}</span>
                  </button>
                )}
                {!isEditing && (
                  <div className="chat-history-item-actions">
                    <button
                      className="chat-history-icon-button"
                      title="Rename chat"
                      aria-label="Rename chat"
                      onClick={(event) => {
                        event.stopPropagation();
                        startEditing(chat);
                      }}
                    >
                      <svg width="12" height="12" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                        <path
                          d="M11.5 2.5a1.5 1.5 0 0 1 2 2l-7 7-3 1 1-3 7-7Z"
                          stroke="currentColor"
                          strokeWidth="1.3"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        />
                      </svg>
                    </button>
                    <button
                      className="chat-history-icon-button danger"
                      title="Delete chat"
                      aria-label="Delete chat"
                      onClick={(event) => {
                        event.stopPropagation();
                        setDeletingChat(chat);
                      }}
                    >
                      <svg width="12" height="12" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                        <path
                          d="M3.5 4.5h9M6.5 4.5v-1a1 1 0 0 1 1-1h1a1 1 0 0 1 1 1v1M6 7.5v4M10 7.5v4M4.5 4.5l.6 8a1 1 0 0 0 1 .95h3.8a1 1 0 0 0 1-.95l.6-8"
                          stroke="currentColor"
                          strokeWidth="1.3"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        />
                      </svg>
                    </button>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {deletingChat && (
        <ConfirmModal
          title="Delete this chat?"
          body={`"${deletingChat.title}" will be permanently deleted, including its whole conversation. This can't be undone.`}
          confirmLabel="Delete"
          danger
          onCancel={() => setDeletingChat(null)}
          onConfirm={() => {
            onDeleteChat(deletingChat.chat_id);
            setDeletingChat(null);
          }}
        />
      )}
    </div>
  );
}
