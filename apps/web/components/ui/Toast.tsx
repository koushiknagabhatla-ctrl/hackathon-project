"use client";

/**
 * Toast — transient feedback that never swallows something important.
 * Non-critical toasts auto-dismiss after 6s. Critical ones NEVER do: they stay
 * until dismissed, and they announce assertively to screen readers.
 *
 * The provider is already mounted in app/layout.tsx. Lane E only needs:
 *
 *   const toast = useToast();
 *   toast.push({ title: "Gate closed", body: "Verified by read-back.", tone: "ok" });
 *   toast.push({ title: "Policy denied", body: reason, tone: "bad", critical: true });
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Icon, type IconName } from "./Icon";
import { toastIn } from "@/lib/motion";
import { cx } from "@/lib/format";
import s from "./ui.module.css";

export type ToastTone = "info" | "ok" | "warn" | "bad";

export interface ToastInput {
  title: string;
  body?: string;
  tone?: ToastTone;
  /** Critical toasts never auto-dismiss and are announced assertively. */
  critical?: boolean;
  /** Override the auto-dismiss delay in ms. Ignored when critical. */
  timeout?: number;
}

interface ToastItem extends ToastInput {
  id: number;
}

const TONE: Record<ToastTone, { cls: string; icon: IconName; color: string }> = {
  info: { cls: "toneInfo", icon: "info", color: "var(--sev-info)" },
  ok: { cls: "toneOk", icon: "check", color: "var(--ok)" },
  warn: { cls: "toneWarn", icon: "major", color: "var(--warn)" },
  bad: { cls: "toneBad", icon: "critical", color: "var(--bad)" },
};

interface ToastApi {
  push: (t: ToastInput) => number;
  dismiss: (id: number) => void;
}

const Ctx = createContext<ToastApi | null>(null);

export function useToast(): ToastApi {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useToast must be used inside <ToastProvider>");
  return ctx;
}

function ToastRow({ t, onDismiss }: { t: ToastItem; onDismiss: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const tone = TONE[t.tone ?? "info"];

  useEffect(() => {
    toastIn(ref.current);
    if (t.critical) return;
    const ms = t.timeout ?? 6000;
    const timer = setTimeout(onDismiss, ms);
    return () => clearTimeout(timer);
  }, [t.critical, t.timeout, onDismiss]);

  return (
    <div
      ref={ref}
      className={cx(s.toast, s[tone.cls])}
      style={{ "--tone": tone.color } as React.CSSProperties}
      role={t.critical ? "alert" : "status"}
      aria-live={t.critical ? "assertive" : "polite"}
    >
      <span className={s.toastIcon}>
        <Icon name={tone.icon} size={16} />
      </span>
      <div>
        <div className={s.toastTitle}>{t.title}</div>
        {t.body && <div className={s.toastBody}>{t.body}</div>}
      </div>
      <button
        type="button"
        className={s.iconBtn}
        style={{ width: 32, height: 32 }}
        onClick={onDismiss}
        aria-label={`Dismiss: ${t.title}`}
      >
        <Icon name="close" size={14} />
      </button>
    </div>
  );
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const next = useRef(1);

  const dismiss = useCallback((id: number) => {
    setItems((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const push = useCallback((t: ToastInput) => {
    const id = next.current++;
    setItems((prev) => [...prev.slice(-3), { ...t, id }]);
    return id;
  }, []);

  const api = useMemo(() => ({ push, dismiss }), [push, dismiss]);

  return (
    <Ctx.Provider value={api}>
      {children}
      <div className={s.toastHost} aria-label="Notifications">
        {items.map((t) => (
          <ToastRow key={t.id} t={t} onDismiss={() => dismiss(t.id)} />
        ))}
      </div>
    </Ctx.Provider>
  );
}

export default ToastProvider;
