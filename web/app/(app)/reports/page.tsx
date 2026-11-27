"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, type ReportRow } from "@/lib/api";
import { useSession } from "@/lib/session";
import { Icon } from "@/components/Icon";
import { PageHead } from "@/components/Shell";
import { Spinner } from "@/components/Spinner";

const dateOf = (day: string) => new Date(`${day}T00:00`);

// The first tasks of the report, as one line: "Booking list shows the wrong date · Send an email…"
function tasksOf(text: string): string {
  const plain = (line: string) => line.replace(/\[([^\]]*)\]\([^)]*\)/g, "$1").replace(/[*_`#>]/g, "").replace(/^\s*[-•]\s*/, "").trim();
  const lines = text.split("\n");
  const nested = lines.filter((line) => /^\s{2,}[-•]/.test(line));
  const tasks = (nested.length ? nested : lines.filter((line) => /^[-•]\s/.test(line))).map(plain).filter(Boolean); // without icons, tasks aren't indented
  return (tasks.length ? tasks : [plain(text.replace(/\s+/g, " "))]).slice(0, 3).join(" · ");
}

export default function ReportsPage() {
  const { team, teams } = useSession();
  const [rows, setRows] = useState<ReportRow[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<ReportRow[]>("/reports").then(setRows).catch((e) => setError(e.message));
  }, []);

  // with several teams, the list shows the team chosen in the menu, and the reports of teams the person has left
  const shown = (rows ?? []).filter((row) => teams.length < 2 || row.team_id === team?.id || !teams.some((item) => item.id === row.team_id));
  const months = [...new Set(shown.map((row) => dateOf(row.day).toLocaleDateString("en-US", { month: "long", year: "numeric" })))];

  return (
    <>
      <PageHead title="My reports" sub={<>{teams.length > 1 && team ? `${team.name} · ` : ""}Every report you copied for Slack, newest first.</>}>
        <Link href="/write" className="btn main">
          <Icon name="write" size={14} /> Write report
        </Link>
      </PageHead>
      <main className="content" style={{ maxWidth: 880 }}>
        {error && <p className="notice bad">{error}</p>}
        {rows === null && !error && <div className="empty"><Spinner />Loading your reports…</div>}
        {rows !== null && shown.length === 0 && (
          <div className="card empty">
            <span className="icon-ring"><Icon name="reports" size={20} /></span>
            <b>No reports yet</b>
            <span className="small">Reports you copy for Slack are kept here.</span>
            <Link href="/write" className="btn main" style={{ marginTop: 10 }}>Write your first report</Link>
          </div>
        )}
        {months.map((month) => (
          <section key={month} className="stack" style={{ gap: 8 }}>
            <h2 className="month">{month}</h2>
            <ul className="card flush report-list">
              {shown.filter((row) => dateOf(row.day).toLocaleDateString("en-US", { month: "long", year: "numeric" }) === month).map((row) => {
                const date = dateOf(row.day);
                return (
                  <li key={row.id}>
                    <Link href={`/reports/${row.id}`}>
                      <span className="date-tile" aria-hidden="true">
                        <small>{date.toLocaleDateString("en-US", { month: "short" })}</small>
                        <b>{date.getDate()}</b>
                      </span>
                      <span style={{ minWidth: 0 }}>
                        <span className="row" style={{ gap: 8 }}>
                          <b style={{ fontWeight: 500 }}>{date.toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" })}</b>
                          {(teams.length > 1 || row.team_id !== team?.id) && <span className="tag off">{row.team}</span>}
                        </span>
                        <span className="snippet" style={{ display: "block" }}>{tasksOf(row.text)}</span>
                      </span>
                      <span className="faint"><Icon name="next" /></span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </section>
        ))}
      </main>
    </>
  );
}
