"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, post } from "@/lib/api";
import { useToastFn } from "./Providers";
import { Empty, ErrorState, Loading } from "./ui";

export default function Coordinator() {
  const qc = useQueryClient();
  const toast = useToastFn();
  const q = useQuery({ queryKey: ["verifs"], queryFn: () => api<any>("/coordinator/verifications") });
  const decide = useMutation({
    mutationFn: (v: { id: string; kind: string; decision: string }) => post(`/coordinator/verifications/${v.id}`, { kind: v.kind, decision: v.decision }),
    onSuccess: () => { toast("Saved · todos will update"); qc.invalidateQueries({ queryKey: ["verifs"] }); },
    onError: (e: Error) => toast(e.message),
  });
  const resolve = useMutation({
    mutationFn: (id: string) => post(`/alerts/${id}/resolve`),
    onSuccess: () => { toast("Marked resolved"); qc.invalidateQueries({ queryKey: ["verifs"] }); },
  });
  if (q.isLoading) return <Loading />;
  if (q.isError) return <ErrorState error={q.error} retry={() => q.refetch()} />;
  return (
    <>
      <h1 style={{ fontSize: 28, marginBottom: 14 }}>Coordinator</h1>
      <div className="grid2">
        <div className="panel">
          <h3>Verify medical data</h3>
          {q.data.queue.length === 0 ? <Empty>Nothing waiting for verification.</Empty> : (
            <table className="qtable"><thead><tr><th>Patient</th><th>Item</th><th>Source</th><th /></tr></thead>
              <tbody>{q.data.queue.map((r: any) => (
                <tr key={r.id}><td>{r.patient}</td><td>{r.item}</td><td>{r.source}</td>
                  <td className="act">
                    <button className="btn primary" disabled={decide.isPending} onClick={() => decide.mutate({ id: r.id, kind: r.kind, decision: "verified" })}>Verify</button>
                    <button className="btn" disabled={decide.isPending} onClick={() => decide.mutate({ id: r.id, kind: r.kind, decision: "rejected" })}>Reject</button>
                  </td></tr>
              ))}</tbody></table>
          )}
        </div>
        <div className="panel">
          <h3>Escalations</h3>
          {q.data.escalations.length === 0 ? <Empty>No open escalations.</Empty> : q.data.escalations.map((a: any) => (
            <div className="ev warn" key={a.id} style={{ marginBottom: 10 }}>
              <h5>{a.patient} · {a.summary.split(/(?<=\.)\s/)[0]}</h5>
              <div className="muted">{a.summary.split(/(?<=\.)\s/).slice(1).join(" ")}</div>
              <ul>{a.evidence.slice(0, 3).map((e: any, i: number) => <li key={i}><b>{e.date} · {e.caretaker}</b> — {e.text}</li>)}</ul>
              <div className="act"><span className="badge b-grey">{a.status}</span><button className="btn primary" onClick={() => resolve.mutate(a.id)}>Mark resolved</button></div>
            </div>
          ))}
        </div>
      </div>
    </>
  );
}
