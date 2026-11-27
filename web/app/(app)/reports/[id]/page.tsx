"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { api, type Report } from "@/lib/api";
import { copyReport } from "@/lib/copy";
import { useSession } from "@/lib/session";
import { Icon } from "@/components/Icon";
import { PageHead } from "@/components/Shell";
import { Spinner } from "@/components/Spinner";

export default function ReportPage() {
  const { id } = useParams<{ id: string }>();
  const { me } = useSession();
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const router = useRouter();
  const deleteButton = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(""), 3000);
    return () => clearTimeout(timer);
  }, [toast]);

  function cancelDelete() {
    setConfirming(false);
    setTimeout(() => deleteButton.current?.focus()); // back where the person was, once the button is shown again
  }

  useEffect(() => {
    api<Report>(`/reports/${id}`).then(setReport).catch((e) => setError(e.message));
  }, [id]);

  async function copy() {
    if (!report) return;
    const copied = await copyReport(report);
    setToast(copied ? "Copied. Paste it into Slack." : "This browser didn't allow copying.");
  }

  async function remove() {
    setDeleting(true);
    try {
      await api(`/reports/${id}`, { method: "DELETE" });
      router.replace("/reports");
    } catch (e) {
      setError((e as Error).message);
      setDeleting(false);
      setConfirming(false);
    }
  }

  const day = report ? new Date(`${report.day}T00:00`).toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric", year: "numeric" }) : "";
  const saved = report ? new Date(`${report.created_at.replace(" ", "T")}Z`).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "";

  return (
    <>
      <PageHead title={report ? day : "Report"} sub={<Link href="/reports" className="row" style={{ gap: 4, display: "inline-flex" }}><Icon name="back" size={13} /> My reports</Link>}>
        {report && !confirming && (
          <>
            <button ref={deleteButton} className="btn ghost danger" onClick={() => setConfirming(true)}>
              <Icon name="trash" size={14} /> Delete
            </button>
            <button className="btn main" onClick={copy}>
              <Icon name="copy" size={14} /> Copy for Slack
            </button>
          </>
        )}
        {/* asked in the page, not in the browser's own box */}
        {report && confirming && (
          <div className="confirm" role="alert">
            <span>Delete this report? This can&apos;t be undone.</span>
            <button className="btn sm" onClick={cancelDelete} disabled={deleting} autoFocus>
              Cancel
            </button>
            <button className="btn sm danger-solid" onClick={remove} disabled={deleting}>
              {deleting ? "Deleting…" : "Delete"}
            </button>
          </div>
        )}
      </PageHead>
      <main className="content">
        {error && <p className="notice bad">{error}</p>}
        {!report && !error && <div className="empty"><Spinner />Loading the report…</div>}
        {report && (
          <div className="write">
            <section className="card flush">
              <div className="message">
                <span className="avatar lg" aria-hidden="true">{me.name[0]}</span>
                <div>
                  <div className="meta">
                    <b>{me.name}</b>
                    <span className="faint small">{saved}</span>
                  </div>
                  <div className="preview" dangerouslySetInnerHTML={{ __html: report.html }} />
                </div>
              </div>
            </section>
            <aside className="stack">
              <div className="card stack">
                <h2>Details</h2>
                <dl className="details-list">
                  <dt>Team</dt>
                  <dd>{report.team}</dd>
                  <dt>Report date</dt>
                  <dd>{new Date(`${report.day}T00:00`).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}</dd>
                  <dt>Copied</dt>
                  <dd>{saved}</dd>
                </dl>
              </div>
              {report.notes && (
                <div className="card stack">
                  <h2>Your notes</h2>
                  <pre className="notes-text">{report.notes}</pre>
                </div>
              )}
            </aside>
          </div>
        )}
      </main>
      {toast && <div className="toast" role="status"><Icon name="check" size={15} />{toast}</div>}
    </>
  );
}
