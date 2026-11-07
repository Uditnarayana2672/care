/** Escape everything, then re-enable a tiny allowlist (b, i, br) — agent text is never trusted as HTML. */
export function safeHtml(s: string): string {
  const esc = s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  return esc
    .replace(/&lt;(\/?)(b|i)&gt;/g, "<$1$2>")
    .replace(/&lt;br\s*\/?&gt;/g, "<br>");
}
