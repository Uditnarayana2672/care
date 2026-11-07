"use client";
import { useEffect, useState } from "react";
import { post } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useOnline } from "@/lib/hooks";
import { useToastFn } from "./Providers";

interface Form {
  full_name: string; age: string; preferred_language: string; gender: string;
  phone: string; address: string; ec_name: string; ec_relation: string; ec_phone: string;
  conditions: string[]; mobility_level: string; diet: string[]; hearing_vision: string;
  medications: { name: string; strength: string; times: ("morning" | "afternoon" | "night")[] }[];
  med_name: string; med_times: ("morning" | "afternoon" | "night")[]; allergy: string;
  wake: string; sleep: string; likes: string[];
}
const EMPTY: Form = {
  full_name: "", age: "", preferred_language: "English", gender: "", phone: "", address: "", ec_name: "", ec_relation: "", ec_phone: "",
  conditions: [], mobility_level: "", diet: [], hearing_vision: "", medications: [], med_name: "", med_times: [], allergy: "",
  wake: "06:30", sleep: "21:30", likes: [],
};
const KEY = "cb-enroll-draft";
const TITLES = ["About you", "How to reach you", "Your health", "Medicines & allergies", "Your day"];
const SUBS = ["", "", " · tap all that apply", " · a coordinator will check these before they are used", " · helps carers fit your routine"];

function Chips({ options, value, onChange, single }: { options: string[]; value: string[]; onChange: (v: string[]) => void; single?: boolean }) {
  return (
    <div className="big-chips" role={single ? "radiogroup" : "group"}>
      {options.map((o) => {
        const on = value.includes(o);
        return (
          <button key={o} type="button" className={cn(on && "on")} aria-pressed={on}
            onClick={() => onChange(single ? (on ? [] : [o]) : on ? value.filter((x) => x !== o) : [...value, o])}>{o}</button>
        );
      })}
    </div>
  );
}

export default function Enroll() {
  const toast = useToastFn();
  const online = useOnline();
  const [f, setF] = useState<Form>(EMPTY);
  const [step, setStep] = useState(1); // 1-5 form, 6 review, 7 done
  const [saved, setSaved] = useState("Saved");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [code, setCode] = useState("");
  const set = <K extends keyof Form>(k: K, v: Form[K]) => { setF((p) => ({ ...p, [k]: v })); setSaved("Saving…"); };

  useEffect(() => {
    try { const d = localStorage.getItem(KEY); if (d) { const j = JSON.parse(d); setF({ ...EMPTY, ...j.f }); setStep(Math.min(j.step || 1, 6)); } } catch {}
  }, []);
  useEffect(() => {
    const t = setTimeout(() => { try { localStorage.setItem(KEY, JSON.stringify({ f, step })); setSaved(online ? "Saved" : "Saved on this device"); } catch {} }, 500);
    return () => clearTimeout(t);
  }, [f, step, online]);

  const validate = () => {
    if (step === 1 && (f.full_name.trim().length < 2 || !(+f.age >= 18))) return "Please enter your name and age.";
    return "";
  };
  const next = () => { const e = validate(); setErr(e); if (!e) setStep((s) => s + 1); window.scrollTo(0, 0); };
  const addMed = () => {
    if (!f.med_name.trim()) return;
    setF((p) => ({ ...p, medications: [...p.medications, { name: p.med_name.trim(), strength: "", times: p.med_times }], med_name: "", med_times: [] }));
  };
  const submit = async () => {
    setBusy(true); setErr("");
    try {
      const meds = [...f.medications, ...(f.med_name.trim() ? [{ name: f.med_name.trim(), strength: "", times: f.med_times }] : [])];
      const r = await post("/enrollments", {
        full_name: f.full_name, age: +f.age, gender: f.gender, preferred_language: f.preferred_language, phone: f.phone, address: f.address,
        emergency_contact: { name: f.ec_name, relation: f.ec_relation, phone: f.ec_phone }, conditions: f.conditions,
        mobility_level: f.mobility_level, diet: f.diet, hearing_vision: f.hearing_vision, medications: meds,
        allergies: f.allergy.split(",").map((s) => s.trim()).filter(Boolean).map((substance) => ({ substance })),
        routine: { wake: f.wake, sleep: f.sleep, likes: f.likes }, source: "self",
      });
      setCode(r.code); setStep(7); try { localStorage.removeItem(KEY); } catch {}
      toast("Patient created · care memory ready");
    } catch (e) { setErr((e as Error).message || "We couldn't save. Your answers are kept on this device — please try again."); }
    finally { setBusy(false); }
  };
  const reset = () => { setF(EMPTY); setStep(1); setCode(""); };

  return (
    <div className="enroll">
      <h1 style={{ fontSize: 34 }}>Join CareBridge</h1>
      <p className="lead">Five short steps. You can stop any time — we save as you go.</p>
      {!online && <div className="banner-off" style={{ fontSize: 16 }}>You&apos;re offline. Keep going — your answers are saved on this device and we&apos;ll send them when you finish.</div>}
      <div className="steps" aria-label={`Step ${Math.min(step, 5)} of 5`}>{[1, 2, 3, 4, 5].map((i) => <div key={i} className={cn(i <= step && "on")} />)}</div>

      {step <= 5 && (
        <div className="estep on">
          <h2>{TITLES[step - 1]}</h2><div className="sub">Step {step} of 5{SUBS[step - 1]}</div>
          {step === 1 && (<>
            <div className="field"><label htmlFor="e-name">Your full name</label><input id="e-name" value={f.full_name} onChange={(e) => set("full_name", e.target.value)} autoComplete="name" /></div>
            <div className="row2">
              <div className="field"><label htmlFor="e-age">Age</label><input id="e-age" inputMode="numeric" value={f.age} onChange={(e) => set("age", e.target.value.replace(/\D/g, ""))} /></div>
              <div className="field"><label htmlFor="e-lang">Language you prefer</label>
                <select id="e-lang" value={f.preferred_language} onChange={(e) => set("preferred_language", e.target.value)}>{["English", "Telugu", "Hindi", "Kannada", "Tamil", "Urdu"].map((l) => <option key={l}>{l}</option>)}</select></div>
            </div>
            <div className="field"><label>Gender</label><Chips single options={["Female", "Male", "Prefer not to say"]} value={f.gender ? [f.gender] : []} onChange={(v) => set("gender", v[0] || "")} /></div>
          </>)}
          {step === 2 && (<>
            <div className="field"><label htmlFor="e-phone">Phone number</label><input id="e-phone" inputMode="tel" value={f.phone} onChange={(e) => set("phone", e.target.value)} /></div>
            <div className="field"><label htmlFor="e-addr">Home address</label><input id="e-addr" value={f.address} onChange={(e) => set("address", e.target.value)} /></div>
            <div className="row2">
              <div className="field"><label htmlFor="e-ec">Emergency contact</label><input id="e-ec" value={f.ec_name} onChange={(e) => set("ec_name", e.target.value)} /></div>
              <div className="field"><label htmlFor="e-ecp">Their phone</label><input id="e-ecp" inputMode="tel" value={f.ec_phone} onChange={(e) => set("ec_phone", e.target.value)} /></div>
            </div>
            <div className="field"><label>Who are they to you?</label><Chips single options={["Son", "Daughter", "Spouse", "Relative", "Friend"]} value={f.ec_relation ? [f.ec_relation] : []} onChange={(v) => set("ec_relation", v[0] || "")} /></div>
          </>)}
          {step === 3 && (<>
            <div className="field"><label>Health conditions</label><Chips options={["Diabetes", "High BP", "Heart", "Joint pain", "Memory issues", "Breathing", "Other"]} value={f.conditions} onChange={(v) => set("conditions", v)} /></div>
            <div className="field"><label>How do you walk?</label><Chips single options={["On my own", "With a stick", "With a walker", "Wheelchair", "Bedbound"]} value={f.mobility_level ? [f.mobility_level] : []} onChange={(v) => set("mobility_level", v[0] || "")} /></div>
            <div className="field"><label>Food</label><Chips options={["Vegetarian", "Non-veg", "Diabetic", "Soft food"]} value={f.diet} onChange={(v) => set("diet", v)} /></div>
            <div className="field"><label>Hearing & vision</label><Chips single options={["No trouble", "Hearing aid", "Glasses", "Both"]} value={f.hearing_vision ? [f.hearing_vision] : []} onChange={(v) => set("hearing_vision", v[0] || "")} /></div>
          </>)}
          {step === 4 && (<>
            {f.medications.map((m, i) => (
              <div className="medrow" key={i}><div><b>{m.name}</b><div className="muted" style={{ fontSize: 15 }}>{m.times.map((t) => t[0].toUpperCase() + t.slice(1)).join(" · ") || "Time not set"}</div></div>
                <button className="btn ghost" aria-label={`Remove ${m.name}`} onClick={() => setF((p) => ({ ...p, medications: p.medications.filter((_, j) => j !== i) }))}>✕</button></div>
            ))}
            <div className="field"><label htmlFor="e-med">Add a medicine</label><input id="e-med" placeholder="Name as on the strip" value={f.med_name} onChange={(e) => set("med_name", e.target.value)} /></div>
            <div className="field"><label>When do you take it?</label><Chips options={["morning", "afternoon", "night"].map((x) => x)} value={f.med_times as string[]} onChange={(v) => set("med_times", v as Form["med_times"])} /></div>
            <button className="btn" type="button" style={{ fontSize: 18, minHeight: 56 }} onClick={addMed}>+ Add this medicine</button>
            <div className="field" style={{ marginTop: 20 }}><label htmlFor="e-all">Allergies (separate with commas)</label><input id="e-all" value={f.allergy} onChange={(e) => set("allergy", e.target.value)} /></div>
          </>)}
          {step === 5 && (<>
            <div className="row2">
              <div className="field"><label htmlFor="e-wake">Wake up</label><input id="e-wake" type="time" value={f.wake} onChange={(e) => set("wake", e.target.value)} /></div>
              <div className="field"><label htmlFor="e-sleep">Sleep</label><input id="e-sleep" type="time" value={f.sleep} onChange={(e) => set("sleep", e.target.value)} /></div>
            </div>
            <div className="field"><label>Things you enjoy</label><Chips options={["Evening walk", "Prayer", "TV", "Music", "Talking to family"]} value={f.likes} onChange={(v) => set("likes", v)} /></div>
          </>)}
          {err && <div className="err" role="alert">{err}</div>}
        </div>
      )}

      {step === 6 && (
        <div className="estep on">
          <h2>Check your answers</h2><div className="sub">Almost done. Tap Back to change anything.</div>
          <dl className="review">
            <dt>Name</dt><dd>{f.full_name}, {f.age} · {f.preferred_language}</dd>
            <dt>Contact</dt><dd>{f.phone || "—"} · {f.address || "—"}</dd>
            <dt>Emergency contact</dt><dd>{f.ec_name ? `${f.ec_name} (${f.ec_relation || "—"}) ${f.ec_phone}` : "—"}</dd>
            <dt>Health</dt><dd>{[...f.conditions, f.mobility_level, ...f.diet].filter(Boolean).join(", ") || "—"}</dd>
            <dt>Medicines</dt><dd>{[...f.medications.map((m) => m.name), f.med_name].filter(Boolean).join(", ") || "None"}</dd>
            <dt>Allergies</dt><dd>{f.allergy || "None"}</dd>
            <dt>Day</dt><dd>Wake {f.wake}, sleep {f.sleep}{f.likes.length ? ` · ${f.likes.join(", ")}` : ""}</dd>
          </dl>
          {err && <div className="err" role="alert">{err}</div>}
        </div>
      )}

      {step === 7 && (
        <div className="estep on">
          <div className="done-card">
            <h2>You&apos;re enrolled</h2>
            <div className="sub">Your carer will use this to look after you.</div>
            <div className="code" data-testid="patient-code">{code}</div>
            <div className="muted" style={{ fontSize: 17 }}>Your care memory has been created. Medicines will be checked by a coordinator.</div>
          </div>
        </div>
      )}

      <div className="enav">
        <button className="btn" style={{ visibility: step > 1 && step < 7 ? "visible" : "hidden" }} onClick={() => setStep((s) => s - 1)}>Back</button>
        <span className="saved" style={{ visibility: step < 7 ? "visible" : "hidden" }} aria-live="polite">{saved}</span>
        {step < 6 && <button className="btn primary" onClick={next}>Next</button>}
        {step === 6 && <button className="btn primary" onClick={submit} disabled={busy}>{busy ? "Saving…" : "Finish"}</button>}
        {step === 7 && <button className="btn primary" onClick={reset}>Enroll another</button>}
      </div>
    </div>
  );
}
