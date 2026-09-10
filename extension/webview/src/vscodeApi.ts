import type { WebviewOutboundMessage } from "../../shared/protocol";

interface VsCodeApi {
  postMessage(message: WebviewOutboundMessage): void;
  getState(): unknown;
  setState(state: unknown): void;
}

declare function acquireVsCodeApi(): VsCodeApi;

export const vscodeApi = acquireVsCodeApi();
