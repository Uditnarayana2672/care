"use client";
import { DndContext, DragEndEvent, PointerSensor, TouchSensor, useDraggable, useDroppable, useSensor, useSensors } from "@dnd-kit/core";
import { useState } from "react";
import { cn } from "@/lib/cn";
import type { BoardCard } from "@/lib/types";
import { Avatar, catBadge } from "./ui";

export const REASONS = ["Refused", "Asleep", "Unwell", "No time", "Other"];

function Card({ c }: { c: BoardCard }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id: c.id, data: { card: c } });
  return (
    <div ref={setNodeRef} {...listeners} {...attributes} className={cn("card", isDragging && "dragging")} data-testid={`card-${c.title}`}>
      <div className="card-top">
        <span className="pt"><Avatar initials={c.patient_initials} color={c.patient_color} />{c.patient_name}</span>
        <span className="time">{c.time}</span>
      </div>
      <h4>{c.title}</h4>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
        <span className={cn("badge", catBadge[c.category] || "b-grey")}>{c.category[0].toUpperCase() + c.category.slice(1)}</span>
        {c.memory_chip && <span className="mem">{c.memory_chip}</span>}
      </div>
      <div className="reason">{c.reason}</div>
    </div>
  );
}

function Column({ k, label, cards }: { k: string; label: string; cards: BoardCard[] }) {
  const { setNodeRef, isOver } = useDroppable({ id: k });
  return (
    <div ref={setNodeRef} className={cn("col", isOver && "drop")} data-col={k}>
      <div className="col-h"><span>{label}</span><span className="n">{cards.length}</span></div>
      {cards.map((c) => <Card key={c.id} c={c} />)}
      {!cards.length && <div className="faint" style={{ fontSize: 12, padding: 6 }}>Nothing here</div>}
    </div>
  );
}

export default function Board({
  columns, onMove, onToast,
}: {
  columns: { key: string; label: string; cards: BoardCard[] }[];
  onMove: (card: BoardCard, status: string, reason?: string) => Promise<void>;
  onToast: (m: string) => void;
}) {
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }), useSensor(TouchSensor, { activationConstraint: { delay: 180, tolerance: 6 } }));
  const [ask, setAsk] = useState<BoardCard | null>(null);

  const onDragEnd = (e: DragEndEvent) => {
    const card = e.active.data.current?.card as BoardCard | undefined;
    const col = e.over?.id as string | undefined;
    if (!card || !col) return;
    const from = columns.find((c) => c.cards.some((x) => x.id === card.id))?.key;
    if (from === col) return;
    if (col === "not_done") return setAsk(card);
    if (col === "done") return void onMove(card, "done");
    if (from === "done") return void onMove(card, "todo"); // reopen
    if (col === "now") return void onMove(card, "in_progress");
    if (from === "not_done") return void onMove(card, "todo");
    onToast("Next / Later are set by the schedule and what I remember");
  };

  return (
    <>
      <DndContext sensors={sensors} onDragEnd={onDragEnd}>
        <div className="board" data-testid="board">
          {columns.map((c) => <Column key={c.key} k={c.key} label={c.label} cards={c.cards} />)}
        </div>
      </DndContext>
      {ask && (
        <div className="modal-bg" role="dialog" aria-modal="true" onClick={() => setAsk(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3 style={{ fontSize: 18 }}>Why wasn&apos;t it done?</h3>
            <p className="muted" style={{ margin: "4px 0 0" }}>{ask.patient_name} · {ask.title}</p>
            <div className="qr">
              {REASONS.map((r) => (
                <button key={r} onClick={() => { const c = ask; setAsk(null); onMove(c, "not_done", r.toLowerCase()); }}>{r}</button>
              ))}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
