"use client";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import type { BoardCard, Patient } from "@/lib/types";
import { Avatar, Badge, Empty, ErrorState, Loading } from "./ui";

const TABS = [["today", "Today"], ["timeline", "Timeline"], ["memory", "Memory"], ["alerts", "Alerts"]] as const;
const KIND: Record<string, [string, string]> = { helps: ["violet", "What helps"], fails: ["clay", "Why todos fail"], routine: ["teal", "Routine"], constraint: ["amber", "Timing constraint"] };
const fmt = (iso?: string | null) => (iso ? new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Kolkata" }) : "");

export function PatientList() {
  const q = useQuery({ queryKey: ["patients"], queryFn: () => api<Patient[]>("/patients") });
  if (q.isLoading) return <Loading />;
  if (q.isError) return <ErrorState error={q.error} retry={() => q.refetch()} />;
  if (!q.data?.length) return <Empty>No patients assigned to you yet.</Empty>;
  return (
    <>
      <h1 style={{ fontSize: 28, marginBottom: 14 }}>Patients</h1>
      <div className="grid2">
        {q.data.map((p) => (
          <Link key={p.id} href={`/patients/${p.id}`} className="pat-h" style={{ padding: 14 }}>
            <Avatar initials={p.initials} color={p.color} size={48} />
            <div><h3 style={{ fontSize: 20 }}>{p.name}</h3><div className="muted">{p.age} · {p.language} · {p.mobility}</div></div>
          </Link>
        ))}
      </div>
    </>
  );
}

export default function PatientView({ id }: { id: string }) {
  const router = useRouter();
  const [tab, setTab] = useState<(typeof TABS)[number][0]>("memory");
  const [cat, setCat] = useState("");
  const all = useQuery({ queryKey: ["patients"], queryFn: () => api<Patient[]>("/patients") });
  const p = useQuery({ queryKey: ["patient", id], queryFn: () => api<Patient>(`/patients/${id}`) });
  const mem = useQuery({ queryKey: ["pmem", id, cat], queryFn: () => api<any>(`/patients/${id}/memory${cat ? `?category=${cat}` : ""}`), enabled: tab === "memory" });
  const today = useQuery({ queryKey: ["ptoday", id], queryFn: () => api<BoardCard[]>(`/patients/${id}/today`), enabled: tab === "today" });
  const tl = useQuery({ queryKey: ["ptl", id], queryFn: () => api<any[]>(`/patients/${id}/timeline`), enabled: tab === "timeline" });
  const alerts = useQuery({ queryKey: ["alerts"], queryFn: () => api<any[]>("/alerts"), enabled: tab === "alerts" });
  const trends = useQuery({ queryKey: ["ptr", id], queryFn: () => api<any>(`/patients/${id}/trends`), enabled: tab === "alerts" });

  if (p.isLoading) return <Loading />;
  if (p.isError) return <ErrorState error={p.error} retry={() => p.refetch()} />;
  const d = p.data!;
  return (
    <>
      <div className="pat-h">
        <Avatar initials={d.initials} color={d.color} size={64} />
        <div>
          <h1>{d.name}</h1>
          <div className="muted">{d.age} · {d.gender} · Prefers {d.language} · Patient code {d.code}</div>
          <div className="facts">
            {d.mobility && <Badge tone="teal">{d.mobility}</Badge>}
            {d.diet && <Badge>{d.diet.split(";")[0]}</Badge>}
            {d.allergies?.map((a) => <Badge key={a.id} tone={a.verification === "verified" ? "rose" : "amber"}>Allergy: {a.substance} · {a.verification}</Badge>)}
            {d.medications?.filter((m) => m.verification !== "verified").map((m) => <Badge key={m.id} tone="amber">{m.name} · {m.verification}</Badge>)}
          </div>
        </div>
        <div className="pselect">
          <select className="btn" aria-label="Switch patient" value={id} onChange={(e) => router.push(`/patients/${e.target.value}`)}>
            {(all.data || []).map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
          </select>
        </div>
      </div>

      <div className="tabs" role="tablist">
        {TABS.map(([k, l]) => <button key={k} role="tab" aria-selected={tab === k} className={cn("chip", tab === k && "on")} onClick={() => setTab(k)}>{l}</button>)}
      </div>

      {tab === "memory" && (mem.isLoading ? <Loading /> : mem.isError ? <ErrorState error={mem.error} retry={() => mem.refetch()} /> : (
        <div className="grid2">
          <div className="panel">
            <h3>Observed patterns</h3>
            <p className="faint" style={{ marginTop: -4, fontSize: 13 }}>Consolidated from caretaker logs. Not clinical instructions.</p>
            {!mem.data.enabled && <div className="banner-off">Memory is switched off for this demo.</div>}
            {mem.data.observations.length === 0 && <Empty>No repeated patterns yet.</Empty>}
            {mem.data.observations.map((o: any) => (
              <div className="obs" key={o.id}>
                <div className="obs-top">
                  <div><h4>{o.text}</h4><Badge tone={KIND[o.kind]?.[0] || "grey"}>{KIND[o.kind]?.[1] || "Pattern"}</Badge></div>
                  <div className="proof">{o.proof_count}<small>times</small></div>
                </div>
                <div className="ev" style={{ marginTop: 8, border: 0, padding: 0 }}>
                  <ul>{o.evidence.map((e: any) => <li key={e.id}><b>{fmt(e.date)} · {e.caretaker}</b> — {e.text}</li>)}</ul>
                </div>
              </div>
            ))}
          </div>
          <div className="panel">
            <h3>Recent memories</h3>
            <p className="faint" style={{ marginTop: -4, fontSize: 13 }}>Every entry is linked to its source log.</p>
            <div className="filters">
              {["", "sleep", "diet", "mood", "medication_effect", "todo_outcome"].map((c) => (
                <button key={c} className={cn("chip", cat === c && "on")} onClick={() => setCat(c)}>{c ? c.replace("_", " ") : "All"}</button>
              ))}
            </div>
            {mem.data.recent.length === 0 && <Empty>Nothing remembered for this filter.</Empty>}
            <ul className="tl">
              {mem.data.recent.map((r: any) => (
                <li key={r.id}><span className="t">{fmt(r.date)}</span><div>{r.text} <span className="mem" title={`${r.source_type}:${r.source_id}`}>{r.context || r.source_type}</span></div></li>
              ))}
            </ul>
          </div>
        </div>
      ))}

      {tab === "today" && (today.isLoading ? <Loading /> : today.isError ? <ErrorState error={today.error} /> : (
        <div className="panel">
          <h3>Today for {d.name.split(" ")[0]}</h3>
          {!today.data?.length && <Empty>No todos today.</Empty>}
          <dl className="kv">
            {today.data?.sort((a, b) => a.due_time.localeCompare(b.due_time)).map((t) => (
              <div key={t.id} style={{ display: "contents" }}>
                <dt>{t.time}</dt>
                <dd>{t.title} · <Badge tone={t.status === "done" ? "teal" : t.status === "not_done" ? "rose" : "grey"}>{t.status.replace("_", " ")}</Badge> {t.memory_chip && <span className="mem">{t.memory_chip}</span>}</dd>
              </div>
            ))}
          </dl>
        </div>
      ))}

      {tab === "timeline" && (tl.isLoading ? <Loading /> : tl.isError ? <ErrorState error={tl.error} /> : (
        <div className="panel">
          <h3>Timeline</h3>
          {!tl.data?.length && <Empty>No history yet.</Empty>}
          <ul className="tl">{tl.data?.map((e) => <li key={e.kind + e.id}><span className="t">{fmt(e.at)}</span><div>{e.text} {e.by && <span className="faint">· {e.by}</span>} {e.severity !== "normal" && <Badge tone={e.severity === "urgent" ? "rose" : "amber"}>{e.severity}</Badge>}</div></li>)}</ul>
        </div>
      ))}

      {tab === "alerts" && (
        <div className="grid2">
          <div className="panel">
            <h3>Alerts</h3>
            {alerts.isLoading ? <Loading rows={2} /> : (alerts.data || []).filter((a) => a.patient_id === id).length === 0 ? <Empty>No alerts.</Empty> :
              (alerts.data || []).filter((a) => a.patient_id === id).map((a) => (
                <div className="ev warn" key={a.id} style={{ marginBottom: 10 }}>
                  <h5>{a.summary.split(/(?<=\.)\s/)[0]} <Badge tone={a.status === "open" ? "amber" : "grey"}>{a.status}</Badge></h5>
                  <div className="muted">{a.summary.split(/(?<=\.)\s/).slice(1).join(" ")}</div>
                  <ul>{a.evidence.slice(0, 5).map((e: any, i: number) => <li key={i}><b>{e.date} · {e.caretaker}</b> — {e.text}</li>)}</ul>
                </div>
              ))}
          </div>
          <div className="panel">
            <h3>Sleep, recent nights</h3>
            {trends.isLoading ? <Loading rows={1} /> : (
              <>
                <div className="spark">{(trends.data?.sleep || []).map((s: any, i: number, arr: any[]) => (
                  <div key={i} className={i >= arr.length - 3 && Number(s.value) < 6 ? "low" : ""} style={{ height: `${Math.min(100, (Number(s.value) / 9) * 100)}%` }} title={`${s.date}: ${s.value}h`}><span>{String(s.date).slice(8)}</span></div>
                ))}</div>
                <p className="muted" style={{ marginTop: 26, fontSize: 13.5 }}>Hours slept per logged night. Observation only — inform the coordinator if it worries you.</p>
              </>
            )}
          </div>
        </div>
      )}
    </>
  );
}
