// Maps a raw tool call into how it reads as a single line, matching the
// "Read foo.ts" / "Write bar.ts" style of Anthropic's own VS Code extension
// -- a verb + target, not a raw function-call dump.

const VERB_BY_TOOL: Record<string, { verb: string; targetArg: string }> = {
  read_file: { verb: "Read", targetArg: "path" },
  write_file: { verb: "Write", targetArg: "path" },
  edit_file: { verb: "Edit", targetArg: "path" },
  list_dir: { verb: "List", targetArg: "path" },
  search_code: { verb: "Search", targetArg: "query" },
  run_command: { verb: "Run", targetArg: "command" },
};

export function describeCall(name: string, args: Record<string, unknown>): { verb: string; target: string } {
  const spec = VERB_BY_TOOL[name];
  if (!spec) return { verb: name, target: "" };
  const raw = args[spec.targetArg];
  return { verb: spec.verb, target: raw === undefined || raw === null ? "" : String(raw) };
}

// A short, human sentence describing what a completed call actually did --
// shown inline without needing to expand, same as the reference UI's
// "Read 256 lines" sub-line.
export function summarizeResult(name: string, content: string): string {
  const trimmed = content.trim();
  if (name === "read_file") {
    const lineCount = content.split("\n").length;
    return `${lineCount} line${lineCount === 1 ? "" : "s"}`;
  }
  if (name === "search_code") {
    if (trimmed === "(no matches)") return "no matches";
    const count = content.split("\n").filter((line) => line.trim() && !line.startsWith("...")).length;
    return `${count} match${count === 1 ? "" : "es"}`;
  }
  if (name === "list_dir") {
    if (trimmed === "(empty directory)") return "empty";
    return `${content.split("\n").filter((l) => l.trim()).length} entries`;
  }
  // write_file/edit_file/run_command already return a good one-line summary
  // as their first line (e.g. "wrote 16 bytes to note.txt").
  return trimmed.split("\n")[0] ?? "";
}
