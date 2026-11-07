"use client";
import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from "react";
import { api, post, streamChat } from "@/lib/api";
import { safeHtml } from "@/lib/html";
import type { Card, ChatMsg, MemUsed, QuickReply } from "@/lib/types";
import { useOnline } from "@/lib/hooks";

export interface ChatHandle {
  pushBot: (html: string, extra?: Partial<ChatMsg>) => void;
}

const uid = () => Math.random().toString(36).slice(2, 9);
const PROMPTS: [string, string, "send" | "checkin"][] = [
  ["Asha restless after dinner", "Asha is restless after dinner", "send"],
  ["Log meds, sleep, diet", "Gave Asha metformin at 8 with breakfast, she felt nauseous for half an hour. Slept only 5 hours. Ate half her dinner.", "send"],
  ["Taking over Asha tonight", "I'm taking over Asha tonight. What should I know?", "send"],
  ["Check in on todos", "Check in on todos", "checkin"],
];

function MemChips({ items }: { items: MemUsed[] }) {
  const [open, setOpen] = useState(false);
  if (!items.length) return null;
  const obs = items.filter((i) => i.type === "observation").length;
  return (
    <div>
      <div className="memchips">
        <button className="mem" onClick={() => setOpen(!open)} aria-expanded={open}>
          Memory used · {items.length} {items.length === 1 ? "memory" : "memories"}{obs ? ` (${obs} observed pattern${obs > 1 ? "s" : ""})` : ""}
        </button>
      </div>
      {open && (
        <div className="ev" style={{ marginTop: 6 }}>
          <ul>
            {items.slice(0, 8).map((i) => (
              <li key={i.id}><b>{[i.date, i.caretaker].filter(Boolean).join(" · ")}</b> — {i.text}{i.proof_count ? ` (${i.proof_count}×)` : ""}</li>
            ))}
          </ul>
          <div className="note">Learned context is not a clinical instruction.</div>
        </div>
      )}
    </div>
  );
}

function Cards({ cards }: { cards: Card[] }) {
  return (
    <>
      {cards.map((c, i) => {
        if (c.type === "suggestion")
          return (
            <div key={i} className="ev suggest">
              <h5>{c.title}</h5>
              <ul>{c.evidence.map((e, j) => <li key={j}><b>{[fmtDate(e.date), e.caretaker].filter(Boolean).join(" · ")}</b> — {e.text}</li>)}</ul>
              {c.note && <div className="note">{c.note}</div>}
            </div>
          );
        if (c.type === "log_draft" || c.type === "handoff")
          return (
            <div key={i} className="ev">
              <table><tbody>{c.rows.map((r, j) => <tr key={j}><td>{r.label}</td><td dangerouslySetInnerHTML={{ __html: safeHtml(r.text) }} /></tr>)}</tbody></table>
              {c.note && <div className="note">{c.note}</div>}
            </div>
          );
        if (c.type === "compare")
          return (
            <div key={i} className="compare">
              <div className="off"><b>Memory off</b><div dangerouslySetInnerHTML={{ __html: safeHtml(c.off.text) }} /></div>
              <div className="on"><b>Memory on</b><div dangerouslySetInnerHTML={{ __html: safeHtml(c.on.text) }} />
                {c.on.cards.map((cc, k) => cc.type === "handoff" ? <ul key={k} style={{ paddingLeft: 16 }}>{cc.rows.map((r, j) => <li key={j}><b>{r.label}:</b> {r.text}</li>)}</ul> : null)}
              </div>
            </div>
          );
        return null;
      })}
    </>
  );
}

function fmtDate(d: string) {
  if (!d) return "";
  const dt = new Date(d + "T12:00:00");
  return isNaN(+dt) ? d : dt.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

const ChatPanel = forwardRef<ChatHandle, { patientId?: string; onBoardChanged: () => void; memoryOn: boolean; onMemory: (on: boolean) => void; greeting: string }>(
  function ChatPanel({ patientId, onBoardChanged, memoryOn, onMemory, greeting }, ref) {
    const [msgs, setMsgs] = useState<ChatMsg[]>([]);
    const [busy, setBusy] = useState(false);
    const [text, setText] = useState("");
    const box = useRef<HTMLDivElement>(null);
    const online = useOnline();

    const pushBot = useCallback((html: string, extra: Partial<ChatMsg> = {}) => setMsgs((m) => [...m, { id: uid(), role: "bot", html, ...extra }]), []);
    useImperativeHandle(ref, () => ({ pushBot }), [pushBot]);
    useEffect(() => { box.current?.scrollTo({ top: box.current.scrollHeight }); }, [msgs, busy]);

    const inited = useRef(false);
    useEffect(() => {
      if (!inited.current) {
        inited.current = true;
        pushBot(greeting);
        loadCheckins();
      }
      // W3: worker publishes due check-ins over SSE
      const es = new EventSource((process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1") + "/me/events", { withCredentials: true });
      es.onmessage = (e) => {
        const d = JSON.parse(e.data);
        if (d.type === "checkin") pushBot(d.prompt, { quick: checkinButtons(d.todo_id) });
        if (d.type === "board_changed") onBoardChanged();
      };
      return () => es.close();
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    const checkinButtons = (todo_id: string): QuickReply[] => [
      { label: "Completed", action: "checkin_status", payload: { todo_id, status: "done" } },
      { label: "Not done", action: "checkin_status", payload: { todo_id, status: "not_done" } },
      { label: "Skipped", action: "checkin_status", payload: { todo_id, status: "skipped" } },
    ];
    const loadCheckins = () => {
      api<{ todo_id: string; prompt: string }[]>("/me/checkins").then((rows) => {
        rows.slice(0, 1).forEach((r) => pushBot(r.prompt, { quick: checkinButtons(r.todo_id) }));
      }).catch(() => {});
    };

    const run = async (body: Record<string, unknown>, label?: string) => {
      if (busy) return;
      if (label) setMsgs((m) => [...m, { id: uid(), role: "me", html: safeHtml(label) }]);
      setBusy(true);
      const id = uid();
      let started = false;
      const patch = (f: (m: ChatMsg) => ChatMsg) => setMsgs((ms) => ms.map((m) => (m.id === id ? f(m) : m)));
      try {
        await streamChat({ ...body, patient_id: patientId }, ({ event, data }) => {
          if (!started) { started = true; setMsgs((ms) => [...ms, { id, role: "bot", html: "", cards: [] }]); }
          if (event === "token") patch((m) => ({ ...m, html: m.html + data.text }));
          else if (event === "card") patch((m) => ({ ...m, cards: [...(m.cards || []), data as Card] }));
          else if (event === "quick_replies") patch((m) => ({ ...m, quick: data.replies as QuickReply[] }));
          else if (event === "memory_used") patch((m) => ({ ...m, memory: data.items as MemUsed[] }));
          else if (event === "board_changed") onBoardChanged();
        });
      } catch (e) {
        pushBot(`Sorry, I couldn't reach the server (${(e as Error).message}). Your message wasn't lost — try again.`);
      } finally {
        setBusy(false);
      }
    };

    const clickQuick = (m: ChatMsg, q: QuickReply) => {
      setMsgs((ms) => ms.map((x) => (x.id === m.id ? { ...x, used: true } : x)));
      run({ action: q.action, payload: q.payload }, q.payload.detail || (q.label === "Skip detail" ? "Skip detail" : q.label));
    };
    const send = (t: string) => { if (t.trim()) { setText(""); run({ message: t.trim() }, t.trim()); } };

    const toggle = async () => {
      const next = !memoryOn;
      await post("/demo/memory-toggle", { enabled: next });
      onMemory(next);
      pushBot(next ? "Memory is <b>on</b>. I'll use what previous caretakers logged." : "Memory is <b>off</b>. I'll answer like an agent with no history — try asking about a handover.");
    };
    const compare = async () => {
      const q = "I'm taking over Asha tonight. What should I know?";
      setMsgs((m) => [...m, { id: uid(), role: "me", html: safeHtml("Compare memory on vs off: " + q) }]);
      try {
        const asha = await api<{ id: string; name: string }[]>("/patients");
        const pid = asha.find((p) => p.name.startsWith("Asha"))?.id;
        const d = await post("/demo/memory-toggle", { question: q, patient_id: pid });
        pushBot("Same question, answered both ways:", { cards: [{ type: "compare", off: d.off, on: d.on }] });
      } catch (e) { pushBot("Couldn't run the comparison: " + (e as Error).message); }
    };

    return (
      <aside className="chat" aria-label="Ask CareBridge">
        <div className="chat-h">
          <div className="mark" style={{ width: 28, height: 28, borderRadius: 8 }}>
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round"><path d="M3 15c3-6 6-6 9 0s6 6 9 0" /></svg>
          </div>
          <div><h3>Ask CareBridge</h3><div className="faint" style={{ fontSize: 12 }}>Logs, todos and handoffs, remembered</div></div>
          <div className="toggle">Memory <button className={"sw" + (memoryOn ? "" : " off")} onClick={toggle} aria-label="Toggle memory" aria-pressed={memoryOn} /></div>
        </div>
        {!online && <div className="banner-off" style={{ margin: 10 }}>You&apos;re offline. Messages will fail until you reconnect.</div>}
        <div className="msgs" ref={box} data-testid="msgs">
          {msgs.map((m) => (
            <div key={m.id} className={"m " + m.role}>
              {m.html && <div className="bubble" dangerouslySetInnerHTML={{ __html: m.role === "me" ? m.html : safeHtml(m.html) }} />}
              {m.cards && <Cards cards={m.cards} />}
              {m.memory && m.role === "bot" && <MemChips items={m.memory} />}
              {m.quick && m.quick.length > 0 && (
                <div className={"qr" + (m.used ? " used" : "")}>
                  {m.quick.map((q, i) => <button key={i} onClick={() => clickQuick(m, q)}>{q.label}</button>)}
                </div>
              )}
            </div>
          ))}
          {busy && <div className="m bot"><div className="bubble typing"><i /><i /><i /></div></div>}
        </div>
        <div className="compose">
          <div className="prompts">
            {PROMPTS.map(([label, t, kind]) => (
              <button key={label} onClick={() => (kind === "checkin" ? run({ action: "checkin_start", payload: {} }, t) : send(t))}>{label}</button>
            ))}
            <button onClick={compare}>Compare memory on/off</button>
          </div>
          <form className="in" onSubmit={(e) => { e.preventDefault(); send(text); }}>
            <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Log care or ask about a patient…" autoComplete="off" aria-label="Message" />
            <button className="btn primary" type="submit" disabled={busy}>Send</button>
          </form>
        </div>
      </aside>
    );
  },
);
export default ChatPanel;
