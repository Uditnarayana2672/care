export type Role = "caretaker" | "coordinator" | "admin";
export interface Me { id: string; name: string; role: Role; email: string }
export interface DemoUser { id: string; email: string; name: string; role: Role }
export interface Evidence { id?: string; date: string; caretaker: string; text: string }
export interface BoardCard {
  id: string; patient_id: string; patient_name: string; patient_initials: string; patient_color: string; title: string;
  time: string; due_time: string; category: string; status: string; reason: string; memory_chip: string; score: number; overdue: boolean;
}
export interface BoardAlert { id: string; patient_id: string; patient_name: string; kind: string; signal: string; summary: string; evidence: Evidence[]; status: string }
export interface Board {
  date: string;
  columns: { key: string; label: string; cards: BoardCard[] }[];
  patients: { id: string; name: string; initials: string; color: string }[];
  alerts: BoardAlert[];
  stats: { patients: number; open: number; done: number };
}
export interface Patient {
  id: string; name: string; initials: string; color: string; age: number; gender: string; language: string; mobility: string; diet: string; code: string;
  hearing_vision?: string; phone?: string; address?: string; conditions?: string[];
  medications?: { id: string; name: string; strength: string; times: string[]; verification: string }[];
  allergies?: { id: string; substance: string; reaction: string; verification: string }[];
  routines?: { kind: string; time: string | null; notes: string }[];
}
export interface MemUsed { id: string; date: string; caretaker: string; text: string; type: string; proof_count: number }
export interface QuickReply { label: string; action: string; payload: Record<string, any> }
export type Card =
  | { type: "suggestion"; kind: string; id: string; title: string; text: string; evidence: Evidence[]; note?: string }
  | { type: "log_draft"; title: string; rows: { label: string; text: string }[]; note?: string }
  | { type: "handoff"; title: string; rows: { label: string; text: string }[]; note?: string }
  | { type: "compare"; off: { text: string; cards: Card[] }; on: { text: string; cards: Card[] } };
export interface ChatMsg {
  id: string; role: "bot" | "me"; html: string; cards?: Card[]; quick?: QuickReply[]; memory?: MemUsed[]; used?: boolean;
}
