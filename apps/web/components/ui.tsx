import { cn } from "@/lib/cn";

export function Avatar({ initials, color, size }: { initials: string; color: string; size?: number }) {
  return (
    <span className="av" style={{ background: color, ...(size ? { width: size, height: size, fontSize: size / 2.9 } : {}) }}>
      {initials}
    </span>
  );
}

export const catBadge: Record<string, string> = {
  medication: "b-teal", meal: "b-clay", hygiene: "b-grey", mobility: "b-violet", vitals: "b-amber",
};

export function Loading({ rows = 3 }: { rows?: number }) {
  return <div style={{ display: "grid", gap: 10 }} aria-busy="true">{Array.from({ length: rows }).map((_, i) => <div key={i} className="skeleton" />)}</div>;
}
export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="state">{children}</div>;
}
export function ErrorState({ error, retry }: { error: unknown; retry?: () => void }) {
  return (
    <div className="state err" role="alert">
      {(error as Error)?.message || "Something went wrong."}
      {retry && <div><button className="btn" style={{ marginTop: 10 }} onClick={retry}>Try again</button></div>}
    </div>
  );
}
export function Badge({ tone = "grey", children }: { tone?: string; children: React.ReactNode }) {
  return <span className={cn("badge", "b-" + tone)}>{children}</span>;
}
