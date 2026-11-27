"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { api, type Checked, type Layout, type MySettings, type RuleResult, type SavedTemplate, type Written } from "@/lib/api";
import { copyReport } from "@/lib/copy";
import { useSession } from "@/lib/session";
import { Questions, answersAsNotes } from "@/components/Questions";
import { RuleList } from "@/components/RuleList";
import { Spinner } from "@/components/Spinner";
import { Icon } from "@/components/Icon";
import { Select } from "@/components/Select";
import { PageHead } from "@/components/Shell";

const SAMPLE = `issue 95 fix booking list shows the wrong date, pr 102 merged
issue 96 feat send an email when the password is reset, pr 101 in review
practiced the project presentation
today: issue 97 chore add validation to the password reset form
blocker: waiting for QA validation on staging`;

const today = () => new Date().toLocaleDateString("sv"); // YYYY-MM-DD in this computer's time zone

type Rendered = { text: string; html: string; slack: string };

type Field = "reviewer" | "day" | "done" | "plan" | "repo" | "greeting";
const REPO = /^https:\/\/github\.com\/[\w.-]+\/[\w.-]+\/?$/; // as REPO in api/main.py

// What a person was doing in each team, so switching teams or pages loses nothing. Kept in memory only:
// reloading the page starts again from empty
type Draft = { notes: string; asked: Written | null; answers: Record<string, string>; written: Written | null; checked: Checked | null; text: string; rendered: Rendered | null };
const drafts = new Map<string, Draft>();

// The AI rules that look at the same thing as a question (as SAME_POINT in views/points.py)
const SAME_POINT: Record<string, string> = { status_or_result: "What is the status", concrete_tasks: "What exactly", terms_explained: "A reader who", real_blockers: "Do you have any blockers" };

// The AI rules ran when the notes were checked, so writing with the answers doesn't run them again. A rule that failed
// passes now when the answers solved its question
function withEarlierRules(result: Written, earlier: Written): Written {
  const solved = (id: string) => id in SAME_POINT && earlier.points.some((point) => point.startsWith(SAME_POINT[id])) && !result.points.some((point) => point.startsWith(SAME_POINT[id]));
  const before = (rule: RuleResult) => {
    const old = earlier.rules.find((other) => other.id === rule.id) ?? rule;
    return old.status !== "PASS" && old.status !== "SKIP" && solved(rule.id) ? { ...old, status: "PASS" as const } : old;
  };
  const rules = result.rules.map((rule) => (rule.status === "SKIP" ? before(rule) : rule));
  const run = rules.filter((rule) => rule.status !== "SKIP");
  const notRun = rules.length - run.length;
  const summary = `${run.filter((rule) => rule.status === "PASS").length} of ${run.length} rules passed` + (notRun ? `, ${notRun} not checked` : "");
  return { ...result, rules, summary };
}

export default function WritePage() {
  const { me, team } = useSession();
  const [notes, setNotes] = useState("");
  const [day, setDay] = useState(today);
  const [firstSection, setFirstSection] = useState<"Yesterday" | "Weekend">("Yesterday");
  const [hours, setHours] = useState<[string, string]>(["", ""]);
  const [mine, setMine] = useState({ reviewer: "", repo: "", greeting: "" });
  const [busy, setBusy] = useState<"" | "checking" | "writing">("");
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState("");
  const [asked, setAsked] = useState<Written | null>(null); // the check of the notes, while its questions are open
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [draftOf, setDraftOf] = useState(""); // the team whose draft the page shows
  const [written, setWritten] = useState<Written | null>(null);
  const [checked, setChecked] = useState<Checked | null>(null);
  const [text, setText] = useState("");
  const [rendered, setRendered] = useState<Rendered | null>(null);
  const [tab, setTab] = useState<"preview" | "markdown">("preview");
  const [showRules, setShowRules] = useState(false);
  const [toast, setToast] = useState("");
  const [problems, setProblems] = useState<Partial<Record<Field, string>>>({});
  const [layout, setLayout] = useState<Layout | null>(null); // the team's format: which settings its reports use
  const [saving, setSaving] = useState(false);
  // the team on screen now: a reply for a team that's no longer chosen is dropped, so it never shows under another team
  const teamNow = useRef<number | undefined>(undefined);
  teamNow.current = team?.id;

  // Each team's report starts from what this person used last time
  useEffect(() => {
    if (!team) return;
    let stale = false; // another team chosen before the reply came
    api<MySettings>(`/teams/${team.id}/settings`)
      .then((data) => {
        if (stale) return;
        setFirstSection(data.first_section);
        setHours([data.done_hours?.toString() ?? "", data.plan_hours?.toString() ?? ""]);
        setMine({ reviewer: data.reviewer, repo: data.repo, greeting: data.greeting });
      })
      .catch((e) => !stale && setError(e.message));
    setLayout(null);
    api<SavedTemplate>(`/teams/${team.id}/template`).then((data) => !stale && setLayout(data.layout)).catch(() => {});
    const key = `zeenote-draft-${me.email}-${team.id}`;
    const saved = drafts.get(key);
    setNotes(saved?.notes ?? "");
    setAsked(saved?.asked ?? null);
    setAnswers(saved?.answers ?? {});
    setWritten(saved?.written ?? null);
    setChecked(saved?.checked ?? null);
    setText(saved?.text ?? "");
    setRendered(saved?.rendered ?? null);
    setTab("preview");
    setError("");
    setDraftOf(key);
    return () => {
      stale = true;
    };
  }, [team, me.email]);

  // Saved only once the team's own draft is shown, so one team's work is never kept as another's
  useEffect(() => {
    if (team && draftOf === `zeenote-draft-${me.email}-${team.id}`) drafts.set(draftOf, { notes, asked, answers, written, checked, text, rendered });
  }, [team, me.email, draftOf, notes, asked, answers, written, checked, text, rendered]);

  // The preview follows the edits, a moment after typing stops
  useEffect(() => {
    if (!written || rendered?.text === text) return;
    const timer = setTimeout(() => {
      api<{ html: string; slack: string }>("/render", { body: { text } }).then((data) => setRendered({ text, ...data })).catch(() => {});
    }, 400);
    return () => clearTimeout(timer);
  }, [text, written, rendered]);

  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(""), 3000);
    return () => clearTimeout(timer);
  }, [toast]);

  if (!team) return <main className="content"><p className="soft">You aren&apos;t in a team yet. Ask your company&apos;s owner to add you.</p></main>;

  const writing = busy !== "";

  // The questions stay open, so an answer can be changed and the report written again
  function show(result: Written) {
    setWritten(result);
    setChecked(result);
    setText(result.text);
    setRendered({ text: result.text, html: result.html, slack: result.slack });
    setTab("preview");
  }

  // The settings are checked here, so each problem shows under its own field
  const usesHours = layout?.hours ?? true;
  const usesLinks = layout?.links ?? true;
  const usesGreeting = layout?.greeting ?? true;

  function settingsOk(): boolean {
    const hoursProblem = (value: string) => (value === "" || Number(value) < 0 || Number(value) > 24 ? "Write the hours." : "");
    const found: Partial<Record<Field, string>> = {
      reviewer: mine.reviewer.trim() ? "" : "Write who checks your report.",
      day: day ? "" : "Pick the date of the report.",
      // what the team's format leaves out of the report isn't needed
      done: usesHours ? hoursProblem(hours[0]) : "",
      plan: usesHours ? hoursProblem(hours[1]) : "",
      repo: !mine.repo.trim() ? (usesLinks ? "Write your GitHub repo link." : "") : REPO.test(mine.repo.trim()) ? "" : "Write a link such as https://github.com/acme/app.",
      greeting: !usesGreeting || mine.greeting.trim() ? "" : "Write a greeting.",
    };
    const open = Object.fromEntries(Object.entries(found).filter(([, problem]) => problem));
    setProblems(open);
    const first = Object.keys(open)[0];
    if (first) document.getElementById(`field-${first}`)?.focus();
    return !first;
  }

  const clear = (name: Field) => problems[name] && setProblems({ ...problems, [name]: "" });
  const field = (name: Field) => ({ id: `field-${name}`, "aria-invalid": Boolean(problems[name]), "aria-describedby": problems[name] ? `problem-${name}` : undefined });
  const problem = (name: Field) => problems[name] && <span id={`problem-${name}`} className="field-problem">{problems[name]}</span>;

  async function writeReport(answered: string[], check_ai: boolean) {
    const number = (value: string) => (value === "" ? null : Number(value));
    return api<Written>("/reports/write", {
      body: { team_id: team!.id, notes, answers: answered, day, first_section: firstSection, done_hours: number(hours[0]), plan_hours: number(hours[1]), ...mine, check_ai },
    });
  }

  // First the notes are checked. With nothing to ask, the report is ready; otherwise the questions come first
  async function checkNotes(event: React.FormEvent) {
    event.preventDefault();
    if (!settingsOk()) return;
    setBusy("checking");
    setError("");
    setWritten(null);
    setChecked(null);
    const forTeam = team!.id;
    try {
      const result = await writeReport([], true);
      if (teamNow.current !== forTeam) return;
      if (JSON.stringify(result.asks) !== JSON.stringify(asked?.asks)) setAnswers({}); // the same questions keep their answers
      setAsked(result.points.length ? result : null);
      if (!result.points.length) show(result);
      else
        setTimeout(() => {
          const card = document.getElementById("questions");
          card?.scrollIntoView({ behavior: "smooth", block: "start" });
          card?.querySelector<HTMLElement>("input, [role=combobox]")?.focus({ preventScroll: true });
        });
    } catch (e) {
      if (teamNow.current === forTeam) setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }

  async function writeWithAnswers() {
    if (!settingsOk()) return;
    setBusy("writing");
    setError("");
    setWritten(null);
    setChecked(null);
    const forTeam = team!.id;
    try {
      const result = await writeReport(answersAsNotes(asked!.asks, answers), false);
      if (teamNow.current === forTeam) show(withEarlierRules(result, asked!));
    } catch (e) {
      if (teamNow.current === forTeam) setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }

  async function checkAgain() {
    setChecking(true);
    const forTeam = team!.id;
    try {
      const result = await api<Checked>("/reports/check", { body: { team_id: forTeam, text, questions: written!.questions } });
      if (teamNow.current === forTeam) setChecked(result);
    } catch (e) {
      if (teamNow.current === forTeam) setToast((e as Error).message);
    } finally {
      setChecking(false);
    }
  }

  async function copyAndSave() {
    if (saving) return; // a second click while saving would report the new report as "updated"
    setSaving(true);
    // copy first, while the click still allows it, then save
    const fresh = rendered?.text === text ? rendered : null;
    const copied = await copyReport({ text, html: fresh?.html, slack: fresh?.slack });
    try {
      const { replaced } = await api<{ replaced: boolean }>("/reports", { body: { team_id: team!.id, day: written!.day, notes: written!.notes, text } }); // with the answers, for the day it was written for
      const kept = replaced ? "This day's report in My reports is updated." : "It's saved in My reports.";
      setToast(copied ? `Copied. Paste it into Slack. ${kept}` : `${kept} This browser didn't allow copying, so copy it from Edit.`);
    } catch (e) {
      setToast(`${copied ? "Copied" : "Not copied"}, but not saved: ${(e as Error).message}`);
    } finally {
      setSaving(false);
    }
  }

  const edited = written !== null && text !== written.text;
  const toFill = /\[add (?:your tasks|your blockers, or None|the title)\]/.test(text);
  const step = written ? 3 : asked ? 2 : 1;
  const longDay = day ? new Date(`${day}T00:00`).toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" }) : "";
  const run = checked?.rules.filter((rule) => rule.status !== "SKIP") ?? [];
  const passed = run.filter((rule) => rule.status === "PASS").length;

  return (
    <>
      <PageHead title="Write report" sub={<>{team.name}{longDay && ` · ${longDay}`}</>}>
        <ol className="steps" aria-label="Steps">
          {["Notes", "Questions", "Report"].map((name, i) => (
            <li key={name} className={i + 1 === step ? "now" : i + 1 < step ? "past" : ""} aria-current={i + 1 === step ? "step" : undefined}>
              <span className="dot">{i + 1 < step ? <Icon name="check" size={12} /> : i + 1}</span>
              <span className="label">{name}</span>
            </li>
          ))}
        </ol>
      </PageHead>

      <main className="content">
        <form className="write" onSubmit={checkNotes} noValidate>
          <div className="stack" style={{ gap: 20 }}>
            <section className="card flush composer">
              <div className="card-head">
                <div className="title-row">
                  <span className="badge-num">1</span>
                  <div>
                    <h2>Your notes</h2>
                    <p className="soft small">What you did, what you&apos;ll do, and any blockers. Any order is fine.</p>
                  </div>
                </div>
              </div>
              <textarea rows={8} value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="e.g. fixed issue 95, pr 102 merged…" disabled={writing} aria-label="Your notes" />
              <div className="card-foot">
                <div className="row" style={{ gap: 12 }}>
                  {/* easy to find for someone new: an accent button, and named in the empty report below */}
                  <button type="button" className="btn sm accent" onClick={() => setNotes(SAMPLE)} disabled={writing}>
                    <Icon name="sparkle" size={14} /> Try sample notes
                  </button>
                  <span className="faint small">{notes.length.toLocaleString("en-US")} / 8,000</span>
                </div>
                <button className="btn main" disabled={writing || !notes.trim()}>
                  {busy === "checking" ? "Checking…" : <>Check notes <Icon name="arrow" size={14} /></>}
                </button>
              </div>
            </section>
            <p className="hint" style={{ marginTop: -10 }}>
              <Icon name="lock" size={13} /> Don&apos;t write keys or passwords: your notes are sent to an AI service.
            </p>

            {/* the notes stay editable: Check notes again asks again */}
            {asked && (
              <Questions asks={asked.asks} answers={answers} onAnswer={(key, value) => setAnswers({ ...answers, [key]: value })} open={checked?.asks ?? null}
                disabled={writing} writing={busy === "writing"} onWrite={writeWithAnswers} />
            )}

            <section className="card flush" aria-live="polite">
              <div className="card-head">
                <div className="title-row">
                  <span className="badge-num">3</span>
                  <div>
                    <h2>Daily report</h2>
                    <p className="soft small">How it will look in Slack. Every report you copy is saved in <Link href="/reports">My reports</Link>.</p>
                  </div>
                </div>
                {written && (
                  <div className="segmented" role="tablist">
                    {(["preview", "markdown"] as const).map((name) => (
                      <button key={name} type="button" role="tab" aria-selected={tab === name} onClick={() => setTab(name)}>
                        {name === "preview" ? "Preview" : "Edit"}
                      </button>
                    ))}
                  </div>
                )}
              </div>
              {error && (
                <div className="card-body">
                  <p className="notice bad" role="alert">{error}</p>
                </div>
              )}
              {busy === "checking" && <div className="empty"><Spinner />Checking your notes…</div>}
              {busy === "writing" && <div className="empty"><Spinner />Writing your daily report…</div>}
              {!writing && !written && !error && (
                <div className="empty">
                  <span className="icon-ring"><Icon name="file" size={20} /></span>
                  <b>{asked ? "Answer the questions first" : "Your report shows up here"}</b>
                  <span className="small">
                    {asked ? <>Then click <b>Write report</b>.</> : <>Write your notes and click <b>Check notes</b>. ZeeNote asks about anything missing first.</>}
                  </span>
                  {!asked && !notes.trim() && (
                    <button type="button" className="btn sm accent" style={{ marginTop: 10 }} onClick={() => setNotes(SAMPLE)}>
                      <Icon name="sparkle" size={14} /> New here? Try sample notes
                    </button>
                  )}
                </div>
              )}
              {written && checked && (
                <>
                  {/* with the questions open, they show what is still open; edits checked again show it here */}
                  {!asked && checked.points.length > 0 && (
                    <div className="card-body" style={{ paddingBottom: 0 }}>
                      <div className="notice">
                        <b>{checked.points.length} point{checked.points.length === 1 ? " is" : "s are"} still open.</b> Fix them in Edit, or copy it as it is.
                        <ul className="points">
                          {checked.points.map((point) => <li key={point}>{point}</li>)}
                        </ul>
                      </div>
                    </div>
                  )}
                  {tab === "preview" ? (
                    <div className="message">
                      <span className="avatar lg" aria-hidden="true">{me.name[0]}</span>
                      <div>
                        <div className="meta">
                          <b>{me.name}</b>
                          <span className="faint small">{new Date().toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" })}</span>
                        </div>
                        <div className="preview" dangerouslySetInnerHTML={{ __html: rendered?.html ?? "" }} />
                      </div>
                    </div>
                  ) : (
                    <textarea className="markdown" rows={18} value={text} onChange={(event) => setText(event.target.value)} aria-label="Daily report in Markdown" />
                  )}
                  {toFill && <p className="error" style={{ padding: "0 20px 14px" }}>Fill in the parts in [brackets] before you post it.</p>}
                  {showRules && (
                    <div id="rule-list" className="card-body" style={{ borderTop: "1px solid var(--line)" }}>
                      <RuleList rules={checked.rules} />
                    </div>
                  )}
                  <div className="card-foot">
                    {/* a button that looks like one, so it's clear the rules can be opened */}
                    <button type="button" className="btn sm rules-toggle" aria-expanded={showRules} aria-controls="rule-list" onClick={() => setShowRules(!showRules)}>
                      <span className={`tag ${passed === run.length ? "ok" : "warn"}`}>
                        <Icon name={passed === run.length ? "check" : "alert"} size={12} /> {checked.summary}
                      </span>
                      {showRules ? "Hide rules" : "Show rules"}
                      <span className="select-chevron"><Icon name="chevron" size={14} /></span>
                    </button>
                    <div className="row">
                      {edited && (
                        <button type="button" className="btn" onClick={checkAgain} disabled={checking}>
                          <Icon name="refresh" size={14} /> {checking ? "Checking…" : "Check again"}
                        </button>
                      )}
                      <button type="button" className="btn main" onClick={copyAndSave} disabled={saving}>
                        <Icon name="copy" size={14} /> {saving ? "Saving…" : "Copy for Slack"}
                      </button>
                    </div>
                  </div>
                </>
              )}
            </section>
          </div>

          <aside className="card stack" onKeyDown={(event) => event.key === "Enter" && (event.target as HTMLElement).tagName === "INPUT" && event.preventDefault()}>
            <div>
              <h2>Report settings</h2>
              <p className="soft small">All fields are required. ZeeNote keeps them for your next report.{layout && (!usesHours || !usesGreeting) ? " Your team's template leaves the others out." : ""}</p>
            </div>
            <label>
              <span>Reviewer (tagged at the top)</span>
              <input {...field("reviewer")} value={mine.reviewer} onChange={(event) => { setMine({ ...mine, reviewer: event.target.value }); clear("reviewer"); }} placeholder="e.g. Illia" disabled={writing} />
              {problem("reviewer")}
            </label>
            <label>
              <span>Date</span>
              <input {...field("day")} type="date" value={day} onChange={(event) => { setDay(event.target.value); clear("day"); }} disabled={writing} />
              {problem("day")}
            </label>
            <div className="stack" style={{ gap: 6 }}>
              <span id="first-section" style={{ fontSize: 13, fontWeight: 500 }}>First section</span>
              <Select labelledBy="first-section" value={firstSection} onChange={(value) => setFirstSection(value as "Yesterday" | "Weekend")} disabled={writing}
                options={[{ value: "Yesterday", label: "Yesterday" }, { value: "Weekend", label: "Weekend" }]} />
            </div>
            {usesHours && (
              <div className="cols2">
                {(["done", "plan"] as const).map((name, i) => (
                  <label key={name}>
                    <span>{i === 0 ? firstSection : "Today"} (hours)</span>
                    <input {...field(name)} type="number" min={0} max={24} step={0.5} value={hours[i]} disabled={writing}
                      onChange={(event) => { setHours(i === 0 ? [event.target.value, hours[1]] : [hours[0], event.target.value]); clear(name); }} />
                    {problem(name)}
                  </label>
                ))}
              </div>
            )}
            <label>
              <span>GitHub repo link{usesLinks ? "" : " (optional)"}</span>
              <input {...field("repo")} value={mine.repo} onChange={(event) => { setMine({ ...mine, repo: event.target.value }); clear("repo"); }} placeholder="https://github.com/acme/app" disabled={writing} />
              {problem("repo")}
            </label>
            {usesGreeting && (
              <label>
                <span>Greeting</span>
                <textarea {...field("greeting")} rows={3} value={mine.greeting} onChange={(event) => { setMine({ ...mine, greeting: event.target.value }); clear("greeting"); }} disabled={writing} />
                {problem("greeting")}
              </label>
            )}
          </aside>
        </form>
      </main>
      {toast && <div className="toast" role="status"><Icon name="check" size={15} />{toast}</div>}
    </>
  );
}
