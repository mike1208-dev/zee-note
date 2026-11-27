// Copies the report so that it pastes well everywhere: Slack takes its own format, other editors the HTML, and plain text
// boxes the Markdown. Only the copy event can set Slack's format, so the newer clipboard API is the backup.

export async function copyReport(data: { text: string; html?: string; slack?: string }): Promise<boolean> {
  const types: Record<string, string> = { "text/plain": data.text };
  if (data.html) types["text/html"] = data.html;
  if (data.slack) types["slack/texty"] = data.slack;

  let copied = false;
  const onCopy = (event: ClipboardEvent) => {
    event.preventDefault();
    event.stopImmediatePropagation();
    for (const type in types) event.clipboardData?.setData(type, types[type]);
    copied = true;
  };
  document.addEventListener("copy", onCopy, true);
  document.execCommand("copy");
  document.removeEventListener("copy", onCopy, true);
  if (copied) return true;
  try {
    const blob = (type: string) => new Blob([types[type]], { type });
    const item: Record<string, Blob> = { "text/plain": blob("text/plain") };
    if (types["text/html"]) item["text/html"] = blob("text/html");
    await navigator.clipboard.write([new ClipboardItem(item)]);
    return true;
  } catch {
    return false;
  }
}
