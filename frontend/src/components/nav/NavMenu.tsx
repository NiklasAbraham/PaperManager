import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { isItemActive, type NavItem } from "./navConfig";
import { linkCls } from "./navStyles";
import { useDismiss } from "./useDismiss";

function Chevron({ open }: { open: boolean }) {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="currentColor"
      aria-hidden="true"
      className={`w-3.5 h-3.5 transition-transform ${open ? "rotate-180" : ""}`}
    >
      <path
        fillRule="evenodd"
        d="M5.22 8.22a.75.75 0 0 1 1.06 0L10 11.94l3.72-3.72a.75.75 0 1 1 1.06 1.06l-4.25 4.25a.75.75 0 0 1-1.06 0L5.22 9.28a.75.75 0 0 1 0-1.06Z"
        clipRule="evenodd"
      />
    </svg>
  );
}

/** Dropdown button + panel. Opens on click; closes on outside click, Escape and route change. */
export function DropdownMenu({
  label,
  active,
  align = "left",
  children,
}: {
  label: ReactNode;
  active: boolean;
  align?: "left" | "right";
  children: (close: () => void) => ReactNode;
}) {
  const { pathname, search } = useLocation();
  // Open state is tied to the route it was opened on, so a navigation closes it without an effect.
  const routeKey = pathname + search;
  const [openAt, setOpenAt] = useState<string | null>(null);
  const open = openAt === routeKey;
  const setOpen = useCallback((f: boolean | ((o: boolean) => boolean)) => {
    setOpenAt((cur) => {
      const was = cur === routeKey;
      const next = typeof f === "function" ? f(was) : f;
      return next ? routeKey : null;
    });
  }, [routeKey]);
  const ref = useRef<HTMLDivElement>(null);
  const btnRef = useRef<HTMLButtonElement>(null);

  const close = useCallback(() => setOpen(false), [setOpen]);
  useDismiss(ref, open, close);

  // Escape returns focus to the button
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") btnRef.current?.focus();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <button
        ref={btnRef}
        type="button"
        aria-haspopup="true"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className={`${linkCls(active)} inline-flex items-center gap-1`}
      >
        {label}
        <Chevron open={open} />
      </button>
      {open && (
        <div
          className={`absolute top-full mt-1 z-50 w-72 max-w-[90vw] bg-raised border border-line rounded-xl shadow-lg p-1.5 ${
            align === "right" ? "right-0" : "left-0"
          }`}
        >
          {children(close)}
        </div>
      )}
    </div>
  );
}

/** One row of a dropdown: label plus one-line description. */
export function MenuLink({ item, onNavigate }: { item: NavItem; onNavigate?: () => void }) {
  const { pathname } = useLocation();
  const active = isItemActive(item, pathname);
  return (
    <NavLink
      to={item.to}
      end={item.end}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      className={`block rounded-lg px-3 py-2 transition-colors ${
        active ? "bg-accent-lo" : "hover:bg-base"
      }`}
    >
      <span className={`block text-sm font-medium ${active ? "text-accent" : "text-ink"}`}>{item.label}</span>
      <span className="block text-xs text-ink-3 leading-snug">{item.description}</span>
    </NavLink>
  );
}
