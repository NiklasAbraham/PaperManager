// Where to land after logging in: the page that was open when the session ended.
// Kept in sessionStorage as well as router state so it survives a reload of /login.
const KEY = "pm_return_to";

export function rememberReturnTo(path: string) {
  if (isSafe(path)) sessionStorage.setItem(KEY, path);
}

export function takeReturnTo(fromState?: string): string {
  const stored = sessionStorage.getItem(KEY);
  sessionStorage.removeItem(KEY);
  const target = fromState ?? stored ?? "/";
  return isSafe(target) ? target : "/";
}

// Same-origin app paths only; never /login itself or a protocol-relative URL.
function isSafe(path: string): boolean {
  return path.startsWith("/") && !path.startsWith("//") && !path.startsWith("/login");
}
