// A deliberately simple identity mechanism -- no password, no real auth
// server. An email identifies the user (used as the Redis partition key for
// their chats on the backend); a token is a deterministic-looking id derived
// from it. Persisted in globalState so this only happens once per VS Code
// install, not once per workspace.
//
// Pure storage helpers only -- the sign-in FORM itself lives in the webview
// (see webview/src/components/SignIn.tsx), not a native VS Code input box.
// chatPanel.ts is what actually drives this: it reads getStoredIdentity() on
// mount and calls saveIdentity() when the webview submits the form.

import * as crypto from "node:crypto";
import * as vscode from "vscode";

export interface Identity {
  email: string;
  userId: string;
  token: string;
}

const STORAGE_KEY = "codingAssistant.identity";

function deriveToken(email: string): string {
  return crypto.createHash("sha256").update(`coding-assistant:${email.toLowerCase().trim()}`).digest("hex").slice(0, 16);
}

export function getStoredIdentity(context: vscode.ExtensionContext): Identity | undefined {
  return context.globalState.get<Identity>(STORAGE_KEY);
}

export async function saveIdentity(context: vscode.ExtensionContext, rawEmail: string): Promise<Identity> {
  const email = rawEmail.trim();
  const identity: Identity = { email, userId: email.toLowerCase(), token: deriveToken(email) };
  await context.globalState.update(STORAGE_KEY, identity);
  return identity;
}

export async function clearIdentity(context: vscode.ExtensionContext): Promise<void> {
  await context.globalState.update(STORAGE_KEY, undefined);
}
