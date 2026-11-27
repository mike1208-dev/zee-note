"use client";

import { usePathname, useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api, ApiError, getToken, setToken, TOKEN, type Me, type Team } from "./api";
import type { IconName } from "@/components/Icon";

const TEAM = "zeenote-team";

export type Page = { href: string; icon: IconName; label: string; group: string };

// Owner manages the company's teams. A Team Manager writes and manages their teams' template. A Team Member writes.
// A ZeeNote Admin is ZeeNote's own staff: they see the console, never a company's reports
export function roleName(me: Me): string {
  if (me.admin) return "ZeeNote Admin";
  if (me.owner) return "Owner";
  return me.teams.some((team) => team.role === "Manager") ? "Team Manager" : "Team Member";
}

export function pagesOf(me: Me): Page[] {
  if (me.admin) return [{ href: "/console", icon: "console" as const, label: "Overview", group: "ZeeNote" }];
  const writes = !me.owner;
  const edits = me.owner || me.teams.some((team) => team.role === "Manager");
  const group = me.owner ? "Company" : "My work";
  return [
    ...(writes ? [{ href: "/write", icon: "write" as const, label: "Write report", group }, { href: "/reports", icon: "reports" as const, label: "My reports", group }] : []),
    ...(edits ? [{ href: "/templates", icon: "templates" as const, label: "Template and rules", group }] : []),
    ...(me.owner ? [{ href: "/settings", icon: "settings" as const, label: "Settings", group }] : []),
  ];
}

// The teams to choose from on a page: the ones you write for, or the ones whose template you can change
export function teamsFor(me: Me, path: string): Team[] {
  return path.startsWith("/templates") ? me.teams.filter((team) => team.role !== "Member") : me.teams;
}

type Session = { me: Me; team: Team | undefined; teams: Team[]; chooseTeam: (id: number) => void; signOut: () => void; changeMe: (change: Partial<Me>) => void };

const SessionContext = createContext<Session | null>(null);

export function useSession(): Session {
  const session = useContext(SessionContext);
  if (!session) throw new Error("useSession is only for signed-in pages");
  return session;
}

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const path = usePathname();
  const [me, setMe] = useState<Me | null>(null);
  const [teamId, setTeamId] = useState<number | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    api<Me>("/me")
      .then((data) => {
        setMe(data);
        try {
          setTeamId(Number(localStorage.getItem(TEAM)) || null);
        } catch {}
      })
      .catch((e: ApiError) => {
        if (e.status === 401) {
          setToken("");
          router.replace("/login");
        } else setError(e.message);
      });
  }, [router]);

  // Signing out or in as someone else in another tab: this tab follows, so it never acts with another person's sign-in
  useEffect(() => {
    const follow = (event: StorageEvent) => {
      if (event.key === TOKEN && event.newValue !== event.oldValue) location.replace(event.newValue ? "/write" : "/login");
    };
    window.addEventListener("storage", follow);
    return () => window.removeEventListener("storage", follow);
  }, []);

  const chooseTeam = useCallback((id: number) => {
    setTeamId(id);
    try {
      localStorage.setItem(TEAM, String(id));
    } catch {}
  }, []);

  // after a change on a page, such as a new company name, so the menu shows it at once
  const changeMe = useCallback((change: Partial<Me>) => setMe((old) => (old ? { ...old, ...change } : old)), []);

  const signOut = useCallback(() => {
    api("/logout", { method: "POST" }).catch(() => {});
    setToken("");
    router.replace("/login");
  }, [router]);

  // a page this role doesn't have, such as an owner on Write report, goes to the role's first page
  const pages = me ? pagesOf(me) : [];
  const allowed = pages.some((page) => path.startsWith(page.href));
  const firstPage = pages[0]?.href ?? "/login";
  useEffect(() => {
    if (me && !allowed) router.replace(firstPage);
  }, [me, allowed, firstPage, router]);

  if (error) return <div className="center"><div className="card stack"><p className="error">{error}</p><button className="btn" onClick={() => location.reload()}>Try again</button></div></div>;
  if (!me || !allowed) return <div className="center soft">Loading…</div>;

  const teams = teamsFor(me, path);
  const team = teams.find((item) => item.id === teamId) ?? teams[0];
  return <SessionContext.Provider value={{ me, team, teams, chooseTeam, signOut, changeMe }}>{children}</SessionContext.Provider>;
}
