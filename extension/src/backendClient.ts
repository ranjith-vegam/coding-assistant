// Thin WebSocket client for the Python backend's /ws/chat endpoint.
//
// Wire protocol (see backend/samixa_code/api/chat.py and ../shared/protocol.ts):
//   send:    { type: "init", workspace_root, user_id, chat_id? }  -- first message, once per connection
//            { type: "send", content: string }
//            { type: "approval_response", id: string, approved: boolean }
//   receive: BackendEvent (see shared/protocol.ts)
//
// No real token streaming yet -- the backend can't get incremental tokens out
// of model-orch today (stream=true hangs indefinitely there).

import * as vscode from "vscode";
import WebSocket from "ws";
import { BackendEvent } from "../shared/protocol";

export type { BackendEvent };

export class BackendClient implements vscode.Disposable {
  private socket: WebSocket | undefined;
  private readonly listeners = new Set<(event: BackendEvent) => void>();
  private reconnectTimer: NodeJS.Timeout | undefined;
  // The webview's React bundle can take longer to load/mount than the socket
  // takes to open -- a "connection: open" emitted before its message listener
  // is attached is simply lost (postMessage doesn't buffer). Tracking the
  // last known status lets a late-mounting webview ask for it explicitly
  // (see chatPanel.ts's "ready" handling) instead of relying on catching a
  // one-shot event at exactly the right moment.
  private lastStatus: "open" | "closed" = "closed";
  // Tracks whichever chat is currently active in this panel (updated from
  // "chat_ready" events, including ones caused by new_chat/switch_chat) so a
  // reconnect (network blip, backend restart) resumes the SAME chat rather
  // than silently falling back to the one passed in at construction time.
  private activeChatId: string | undefined;

  constructor(
    private readonly wsUrl: string,
    private readonly workspaceRoot: string,
    private readonly userId: string,
    initialChatId: string | undefined
  ) {
    this.activeChatId = initialChatId;
  }

  onEvent(listener: (event: BackendEvent) => void): vscode.Disposable {
    this.listeners.add(listener);
    return new vscode.Disposable(() => this.listeners.delete(listener));
  }

  getStatus(): "open" | "closed" {
    return this.lastStatus;
  }

  getActiveChatId(): string | undefined {
    return this.activeChatId;
  }

  connect(): void {
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      return;
    }
    const socket = new WebSocket(this.wsUrl);
    this.socket = socket;

    socket.on("open", () => {
      socket.send(
        JSON.stringify({
          type: "init",
          workspace_root: this.workspaceRoot,
          user_id: this.userId,
          chat_id: this.activeChatId,
        })
      );
      this.lastStatus = "open";
      this.emit({ type: "connection", status: "open" });
    });
    socket.on("message", (raw) => {
      try {
        const event = JSON.parse(raw.toString()) as BackendEvent;
        this.emit(event);
      } catch (err) {
        this.emit({ type: "error", message: `Malformed message from backend: ${String(err)}` });
      }
    });
    socket.on("close", () => {
      this.lastStatus = "closed";
      this.emit({ type: "connection", status: "closed" });
      this.scheduleReconnect();
    });
    socket.on("error", (err) => {
      this.emit({ type: "error", message: `Backend connection error: ${err.message}` });
    });
  }

  send(content: string): void {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
      this.emit({ type: "error", message: "Not connected to the backend yet -- try again in a moment." });
      this.connect();
      return;
    }
    this.socket.send(JSON.stringify({ type: "send", content }));
  }

  respondToApproval(id: string, approved: boolean): void {
    this.socket?.send(JSON.stringify({ type: "approval_response", id, approved }));
  }

  cancel(): void {
    this.socket?.send(JSON.stringify({ type: "cancel" }));
  }

  rewind(checkpointId: string, restoreCode: boolean, restoreConversation: boolean): void {
    this.socket?.send(
      JSON.stringify({
        type: "rewind",
        checkpoint_id: checkpointId,
        restore_code: restoreCode,
        restore_conversation: restoreConversation,
      })
    );
  }

  newChat(): void {
    this.socket?.send(JSON.stringify({ type: "new_chat" }));
  }

  switchChat(chatId: string): void {
    this.socket?.send(JSON.stringify({ type: "switch_chat", chat_id: chatId }));
  }

  listChats(): void {
    this.socket?.send(JSON.stringify({ type: "list_chats" }));
  }

  deleteChat(chatId: string): void {
    this.socket?.send(JSON.stringify({ type: "delete_chat", chat_id: chatId }));
  }

  renameChat(chatId: string, title: string): void {
    this.socket?.send(JSON.stringify({ type: "rename_chat", chat_id: chatId, title }));
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer) {
      return;
    }
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = undefined;
      this.connect();
    }, 2000);
  }

  private emit(event: BackendEvent): void {
    if (event.type === "chat_ready") {
      this.activeChatId = event.chat_id;
    }
    for (const listener of this.listeners) {
      listener(event);
    }
  }

  dispose(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
    }
    this.socket?.close();
  }
}
