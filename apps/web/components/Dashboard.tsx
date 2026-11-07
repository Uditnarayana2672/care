"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { api, patch, post } from "@/lib/api";
import type { Board as BoardT, BoardCard, Me } from "@/lib/types";
import Board from "./Board";
import ChatPanel, { ChatHandle } from "./ChatPanel";
import { useToastFn } from "./Providers";
import { Avatar, ErrorState, Loading } from "./ui";
import { cn } from "@/lib/cn";

export default function Dashboard() {
  const qc = useQueryClient();
  const toast = useToastFn();
  const chat = useRef<ChatHandle>(null);
  const [filter, setFilter] = useState("all");
  const [memoryOn, setMemoryOn] = useState(true);
  const me = useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/auth/me") });
  const board = useQuery({ queryKey: ["board"], queryFn: () => api<BoardT>("/me/board"), refetchInterval: 60_000 });
  const refresh = () => qc.invalidateQueries({ queryKey: ["board"] });

  const move = useMutation({
    mutationFn: ({ card, status, reason }: { card: BoardCard; status: string; reason?: string }) =>
      patch(`/todos/${card.id}`, { status, reason: reason || "" }),
    onSuccess: async (res, { card, status }) => {
      toast(status === "done" || status === "not_done" ? "Status saved and retained to memory" : "Status updated");
      await refresh();
      if (res.suggestion)
        chat.current?.pushBot(`Saved. Here's what I found for <b>${card.patient_name.split(" ")[0]}</b>:`, {
          cards: [{ type: "suggestion", kind: "reschedule", id: res.suggestion.id, title: res.suggestion.title, text: res.suggestion.text, evidence: res.suggestion.evidence, note: "Observed pattern — not a clinical instruction. You decide." }],
          quick: [
            { label: "Yes, move it", action: "accept_suggestion", payload: { id: res.suggestion.id } },
            { label: "Keep as is", action: "dismiss_suggestion", payload: { id: res.suggestion.id } },
          ],
        });
      if (res.coordinator_hint) chat.current?.pushBot(res.coordinator_hint);
    },
    onError: (e: Error) => toast(e.message),
  });
  const ack = useMutation({ mutationFn: (id: string) => post(`/alerts/${id}/ack`), onSuccess: () => { toast("Coordinator notified"); refresh(); } });

  if (board.isLoading) return <Loading rows={4} />;
  if (board.isError) return <ErrorState error={board.error} retry={() => board.refetch()} />;
  const b = board.data!;
  const first = me.data?.name.split(" ")[0] ?? "";
  const hour = new Date().getHours();
  const greet = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
  const cols = b.columns.map((c) => ({ ...c, cards: c.cards.filter((x) => filter === "all" || x.patient_id === filter) }));
  const date = new Date(b.date + "T12:00:00").toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" });

  return (
    <div className="dash">
      <div>
        <div className="hello">
          <div>
            <div className="faint" style={{ fontSize: 13, fontWeight: 600 }}>{date}</div>
            <h1>{greet}, {first}</h1>
          </div>
          <div className="stats">
            <div className="stat"><b>{b.stats.patients}</b><span>Patients</span></div>
            <div className="stat"><b>{b.stats.open}</b><span>Open todos</span></div>
            <div className="stat"><b>{b.stats.done}</b><span>Done</span></div>
          </div>
        </div>

        {b.alerts.map((a) => (
          <div className="alert" key={a.id} role="alert" style={a.status !== "open" ? { opacity: 0.55 } : undefined}>
            <div className="dot" />
            <div style={{ flex: 1 }}>
              <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                <b>{a.patient_name} · {a.summary.split(/(?<=\.)\s/)[0].replace(/\.$/, "")}</b>
                <span className="badge b-amber">{a.kind === "trend" ? "Trend watch" : "Escalation"}</span>
                <span className="mem">{a.evidence.length} memories</span>
              </div>
              <p>{a.summary.split(/(?<=\.)\s/).slice(1).join(" ")}</p>
            </div>
            <button className="btn" disabled={a.status !== "open" || ack.isPending} onClick={() => ack.mutate(a.id)}>
              {a.status === "open" ? "Acknowledge" : "Acknowledged"}
            </button>
          </div>
        ))}

        <div className="filters">
          <button className={cn("chip", filter === "all" && "on")} onClick={() => setFilter("all")}>All patients</button>
          {b.patients.map((p) => (
            <button key={p.id} className={cn("chip", filter === p.id && "on")} onClick={() => setFilter(p.id)}>
              <Avatar initials={p.initials} color={p.color} />{p.name}
            </button>
          ))}
        </div>
        <Board columns={cols} onToast={toast} onMove={async (card, status, reason) => { await move.mutateAsync({ card, status, reason }).catch(() => {}); }} />
      </div>

      <ChatPanel
        ref={chat}
        patientId={filter === "all" ? undefined : filter}
        onBoardChanged={refresh}
        memoryOn={memoryOn}
        onMemory={(on) => { setMemoryOn(on); refresh(); }}
        greeting={
          b.patients.length === 1 && first === "Rohan"
            ? `Hi ${first}. You're covering <b>${b.patients[0].name}</b>. Want a handoff briefing? Try "Taking over ${b.patients[0].name.split(" ")[0]} tonight".`
            : `${greet}, ${first}. You have <b>${b.stats.patients} patients</b> today. I've ordered your board using what I know about each of them.`
        }
      />
    </div>
  );
}
