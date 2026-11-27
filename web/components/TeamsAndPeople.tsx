"use client";

import { useEffect, useState } from "react";
import { api, ApiError, type Me } from "@/lib/api";
import { useSession } from "@/lib/session";
import { Icon } from "@/components/Icon";
import { Select } from "@/components/Select";

type Person = { email: string; name: string; role: "Manager" | "Member" };
type NewPerson = { name: string; email: string; role: "Manager" | "Member" };
const NOBODY: NewPerson = { name: "", email: "", role: "Member" };

// The owner's teams and the people in each. Someone new joins the company and signs in with the shared password of v1
export function TeamsAndPeople({ onDone }: { onDone: (message: string) => void }) {
  const { me, changeMe } = useSession();
  const [teamId, setTeamId] = useState(me.teams[0]?.id ?? 0);
  const [people, setPeople] = useState<Person[] | null>(null);
  const [teamName, setTeamName] = useState("");
  const [teamProblem, setTeamProblem] = useState("");
  const [person, setPerson] = useState<NewPerson>(NOBODY);
  const [problems, setProblems] = useState<Partial<Record<keyof NewPerson, string>>>({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const team = me.teams.find((item) => item.id === teamId);

  useEffect(() => {
    if (!teamId) return;
    let stale = false; // another team chosen before the reply came
    setPeople(null);
    setError("");
    api<Person[]>(`/teams/${teamId}/people`).then((list) => !stale && setPeople(list)).catch((e) => !stale && setError(e.message));
    return () => {
      stale = true;
    };
  }, [teamId]);

  async function addTeam(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setTeamProblem("");
    try {
      const created = await api<{ id: number; name: string }>("/teams", { body: { name: teamName } });
      changeMe({ teams: (await api<Me>("/me")).teams }); // the menu and the pages know the team at once
      setTeamId(created.id);
      setTeamName("");
      onDone(`${created.name} is added. Add its people below.`);
    } catch (e) {
      setTeamProblem(e instanceof ApiError ? e.fields.name ?? e.message : (e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function addPerson(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setProblems({});
    setError("");
    try {
      const now = await api<Person[]>(`/teams/${teamId}/people`, { method: "PUT", body: person });
      setPeople(now);
      const added = now.find((who) => who.email === person.email.trim().toLowerCase());
      const renamed = added && added.name !== person.name.trim() ? ` They're already in ZeeNote as ${added.name}.` : "";
      onDone(`${added?.name ?? person.name.trim()} is in the ${team?.name} now.${renamed}`);
      setPerson(NOBODY);
    } catch (e) {
      const fields = e instanceof ApiError ? e.fields : {};
      setProblems(fields);
      if (!Object.keys(fields).length) setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function remove(who: Person) {
    setBusy(true);
    setError("");
    try {
      setPeople(await api<Person[]>(`/teams/${teamId}/people/${encodeURIComponent(who.email)}`, { method: "DELETE" }));
      onDone(`${who.name} is out of the ${team?.name}. Their reports stay.`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const field = (key: "name" | "email", label: string, placeholder: string) => (
    <label>
      <span>{label}</span>
      <input id={`person-${key}`} value={person[key]} placeholder={placeholder} disabled={busy}
        onChange={(event) => { setPerson({ ...person, [key]: event.target.value }); setProblems({ ...problems, [key]: undefined }); }}
        aria-invalid={Boolean(problems[key])} aria-describedby={problems[key] ? `person-${key}-problem` : undefined} />
      {problems[key] && <span id={`person-${key}-problem`} className="field-problem">{problems[key]}</span>}
    </label>
  );

  return (
    <section className="card flush">
      <div className="card-head">
        <div>
          <h2>Teams and people</h2>
          <p className="soft small">Add teams, and the people in each. New people sign in with their email and the shared password.</p>
        </div>
      </div>
      <div className="card-body">
        <form className="row" style={{ alignItems: "flex-start" }} onSubmit={addTeam} noValidate>
          <label className="grow">
            <span>New team</span>
            <input value={teamName} placeholder="e.g. Web Team" disabled={busy} onChange={(event) => { setTeamName(event.target.value); setTeamProblem(""); }}
              aria-invalid={Boolean(teamProblem)} aria-describedby={teamProblem ? "team-problem" : undefined} />
            {teamProblem && <span id="team-problem" className="field-problem">{teamProblem}</span>}
          </label>
          <button className="btn" style={{ marginTop: 25 }} disabled={busy}>Add team</button>
        </form>

        {me.teams.length === 0 ? (
          <div className="empty" style={{ padding: 24 }}>
            <span className="icon-ring"><Icon name="building" size={20} /></span>
            <b>No teams yet</b>
            <span className="small">Add your company&apos;s first team above.</span>
          </div>
        ) : (
          <>
            <div className="stack" style={{ gap: 6 }}>
              <span id="people-team" style={{ fontSize: 13, fontWeight: 500 }}>People in</span>
              <Select labelledBy="people-team" value={String(teamId)} onChange={(id) => setTeamId(Number(id))}
                options={me.teams.map((item) => ({ value: String(item.id), label: item.name }))} />
            </div>
            {error && <p className="notice bad" role="alert">{error}</p>}
            {people === null ? (
              <p className="soft small">Loading…</p>
            ) : people.length === 0 ? (
              <p className="soft small">Nobody is in the {team?.name} yet.</p>
            ) : (
              <ul className="people">
                {people.map((who) => (
                  <li key={who.email}>
                    <span className="avatar" aria-hidden="true">{who.name[0]}</span>
                    <span className="grow">
                      <b>{who.name}</b>
                      <span className="faint small">{who.email}</span>
                    </span>
                    <span className={`tag ${who.role === "Manager" ? "" : "off"}`}>{who.role}</span>
                    <button type="button" className="btn ghost icon danger" onClick={() => remove(who)} disabled={busy} aria-label={`Take ${who.name} out of the team`} title="Take out of the team">
                      <Icon name="trash" size={14} />
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <form className="stack" onSubmit={addPerson} noValidate style={{ gap: 12, borderTop: "1px solid var(--line)", paddingTop: 14 }}>
              <span style={{ fontWeight: 500 }}>Add someone to the {team?.name}</span>
              <div className="cols2">
                {field("name", "Name", "e.g. Olivia")}
                {field("email", "Email", "e.g. olivia@northwind.ai")}
              </div>
              <div className="row" style={{ alignItems: "flex-end" }}>
                <div className="stack grow" style={{ gap: 6 }}>
                  <span id="person-role" style={{ fontSize: 13, fontWeight: 500 }}>Role</span>
                  <Select labelledBy="person-role" value={person.role} onChange={(role) => setPerson({ ...person, role: role as NewPerson["role"] })} disabled={busy}
                    options={[{ value: "Member", label: "Member: writes reports" }, { value: "Manager", label: "Manager: also sets the template and rules" }]} />
                </div>
                <button className="btn main" disabled={busy}>Add to team</button>
              </div>
            </form>
          </>
        )}
      </div>
    </section>
  );
}
