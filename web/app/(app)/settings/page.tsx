"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useSession } from "@/lib/session";
import { Icon } from "@/components/Icon";
import { PageHead } from "@/components/Shell";
import { TeamsAndPeople } from "@/components/TeamsAndPeople";

// The owner's settings of the company: its name, and its teams and people
export default function SettingsPage() {
  const { me, changeMe } = useSession();
  const [name, setName] = useState(me.company);
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState("");

  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(""), 3500);
    return () => clearTimeout(timer);
  }, [toast]);

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setProblem("");
    try {
      const saved = await api<{ name: string }>("/company", { method: "PUT", body: { name } });
      changeMe({ company: saved.name });
      setName(saved.name);
      setToast("Saved. Everyone in the company sees the new name.");
    } catch (e) {
      setProblem(e instanceof ApiError ? e.fields.name ?? e.message : (e as Error).message); // the API checks the name
    } finally {
      setBusy(false);
    }
  }

  const changed = name.trim() !== me.company;
  return (
    <>
      <PageHead title="Settings" sub="Your company's settings in ZeeNote." />
      <main className="content" style={{ maxWidth: 720 }}>
        <form className="card flush" onSubmit={save} noValidate>
          <div className="card-head">
            <div>
              <h2>Company name</h2>
              <p className="soft small">Shown under the ZeeNote logo for everyone in the company.</p>
            </div>
          </div>
          <div className="card-body">
            <label>
              <span>Name</span>
              <input value={name} maxLength={60} onChange={(event) => { setName(event.target.value); setProblem(""); }}
                aria-invalid={Boolean(problem)} aria-describedby={problem ? "company-problem" : undefined} disabled={busy} />
              {problem && <span id="company-problem" className="field-problem">{problem}</span>}
            </label>
          </div>
          <div className="card-foot">
            <span className="faint small">Only you, as the owner, can change it.</span>
            <button className="btn main" disabled={busy || !changed}>
              {busy ? "Saving…" : changed ? "Save" : "Saved"}
            </button>
          </div>
        </form>
        <TeamsAndPeople onDone={setToast} />
      </main>
      {toast && <div className="toast" role="status"><Icon name="check" size={15} />{toast}</div>}
    </>
  );
}
