"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, setToken } from "@/lib/api";
import { Icon } from "@/components/Icon";

// The first version has sample accounts only. Every one uses the same password
const ACCOUNTS = [
  ["dan@zeenote.ai", "Company Owner (Dan), ZeeSpires"],
  ["illia@zeenote.ai", "Team Manager (Illia), ZeeSpires: Cova, Commity and AI-Training teams"],
  ["mike@zeenote.ai", "Team Member (Mike), ZeeSpires: Cova and AI-Training teams"],
  ["nora@northwind.ai", "Company Owner (Nora), Northwind"],
  ["admin@zeenote.ai", "ZeeNote Admin, every company"],
];
// Where the password is set is shown only on this computer. Through a shared link, people get the password from you
const isLocal = () => typeof location !== "undefined" && ["localhost", "127.0.0.1"].includes(location.hostname);

export default function Login() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [local, setLocal] = useState(false);
  const [shown, setShown] = useState(false);
  const [problems, setProblems] = useState<{ email?: string; password?: string }>({});
  useEffect(() => setLocal(isLocal()), []);

  // Checked here, so each problem shows under its own field like the rest of ZeeNote
  function fieldsOk(): boolean {
    const found = {
      email: !email.trim() ? "Write your email." : /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim()) ? undefined : "Write an email such as mike@zeenote.ai.",
      password: password ? undefined : "Write your password.",
    };
    setProblems(found);
    const first = found.email ? "email" : found.password ? "password" : "";
    if (first) document.getElementById(`login-${first}`)?.focus();
    return !first;
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    if (!fieldsOk()) return;
    setBusy(true);
    setError("");
    try {
      const { token } = await api<{ token: string }>("/login", { body: { email, password } });
      setToken(token);
      router.replace("/write"); // an owner is sent on to their own first page
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <div className="center">
      <div className="stack" style={{ width: "min(100%, 420px)" }}>
        <div className="brand" style={{ justifyContent: "center", fontSize: 24 }}>
          <img src="/zeenote-mark.png" alt="" /> ZeeNote
        </div>
        <form className="card stack" onSubmit={submit} noValidate>
          <h1>Sign in</h1>
          <label>
            Email
            <input id="login-email" type="email" value={email} onChange={(event) => { setEmail(event.target.value); setProblems({ ...problems, email: undefined }); }}
              autoComplete="username" aria-invalid={Boolean(problems.email)} aria-describedby={problems.email ? "login-email-problem" : undefined} />
            {problems.email && <span id="login-email-problem" className="field-problem">{problems.email}</span>}
          </label>
          <label>
            Password
            <span className="with-button">
              <input id="login-password" type={shown ? "text" : "password"} value={password} onChange={(event) => { setPassword(event.target.value); setProblems({ ...problems, password: undefined }); }}
                autoComplete="current-password" aria-invalid={Boolean(problems.password)} aria-describedby={problems.password ? "login-password-problem" : undefined} />
              <button type="button" className="btn ghost icon" onClick={() => setShown(!shown)} aria-label={shown ? "Hide password" : "Show password"} aria-pressed={shown} title={shown ? "Hide password" : "Show password"}>
                <Icon name={shown ? "eyeOff" : "eye"} />
              </button>
            </span>
            {problems.password && <span id="login-password-problem" className="field-problem">{problems.password}</span>}
          </label>
          {error && (
            <p className="notice bad row" role="alert" style={{ gap: 8 }}>
              <Icon name="alert" size={15} /> {error}
            </p>
          )}
          <button className="btn main" disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>
        <div className="card stack small">
          <p>
            <b>Sample accounts</b> ·{" "}
            {local ? (
              <>the password is <code>ZEENOTE_PASSWORD</code> in <code>.env</code>, or <code>zeenote</code> if it isn&apos;t set</>
            ) : (
              <>ask the person who shared this link for the password</>
            )}
          </p>
          {ACCOUNTS.filter(([address]) => local || !address.startsWith("admin@")).map(([address, role]) => (
            <button key={address} className="link" style={{ textAlign: "left" }} onClick={() => { setEmail(address); setProblems({ ...problems, email: undefined }); }}>
              {address} <span className="soft">· {role}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
