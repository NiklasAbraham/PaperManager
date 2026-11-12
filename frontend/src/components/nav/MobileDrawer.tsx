import { useEffect } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { useAppSettings } from "../../contexts/SettingsContext";
import { useAuth } from "../../contexts/AuthContext";
import { GROUP_LABELS, itemsFor, isItemActive, type NavGroup } from "./navConfig";
import { confirmLogout } from "./navStyles";

const GROUPS: NavGroup[] = ["primary", "explore", "tools", "account"];

/** Full-height drawer for screens below md: every entry, grouped, closes on navigation. */
export default function MobileDrawer({ onClose }: { onClose: () => void }) {
  const { settings, update } = useAppSettings();
  const { isAdmin, username, logout } = useAuth();
  const { pathname } = useLocation();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [onClose]);

  return (
    <div role="dialog" aria-modal="true" aria-label="Navigation" className="fixed inset-0 z-50 flex flex-col bg-raised md:hidden">
      <div className="flex items-center justify-between border-b border-line px-4 py-2">
        <span className="text-sm font-semibold text-ink">{username ?? "Menu"}</span>
        <button
          type="button"
          aria-label="Close menu"
          onClick={onClose}
          className="p-2 rounded-lg border border-line text-ink-2 hover:text-accent hover:border-accent-border"
        >
          <svg viewBox="0 0 20 20" fill="currentColor" aria-hidden="true" className="w-5 h-5">
            <path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" />
          </svg>
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-3 py-3">
        {GROUPS.map((g) => (
          <section key={g} aria-label={GROUP_LABELS[g]} className="mb-4">
            <h2 className="px-3 pb-1 text-xs font-medium text-ink-3 uppercase tracking-wide">{GROUP_LABELS[g]}</h2>
            {itemsFor(g, isAdmin).map((item) => {
              const active = isItemActive(item, pathname);
              return (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  onClick={onClose}
                  aria-current={active ? "page" : undefined}
                  className={`block rounded-lg px-3 py-2.5 ${active ? "bg-accent-lo" : "hover:bg-base"}`}
                >
                  <span className={`block text-sm font-medium ${active ? "text-accent" : "text-ink"}`}>{item.label}</span>
                  <span className="block text-xs text-ink-3 leading-snug">{item.description}</span>
                </NavLink>
              );
            })}
            {g === "account" && (
              <>
                <button
                  type="button"
                  role="switch"
                  aria-checked={settings.debugMode}
                  onClick={() => update({ debugMode: !settings.debugMode })}
                  className="w-full flex items-center justify-between rounded-lg px-3 py-2.5 text-left hover:bg-base"
                >
                  <span className="text-sm font-medium text-ink">Debug mode</span>
                  <span className={`text-xs font-semibold ${settings.debugMode ? "text-amber" : "text-ink-3"}`}>
                    {settings.debugMode ? "On" : "Off"}
                  </span>
                </button>
                <button
                  type="button"
                  onClick={() => {
                    onClose();
                    confirmLogout(logout);
                  }}
                  className="w-full rounded-lg px-3 py-2.5 text-left text-sm font-medium text-ink-2 hover:bg-red-50 hover:text-coral"
                >
                  Logout
                </button>
              </>
            )}
          </section>
        ))}
      </div>
    </div>
  );
}
