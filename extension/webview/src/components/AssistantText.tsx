import { Markdown } from "./Markdown";

// Rendered as actual markdown (see Markdown.tsx) -- flat, no card/bubble,
// matching the flat document-like reading experience of Anthropic's own
// VS Code extension rather than a boxed chat-app aesthetic.
export function AssistantText({ text }: { text: string }) {
  return <Markdown text={text} />;
}
