import { KeyboardEvent, useState } from "react";

interface Props {
  onSubmit: (email: string) => void;
}

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

// In-webview sign-in -- deliberately NOT a native VS Code input box, so it
// looks and feels like part of the extension's own UI rather than an OS-level
// prompt. No password: an email is just the partition key for this person's
// chats (see backend/samixa_code/chat_store.py).
export function SignIn({ onSubmit }: Props) {
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);

  const submit = () => {
    const trimmed = email.trim();
    if (!EMAIL_RE.test(trimmed)) {
      setError("Enter a valid email address");
      return;
    }
    setError(null);
    onSubmit(trimmed);
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") submit();
  };

  return (
    <div className="signin-screen">
      <div className="signin-card">
        <div className="signin-title">Welcome to Samixa Code</div>
        <div className="signin-subtitle">
          Enter your email to keep your chat history yours -- no password, this just separates your chats from anyone
          else's using this backend.
        </div>
        <input
          className="signin-input"
          type="email"
          placeholder="you@example.com"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          onKeyDown={handleKeyDown}
          autoFocus
        />
        {error && <div className="signin-error">{error}</div>}
        <button className="signin-submit" onClick={submit} disabled={!email.trim()}>
          Continue
        </button>
      </div>
    </div>
  );
}
