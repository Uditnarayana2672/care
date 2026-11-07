"use client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createContext, useContext, useState } from "react";
import { useToast } from "@/lib/hooks";

const ToastCtx = createContext<(m: string) => void>(() => {});
export const useToastFn = () => useContext(ToastCtx);

export default function Providers({ children }: { children: React.ReactNode }) {
  const [qc] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } }));
  const { msg, toast } = useToast();
  return (
    <QueryClientProvider client={qc}>
      <ToastCtx.Provider value={toast}>
        {children}
        <div className={"toast" + (msg ? " show" : "")} role="status">{msg}</div>
      </ToastCtx.Provider>
    </QueryClientProvider>
  );
}
