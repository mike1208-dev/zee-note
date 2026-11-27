"use client";

import { useEffect, useRef, useState } from "react";
import { api, type Layout, type Rule, type SavedTemplate, type Template } from "@/lib/api";
import { useSession } from "@/lib/session";
import { Icon } from "@/components/Icon";
import { PageHead } from "@/components/Shell";
import { Spinner } from "@/components/Spinner";

const own = (rule: Rule) => rule.id === "" || rule.id.startsWith("custom_");

const NAMES: [keyof Layout, string][] = [["done", "Done yesterday"], ["weekend", "Done at the weekend"], ["today", "Plans for today"], ["blockers", "Blockers"], ["notes", "Notes"]];
const SWITCHES: [keyof Layout, string, string][] = [
  ["icons", "Icons", "✅ 🎯 🚧 before the section names"],
  ["hours", "Hours", "Each person's hours after Yesterday and Today"],
  ["links", "Full links", "Links to the PRs and issues, or just “PR #102”"],
  ["greeting", "Greeting", "Each person's greeting under the reviewer"],
];

// Edits not saved yet, by team, so switching teams in the menu doesn't lose them. Kept until the page is reloaded
const unsaved = new Map<number, Template>();

// Cleans what the form allows while typing, such as an empty line in the known terms
function forSaving(data: Template): Template {
  return {
    rules: data.rules.map((rule) => (rule.known_terms ? { ...rule, known_terms: rule.known_terms.map((term) => term.trim()).filter(Boolean) } : rule)),
    layout: data.layout,
  };
}

export default function TemplatesPage() {
  const { me, team } = useSession();
  const [saved, setSaved] = useState<SavedTemplate | null>(null);
  const [rules, setRules] = useState<Rule[] | null>(null);
  const [layout, setLayout] = useState<Layout | null>(null);
  const [preview, setPreview] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState("");
  const [newRule, setNewRule] = useState({ title: "", question: "" });
  const [loadedFor, setLoadedFor] = useState(0); // the team whose template the page shows
  const teamNow = useRef<number | undefined>(undefined);
  teamNow.current = team?.id;

  function use(result: SavedTemplate) {
    setSaved(result);
    setRules(result.rules);
    setLayout(result.layout);
  }

  useEffect(() => {
    if (!team) return;
    setSaved(null);
    setRules(null);
    setLayout(null);
    setError("");
    let stale = false;
    api<SavedTemplate>(`/teams/${team.id}/template`)
      .then((result) => {
        if (stale) return;
        use(result);
        const kept = unsaved.get(team.id);
        if (kept) {
          setRules(kept.rules);
          setLayout(kept.layout);
        }
        setLoadedFor(team.id);
      })
      .catch((e) => !stale && setError(e.message));
    return () => {
      stale = true;
    };
  }, [team]);

  // Only once the team's own template is shown, so one team's edits are never kept as another's
  useEffect(() => {
    if (!team || loadedFor !== team.id || !saved || !rules || !layout) return;
    const now = forSaving({ rules, layout });
    if (JSON.stringify(now) === JSON.stringify({ rules: saved.rules, layout: saved.layout })) unsaved.delete(team.id);
    else unsaved.set(team.id, { rules, layout });
  }, [team, loadedFor, saved, rules, layout]);

  // Leaving or reloading the page with edits not saved asks first
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (unsaved.size) event.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, []);

  // The preview is the real report builder on a made-up report, a moment after the last change
  useEffect(() => {
    if (!layout) return;
    const timer = setTimeout(() => {
      api<{ html: string }>("/template/preview", { body: layout }).then((data) => setPreview(data.html)).catch(() => {});
    }, 300);
    return () => clearTimeout(timer);
  }, [layout]);

  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(""), 3000);
    return () => clearTimeout(timer);
  }, [toast]);

  if (!team) return <main className="content"><p className="soft">There are no teams yet.</p></main>;

  async function save(path: string, body?: Template) {
    setBusy(true);
    setError("");
    const forTeam = team!.id, name = team!.name;
    try {
      const result = await api<SavedTemplate>(path, { method: body ? "PUT" : "POST", body });
      unsaved.delete(forTeam);
      if (teamNow.current === forTeam) use(result);
      setToast(`Saved. New reports of the ${name} use it now.`);
    } catch (e) {
      if (teamNow.current === forTeam) setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const editRule = (index: number, change: Partial<Rule>) => setRules(rules!.map((rule, i) => (i === index ? { ...rule, ...change } : rule)));
  const changed = rules !== null && layout !== null && saved !== null &&
    JSON.stringify(forSaving({ rules, layout })) !== JSON.stringify({ rules: saved.rules, layout: saved.layout });
  const canEdit = Boolean(saved?.can_edit);

  return (
    <>
      <PageHead
        title="Template and rules"
        sub={<>{team.name} · {me.owner ? "As the owner, you can change any team's template." : "Every report of your team follows these."}
          {saved?.updated_by && ` Last changed by ${saved.updated_by}, ${saved.updated_at?.slice(0, 16)} UTC.`}</>}>
        {canEdit && rules && layout && (
          <>
            <button className="btn" disabled={busy} onClick={() => confirm("Go back to ZeeNote's built-in template and rules? Your own rules are removed.") && save(`/teams/${team.id}/template/reset`)}>
              Reset to default
            </button>
            <button className="btn main" disabled={busy || !changed} onClick={() => save(`/teams/${team.id}/template`, forSaving({ rules, layout }))}>
              {busy ? "Saving…" : changed ? "Save changes" : "Saved"}
            </button>
          </>
        )}
      </PageHead>
      <main className="content">
        {error && <p className="notice bad" role="alert">{error}</p>}
        {!rules && !error && <div className="empty"><Spinner />Loading the template…</div>}
        {rules && layout && (
          <fieldset disabled={!canEdit || busy} style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }} className="stack">
            <section className="card flush">
              <div className="card-head">
                <div>
                  <h2>Template</h2>
                  <p className="soft small">How every report of the team looks. Each person still sets their reviewer, hours, repo link and greeting on Write report.</p>
                </div>
              </div>
              <div className="template-grid">
                <div className="stack" style={{ padding: 20 }}>
                  <h3 className="mini-title">Section names</h3>
                  <div className="cols2">
                    {NAMES.map(([key, label]) => (
                      <label key={key}>
                        {label}
                        <input value={layout[key] as string} maxLength={30} onChange={(event) => setLayout({ ...layout, [key]: event.target.value })} />
                      </label>
                    ))}
                  </div>
                  <h3 className="mini-title">Show in the report</h3>
                  <div className="stack" style={{ gap: 10 }}>
                    {SWITCHES.map(([key, label, hint]) => (
                      <label key={key} className="switch-row">
                        <span>
                          <b>{label}</b>
                          <span className="soft small">{hint}</span>
                        </span>
                        <input type="checkbox" role="switch" className="switch" checked={layout[key] as boolean} onChange={(event) => setLayout({ ...layout, [key]: event.target.checked })} />
                      </label>
                    ))}
                  </div>
                  <p className="hint"><Icon name="check" size={13} /> The rules check the section names you choose.</p>
                </div>
                <div className="template-preview">
                  <span className="mini-title">Preview</span>
                  <div className="message" style={{ padding: "12px 0 0" }}>
                    <span className="avatar lg" aria-hidden="true">{me.name[0]}</span>
                    <div>
                      <div className="meta">
                        <b>{me.name}</b>
                        <span className="faint small">example</span>
                      </div>
                      <div className="preview" dangerouslySetInnerHTML={{ __html: preview }} />
                    </div>
                  </div>
                </div>
              </div>
            </section>

            <section className="card flush">
              <div className="card-head">
                <div>
                  <h2>Rules</h2>
                  <p className="soft small">Every report is checked against the rules that are on. Code checks are always quick; AI checks ask the AI one question each.</p>
                </div>
                <span className="tag off">{rules.filter((rule) => rule.enabled).length} of {rules.length} on</span>
              </div>
              <div className="card-body">
                {rules.map((rule, i) => (
                  <div key={i} className={`rule ${rule.enabled ? "" : "off"}`}>
                    <div className="row between">
                      <label className="check grow">
                        <input type="checkbox" role="switch" className="switch" checked={rule.enabled} onChange={(event) => editRule(i, { enabled: event.target.checked })} aria-label={`${rule.title} is on`} />
                        <input value={rule.title} onChange={(event) => editRule(i, { title: event.target.value })} aria-label="Rule title" style={{ fontWeight: 500 }} />
                      </label>
                      <span className={`tag ${rule.check === "llm" ? "" : "off"}`}>{rule.check === "llm" ? "AI check" : "Code check"}</span>
                      {own(rule) && (
                        <button type="button" className="btn sm ghost danger" onClick={() => setRules(rules.filter((_, j) => j !== i))}>
                          <Icon name="trash" size={13} /> Delete
                        </button>
                      )}
                    </div>
                    {rule.check === "llm" && (
                      <label>
                        Question for the AI
                        <textarea rows={2} value={rule.question ?? ""} onChange={(event) => editRule(i, { question: event.target.value })} />
                      </label>
                    )}
                    {rule.known_terms && (
                      <label>
                        Terms that need no explanation (one per line)
                        <textarea rows={4} value={rule.known_terms.join("\n")} onChange={(event) => editRule(i, { known_terms: event.target.value.split("\n") })} />
                      </label>
                    )}
                  </div>
                ))}
              </div>
              <form
                className="card-foot"
                style={{ display: "grid", gap: 12, justifyContent: "stretch" }}
                onSubmit={(event) => {
                  event.preventDefault();
                  setRules([...rules, { id: "", check: "llm", title: newRule.title.trim(), question: newRule.question.trim(), enabled: true }]);
                  setNewRule({ title: "", question: "" });
                }}
              >
                <div>
                  <h2>Add your own rule</h2>
                  <p className="soft small">Write a yes-or-no question. The AI asks it of every report. Save to keep it.</p>
                </div>
                <div className="cols2">
                  <label>
                    Title
                    <input value={newRule.title} onChange={(event) => setNewRule({ ...newRule, title: event.target.value })} placeholder="e.g. Names the client for client work" required />
                  </label>
                  <label>
                    Question for the AI
                    <input value={newRule.question} onChange={(event) => setNewRule({ ...newRule, question: event.target.value })} placeholder="e.g. Does each client task name the client?" required />
                  </label>
                </div>
                <div>
                  <button className="btn">Add rule</button>
                </div>
              </form>
            </section>
          </fieldset>
        )}
      </main>
      {toast && <div className="toast" role="status"><Icon name="check" size={15} />{toast}</div>}
    </>
  );
}
