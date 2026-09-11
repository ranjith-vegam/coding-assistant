import * as vscode from "vscode";
import { ChatPanel } from "./chatPanel";
import { clearIdentity } from "./identity";

export function activate(context: vscode.ExtensionContext): void {
  const config = vscode.workspace.getConfiguration("samixaCode");
  const wsUrl = config.get<string>("backendWsUrl", "ws://127.0.0.1:8765/ws/chat");

  context.subscriptions.push(
    vscode.commands.registerCommand("samixaCode.openChat", () => {
      const folder = vscode.workspace.workspaceFolders?.[0];
      if (!folder) {
        vscode.window.showErrorMessage("Samixa Code: open a folder/workspace first.");
        return;
      }
      ChatPanel.createOrShow(context, wsUrl, folder.uri.fsPath);
    }),

    vscode.commands.registerCommand("samixaCode.switchUser", async () => {
      const hadOpenPanel = Boolean(ChatPanel.current);
      ChatPanel.current?.disposeForSwitchUser();
      await clearIdentity(context);
      if (hadOpenPanel) {
        // Reopen immediately, in-panel sign-in form, no native prompt.
        await vscode.commands.executeCommand("samixaCode.openChat");
      }
    })
  );
}

export function deactivate(): void {
  // ChatPanel disposes its own BackendClient via panel.onDidDispose.
}
