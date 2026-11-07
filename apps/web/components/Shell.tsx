"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { api, post } from "@/lib/api";
import { cn } from "@/lib/cn";
import type { DemoUser, Me } from "@/lib/types";
import { ErrorState, Loading } from "./ui";

const Logo = ({ s = 18 }: { s?: number }) => (
  <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round">
    <path d="M3 15c3-6 6-6 9 0s6 6 9 0" />
  </svg>
);

export default function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const qc = useQueryClient();
  const me = useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/auth/me"), retry: false });
  const users = useQuery({ queryKey: ["demo-users"], queryFn: () => api<DemoUser[]>("/auth/demo-users"), enabled: !me.data });
  const allUsers = useQuery({ queryKey: ["demo-users-all"], queryFn: () => api<DemoUser[]>("/auth/demo-users"), enabled: !!me.data });

  useEffect(() => {
    try {
      const t = localStorage.getItem("cb-theme");
      if (t) document.documentElement.dataset.theme = t;
    } catch {}
  }, []);

  const public_ = path.startsWith("/enroll");
  const login = async (email: string) => {
    await post("/auth/demo-login", { email });
    qc.removeQueries({ predicate: (q) => q.queryKey[0] !== "me" });
    await qc.refetchQueries({ queryKey: ["me"] });
  };
  const switchUser = async (email: string) => {
    await login(email);
    const role = allUsers.data?.find((u) => u.email === email)?.role;
    router.push(role === "coordinator" ? "/coordinator" : "/dashboard");
  };
  const toggleTheme = () => {
    const r = document.documentElement;
    const dark = r.dataset.theme ? r.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    r.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem("cb-theme", r.dataset.theme); } catch {}
  };
  const role = me.data?.role;
  const nav = [
    ...(role !== "coordinator" ? [{ href: "/dashboard", label: "Today" }] : []),
    { href: "/patients", label: "Patients" },
    { href: "/enroll", label: "Enroll" },
    ...(role === "coordinator" ? [{ href: "/coordinator", label: "Coordinator" }] : []),
  ];

  return (
    <>
      <header className="top">
        <div className="top-in">
          <Link className="brand" href="/dashboard">
            <div className="mark"><Logo /></div>CareBridge
          </Link>
          <nav className="nav" aria-label="Main">
            {nav.map((n) => (
              <Link key={n.href} href={n.href} className={cn(path.startsWith(n.href) && "on")}>{n.label}</Link>
            ))}
          </nav>
          <div className="spacer" />
          <div className="who">
            {me.data && (
              <>
                <span className="faint" style={{ fontSize: 13 }}>Signed in as</span>
                <select aria-label="Switch demo user" value={me.data.email} onChange={(e) => switchUser(e.target.value)}>
                  {(allUsers.data || []).map((u) => (
                    <option key={u.id} value={u.email}>{u.name} · {u.role[0].toUpperCase() + u.role.slice(1)}</option>
                  ))}
                </select>
              </>
            )}
            <button className="icon-btn" onClick={toggleTheme} title="Toggle theme" aria-label="Toggle theme">◐</button>
          </div>
        </div>
      </header>
      <main className="wrap">
        {public_ || me.data ? (
          children
        ) : me.isLoading ? (
          <Loading />
        ) : users.isError ? (
          <ErrorState error={users.error} retry={() => users.refetch()} />
        ) : (
          <div className="center-card">
            <h2 style={{ fontSize: 24 }}>Choose a demo user</h2>
            <p className="muted">Synthetic data only. Pick who you are to continue.</p>
            {(users.data || []).map((u) => (
              <button key={u.id} className="btn" onClick={() => switchUser(u.email)}>
                <b>{u.name}</b> <span className="faint">· {u.role}</span>
              </button>
            ))}
          </div>
        )}
      </main>
    </>
  );
}
