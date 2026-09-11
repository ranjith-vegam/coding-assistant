// Hosts the React webview (webview/src) inside a VS Code panel. This file is
// a thin message bridge: BackendClient <-> webview, nothing more. Approval
// prompts are NOT a native dialog -- they render inline in the tool-call
// card inside the chat itself (see webview/src/components/ToolCallCard.tsx),
// so the decision stays part of the conversation flow instead of
// interrupting it with an OS-level modal. Sign-in works the same way: the
// email FORM lives in the webview (SignIn.tsx), not a native input box --
// this file only persists what the webview submits.

import * as crypto from "node:crypto";
import * as vscode from "vscode";
import { BackendClient, BackendEvent } from "./backendClient";
import { getStoredIdentity, saveIdentity } from "./identity";
import { WebviewOutboundMessage } from "../shared/protocol";

// Remembers the last-active chat per workspace so reopening the panel (or
// reloading the VS Code window) resumes it instead of always starting fresh.
function lastChatStorageKey(workspaceRoot: string): string {
  return `samixaCode.lastChatId:${workspaceRoot}`;
}

export class ChatPanel {
  public static current: ChatPanel | undefined;

  private readonly panel: vscode.WebviewPanel;
  private readonly disposables: vscode.Disposable[] = [];
  // Undefined until identity is known -- no backend connection starts before
  // then, since there's no user_id to key Redis chats on yet.
  private client: BackendClient | undefined;

  static createOrShow(context: vscode.ExtensionContext, wsUrl: string, workspaceRoot: string): void {
    if (ChatPanel.current) {
      ChatPanel.current.panel.reveal();
      return;
    }
    const panel = vscode.window.createWebviewPanel(
      "samixaCodeChat",
      "Samixa Code",
      vscode.ViewColumn.Beside,
      {
        enableScripts: true,
        retainContextWhenHidden: true,
        localResourceRoots: [vscode.Uri.joinPath(context.extensionUri, "dist")],
      }
    );
    ChatPanel.current = new ChatPanel(panel, context, wsUrl, workspaceRoot);
  }

  private constructor(
    panel: vscode.WebviewPanel,
    private readonly context: vscode.ExtensionContext,
    private readonly wsUrl: string,
    private readonly workspaceRoot: string
  ) {
    this.panel = panel;
    this.panel.webview.html = this.render(context.extensionUri);

    const existing = getStoredIdentity(context);
    if (existing) {
      this.startSession(existing.userId);
    }
    // else: the webview will render its sign-in form (SignIn.tsx) once it
    // hears identity=null from the "ready" handshake below, and this stays
    // paused until a "submit_identity" message arrives.

    this.panel.webview.onDidReceiveMessage(
      async (message: WebviewOutboundMessage) => {
        if (message.type === "ready") {
          // Answer with CURRENT identity + connection status rather than
          // relying on catching a one-shot event at exactly the right
          // moment -- the same reasoning as the connection-status fix.
          const identity = getStoredIdentity(context);
          this.panel.webview.postMessage({
            type: "identity",
            email: identity?.email ?? null,
            token: identity?.token ?? null,
          } satisfies BackendEvent);
          if (this.client) {
            this.panel.webview.postMessage({ type: "connection", status: this.client.getStatus() } satisfies BackendEvent);
          }
          return;
        }

        if (message.type === "submit_identity") {
          if (this.client) return; // already signed in this session -- ignore a stray resubmit
          const identity = await saveIdentity(context, message.email);
          this.panel.webview.postMessage({ type: "identity", email: identity.email, token: identity.token } satisfies BackendEvent);
          this.startSession(identity.userId);
          return;
        }

        if (!this.client) return; // nothing else is meaningful before identity/connection exist

        if (message.type === "send" && message.text) {
          this.client.send(message.text);
        } else if (message.type === "approval_response") {
          this.client.respondToApproval(message.id, message.approved);
        } else if (message.type === "cancel") {
          this.client.cancel();
        } else if (message.type === "rewind") {
          this.client.rewind(message.checkpoint_id, message.restore_code, message.restore_conversation);
        } else if (message.type === "new_chat") {
          this.client.newChat();
        } else if (message.type === "switch_chat") {
          this.client.switchChat(message.chat_id);
        } else if (message.type === "list_chats") {
          this.client.listChats();
        }
      },
      undefined,
      this.disposables
    );

    this.panel.onDidDispose(() => this.dispose(), undefined, this.disposables);
  }

  private startSession(userId: string): void {
    if (this.client) return;
    const lastChatId = this.context.workspaceState.get<string>(lastChatStorageKey(this.workspaceRoot));
    const client = new BackendClient(this.wsUrl, this.workspaceRoot, userId, lastChatId);
    this.client = client;
    this.disposables.push(
      client.onEvent((event: BackendEvent) => {
        if (event.type === "chat_ready") {
          void this.context.workspaceState.update(lastChatStorageKey(this.workspaceRoot), event.chat_id);
        }
        this.panel.webview.postMessage(event);
      })
    );
    client.connect();
  }

  /** Closes the panel outright -- used by "Switch User" so the next
   * "Open Chat" creates a fresh panel that shows the sign-in form again. */
  disposeForSwitchUser(): void {
    this.panel.dispose(); // triggers onDidDispose -> this.dispose()
  }

  private dispose(): void {
    ChatPanel.current = undefined;
    this.client?.dispose();
    for (const d of this.disposables) {
      d.dispose();
    }
  }

  private render(extensionUri: vscode.Uri): string {
    const webview = this.panel.webview;
    const scriptUri = webview.asWebviewUri(vscode.Uri.joinPath(extensionUri, "dist", "webview.js"));
    const styleUri = webview.asWebviewUri(vscode.Uri.joinPath(extensionUri, "dist", "webview.css"));
    const nonce = crypto.randomBytes(16).toString("base64");

    return /* html */ `<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8" />
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${webview.cspSource}; img-src ${webview.cspSource} data:; script-src 'nonce-${nonce}';" />
<link rel="stylesheet" href="${styleUri}" />
</head>
<body>
  <div id="root"></div>
  <script nonce="${nonce}" src="${scriptUri}"></script>
</body>
</html>`;
  }
}
