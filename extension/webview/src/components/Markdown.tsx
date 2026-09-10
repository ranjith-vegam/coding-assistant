import DOMPurify from "dompurify";
import { marked } from "marked";
import { useMemo } from "react";

marked.setOptions({ breaks: true, gfm: true });

// Renders LLM output as actual markdown (headers, bold, lists, code fences,
// links) instead of literal asterisks/backticks. Sanitized with DOMPurify as
// defense in depth -- the page's CSP (script-src 'nonce-...', no
// unsafe-inline) already blocks any injected <script> or inline event
// handler from executing, but the model's output is still untrusted text
// being rendered as HTML, and sanitizing costs nothing here.
export function Markdown({ text }: { text: string }) {
  const html = useMemo(() => {
    const raw = marked.parse(text, { async: false }) as string;
    return DOMPurify.sanitize(raw);
  }, [text]);

  // eslint-disable-next-line react/no-danger -- sanitized above
  return <div className="markdown-body" dangerouslySetInnerHTML={{ __html: html }} />;
}
