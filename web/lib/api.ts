// Calls to the ZeeNote API (api/main.py). The sign-in token is kept in this browser.

export const TOKEN = "zeenote-token";

export type Role = "Owner" | "Manager" | "Member";
export type Team = { id: number; name: string; role: Role };
export type Me = { email: string; name: string; owner: boolean; admin: boolean; teams: Team[]; company: string };
export type RuleResult = { id: string; title: string; status: "PASS" | "FAIL" | "WARN" | "SKIP" };
export type Ask = { ask: string; items: string[] };
export type Checked = { html: string; slack: string; points: string[]; asks: Ask[]; rules: RuleResult[]; summary: string };
export type Written = Checked & { notes: string; day: string; text: string; questions: string[] };
export type ReportRow = { id: number; day: string; team_id: number; team: string; text: string; created_at: string };
export type Report = ReportRow & { notes: string; html: string; slack: string };
export type Rule = { id: string; check: string; title: string; enabled: boolean; question?: string; known_terms?: string[]; [option: string]: unknown };
// the team's format of the report: its section names and a few details (Layout in checker/writer.py)
export type Layout = { done: string; weekend: string; today: string; blockers: string; notes: string; icons: boolean; hours: boolean; links: boolean; greeting: boolean };
export type Template = { rules: Rule[]; layout: Layout };
// what each person sets for their reports in a team; the next report starts from the last one
export type MySettings = {
  reviewer: string;
  first_section: "Yesterday" | "Weekend";
  done_hours: number | null;
  plan_hours: number | null;
  repo: string;
  greeting: string;
};
export type SavedTemplate = Template & { can_edit: boolean; updated_at: string | null; updated_by: string | null };

export class ApiError extends Error {
  // the message for each wrong field of a form, by the field's name
  constructor(message: string, readonly status: number, readonly fields: Record<string, string> = {}) {
    super(message);
  }
}

export function getToken(): string {
  try {
    return localStorage.getItem(TOKEN) ?? "";
  } catch {
    return "";
  }
}

export function setToken(token: string) {
  try {
    if (token) localStorage.setItem(TOKEN, token);
    else localStorage.removeItem(TOKEN);
  } catch {
    // a private window may block storage: the sign-in then lasts until the page is reloaded
  }
}

export async function api<T>(path: string, options: { method?: string; body?: unknown } = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      method: options.method ?? (options.body === undefined ? "GET" : "POST"),
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${getToken()}` },
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    });
  } catch {
    throw new ApiError("Can't reach the ZeeNote API. Is it running?", 0);
  }
  const data = await response.json().catch(() => null);
  if (response.status === 401 && path !== "/login" && typeof window !== "undefined") {
    // signed out, maybe in another tab: back to signing in, from any page
    setToken("");
    window.location.replace("/login");
  }
  if (!response.ok) {
    const detail = data?.detail;
    // FastAPI lists the wrong fields when the body doesn't fit
    const items: { loc?: unknown[]; msg: string }[] = Array.isArray(detail) ? detail : [];
    const text = (item: { msg: string }) => String(item.msg).replace(/^Value error, /, "");
    const message = typeof detail === "string" ? detail : items.length ? items.map(text).join(" ") : `Something went wrong (${response.status}).`;
    const fields = Object.fromEntries(items.filter((item) => item.loc && item.loc.length > 1).map((item) => [String(item.loc!.at(-1)), text(item)]));
    throw new ApiError(message, response.status, fields);
  }
  return data as T;
}
