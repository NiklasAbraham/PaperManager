import { useState } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { useAppSettings } from "../../contexts/SettingsContext";
import { useAuth } from "../../contexts/AuthContext";
import { itemsFor, isGroupActive, isItemActive } from "./navConfig";
import { DropdownMenu, MenuLink } from "./NavMenu";
import { linkCls, confirmLogout } from "./navStyles";
import MobileDrawer from "./MobileDrawer";

function PrimaryLink({ item }: { item: ReturnType<typeof itemsFor>[number] }) {
  const { pathname } = useLocation();
  return (
    <NavLink
      to={item.to}
      end={item.end}
      aria-current={isItemActive(item, pathname) ? "page" : undefined}
      className={linkCls(isItemActive(item, pathname))}
    >
      {item.label}
    </NavLink>
  );
}

function DebugBadge() {
  const { settings } = useAppSettings();
  if (!settings.debugMode) return null;
  return (
    <span
      title="Debug mode is on (turn it off in the account menu)"
      className="px-2 py-0.5 rounded text-[10px] font-semibold tracking-wide bg-amber-500 text-white"
    >
      DEBUG
    </span>
  );
}

function AccountMenu() {
  const { settings, update } = useAppSettings();
  const { logout, username, isAdmin } = useAuth();
  const { pathname } = useLocation();
  return (
    <DropdownMenu
      align="right"
      active={isGroupActive("account", pathname, isAdmin)}
      label={<span className="max-w-[10rem] truncate">{username ?? "Account"}</span>}
    >
      {(close) => (
        <>
          {itemsFor("account", isAdmin).map((item) => (
            <MenuLink key={item.to} item={item} onNavigate={close} />
          ))}
          <div className="my-1.5 border-t border-line-s" />
          <button
            type="button"
            role="switch"
            aria-checked={settings.debugMode}
            onClick={() => update({ debugMode: !settings.debugMode })}
            className="w-full flex items-center justify-between gap-3 rounded-lg px-3 py-2 text-left hover:bg-base"
          >
            <span>
              <span className="block text-sm font-medium text-ink">Debug mode</span>
              <span className="block text-xs text-ink-3 leading-snug">
                {settings.debugMode ? "On: new uploads are marked as debug papers" : "Off"}
              </span>
            </span>
            <span
              aria-hidden="true"
              className={`shrink-0 inline-flex h-5 w-9 items-center rounded-full px-0.5 transition-colors ${
                settings.debugMode ? "bg-amber-500 justify-end" : "bg-line justify-start"
              }`}
            >
              <span className="h-4 w-4 rounded-full bg-raised shadow" />
            </span>
          </button>
          <button
            type="button"
            onClick={() => {
              close();
              confirmLogout(logout);
            }}
            className="w-full rounded-lg px-3 py-2 text-left text-sm font-medium text-ink-2 hover:bg-red-50 hover:text-coral"
          >
            Logout
          </button>
        </>
      )}
    </DropdownMenu>
  );
}

export default function NavBar() {
  const { isAdmin } = useAuth();
  const { pathname } = useLocation();
  // Tied to the route it was opened on, so any navigation closes it.
  const [drawerAt, setDrawerAt] = useState<string | null>(null);
  const drawerOpen = drawerAt === pathname;
  const setDrawerOpen = (o: boolean) => setDrawerAt(o ? pathname : null);

  return (
    <nav aria-label="Main" className="border-b border-line bg-raised px-3 md:px-6 py-2 flex items-center gap-1">
      <Link to="/" className="mr-3 shrink-0" aria-label="PaperManager home">
        <img src="/SecondBrainLogo.png" alt="PaperManager" className="h-8 object-contain" />
      </Link>

      {/* Desktop */}
      <div className="hidden md:flex items-center gap-1 flex-1 min-w-0">
        {itemsFor("primary", isAdmin).map((item) => (
          <PrimaryLink key={item.to} item={item} />
        ))}
        <DropdownMenu label="Explore" active={isGroupActive("explore", pathname, isAdmin)}>
          {(close) => itemsFor("explore", isAdmin).map((item) => <MenuLink key={item.to} item={item} onNavigate={close} />)}
        </DropdownMenu>
        <DropdownMenu label="Tools" active={isGroupActive("tools", pathname, isAdmin)}>
          {(close) => itemsFor("tools", isAdmin).map((item) => <MenuLink key={item.to} item={item} onNavigate={close} />)}
        </DropdownMenu>
        <div className="ml-auto flex items-center gap-2">
          <DebugBadge />
          <AccountMenu />
        </div>
      </div>

      {/* Mobile */}
      <div className="md:hidden ml-auto flex items-center gap-2">
        <DebugBadge />
        <button
          type="button"
          aria-label="Open menu"
          aria-haspopup="dialog"
          aria-expanded={drawerOpen}
          onClick={() => setDrawerOpen(true)}
          className="p-2 rounded-lg border border-line text-ink-2 hover:text-accent hover:border-accent-border"
        >
          <svg viewBox="0 0 20 20" fill="currentColor" aria-hidden="true" className="w-5 h-5">
            <path fillRule="evenodd" d="M2 4.75A.75.75 0 0 1 2.75 4h14.5a.75.75 0 0 1 0 1.5H2.75A.75.75 0 0 1 2 4.75Zm0 5.25a.75.75 0 0 1 .75-.75h14.5a.75.75 0 0 1 0 1.5H2.75A.75.75 0 0 1 2 10Zm0 5.25a.75.75 0 0 1 .75-.75h14.5a.75.75 0 0 1 0 1.5H2.75a.75.75 0 0 1-.75-.75Z" clipRule="evenodd" />
          </svg>
        </button>
      </div>

      {drawerOpen && <MobileDrawer onClose={() => setDrawerOpen(false)} />}
    </nav>
  );
}
