"use client";
import { useEffect, useState } from "react";

export function useToast() {
  const [msg, setMsg] = useState("");
  useEffect(() => {
    if (!msg) return;
    const t = setTimeout(() => setMsg(""), 2200);
    return () => clearTimeout(t);
  }, [msg]);
  return { msg, toast: setMsg };
}

export function useOnline() {
  const [on, setOn] = useState(true);
  useEffect(() => {
    setOn(navigator.onLine);
    const u = () => setOn(true);
    const d = () => setOn(false);
    window.addEventListener("online", u);
    window.addEventListener("offline", d);
    return () => { window.removeEventListener("online", u); window.removeEventListener("offline", d); };
  }, []);
  return on;
}
