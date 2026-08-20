"use client";

/**
 * Drawer — a side/bottom panel built on the native <dialog> element, so focus
 * trapping, inert background, Escape-to-close and the backdrop come from the
 * platform rather than from 200 lines of focus management.
 *
 * Enters with x/clip 24px over ~380ms, spring-ish. Slides from the bottom on
 * small screens because that is where thumbs are.
 *
 *   <Drawer open={open} onClose={() => setOpen(false)} title="Evidence trace">
 *     ...
 *   </Drawer>
 *   <Drawer open={open} onClose={close} title="Filters" side="bottom" footer={<button/>}>
 */

import { useEffect, useRef, type ReactNode } from "react";
import { Icon } from "./Icon";
import { drawerIn, drawerOut } from "@/lib/motion";
import s from "./ui.module.css";

export interface DrawerProps {
  open: boolean;
  onClose: () => void;
  title: string;
  /** Edge it enters from. Always bottom under 640px. */
  side?: "right" | "bottom";
  /** Extra controls in the header, left of the close button. */
  actions?: ReactNode;
  footer?: ReactNode;
  children: ReactNode;
}

export function Drawer({
  open,
  onClose,
  title,
  side = "right",
  actions,
  footer,
  children,
}: DrawerProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const d = dialogRef.current;
    if (!d) return;
    if (open && !d.open) {
      d.showModal();
      drawerIn(panelRef.current, side);
    } else if (!open && d.open) {
      d.close();
    }
  }, [open, side]);

  // Escape fires "cancel" on <dialog>; let the exit animation play first.
  useEffect(() => {
    const d = dialogRef.current;
    if (!d) return;
    const onCancel = (e: Event) => {
      e.preventDefault();
      void drawerOut(panelRef.current, side).then(onClose);
    };
    d.addEventListener("cancel", onCancel);
    return () => d.removeEventListener("cancel", onCancel);
  }, [onClose, side]);

  const close = () => void drawerOut(panelRef.current, side).then(onClose);

  return (
    <dialog ref={dialogRef} className={s.drawer} aria-label={title}>
      <div
        className={s.drawerShell}
        data-side={side}
        onMouseDown={(e) => {
          if (e.target === e.currentTarget) close();
        }}
      >
        <div className={s.drawerPanel} ref={panelRef}>
          <div className={s.grabber} aria-hidden="true" />
          <header className={s.drawerHead}>
            <h2 className={s.drawerTitle}>{title}</h2>
            <div className="row" style={{ gap: 8 }}>
              {actions}
              <button
                type="button"
                className={s.iconBtn}
                onClick={close}
                aria-label={`Close ${title}`}
              >
                <Icon name="close" size={18} />
              </button>
            </div>
          </header>
          <div className={s.drawerBody}>{children}</div>
          {footer && (
            <div
              className={s.drawerHead}
              style={{ borderBottom: 0, borderTop: "1px solid var(--line)" }}
            >
              {footer}
            </div>
          )}
        </div>
      </div>
    </dialog>
  );
}

export default Drawer;
