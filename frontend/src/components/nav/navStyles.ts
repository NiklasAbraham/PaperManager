export const linkCls = (active: boolean) =>
  `px-3 py-2 rounded-lg text-sm font-medium transition-colors whitespace-nowrap ${
    active ? "bg-accent-lo text-accent" : "text-ink-2 hover:text-ink hover:bg-base"
  }`;

export function confirmLogout(logout: () => void) {
  if (confirm("Are you sure you want to logout?")) logout();
}
