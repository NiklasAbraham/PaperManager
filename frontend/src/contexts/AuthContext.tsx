import { createContext, useContext, useState, useEffect, type ReactNode } from "react";

// Username is a non-sensitive display value; the session token itself lives only
// in an httpOnly cookie set by the backend and is never stored in JS/localStorage.
const USERNAME_KEY = "pm_username";

interface AuthContextValue {
  username: string | null;
  isAdmin: boolean;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue>({
  username: null,
  isAdmin: false,
  isAuthenticated: false,
  isLoading: true,
  login: async () => {},
  logout: () => {},
});

const BASE_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [username, setUsername] = useState<string | null>(null);
  const [isAdmin, setIsAdmin] = useState(false);
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [isLoading, setIsLoading] = useState(true);

  const clearSession = () => {
    setUsername(null);
    setIsAdmin(false);
    setIsAuthenticated(false);
    localStorage.removeItem(USERNAME_KEY);
    localStorage.removeItem("pm_current_user");
  };

  // Handle session expiry from API client without a hard page reload
  useEffect(() => {
    const handler = () => clearSession();
    window.addEventListener("auth:expired", handler);
    return () => window.removeEventListener("auth:expired", handler);
  }, []);

  // Validate the existing session cookie on mount.
  useEffect(() => {
    fetch(`${BASE_URL}/auth/me`, { credentials: "include" })
      .then((res) => {
        if (!res.ok) throw new Error("Not authenticated");
        return res.json();
      })
      .then((data) => {
        setUsername(data.username);
        setIsAdmin(data.is_admin || false);
        setIsAuthenticated(true);
        localStorage.setItem(USERNAME_KEY, data.username);
        localStorage.setItem("pm_current_user", data.username);
      })
      .catch(() => clearSession())
      .finally(() => setIsLoading(false));
  }, []);

  const login = async (username: string, password: string) => {
    const response = await fetch(`${BASE_URL}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ username, password }),
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: "Login failed" }));
      throw new Error(error.detail || "Login failed");
    }

    // The backend sets the session as an httpOnly cookie; we only keep the
    // username (for display) and admin flag in memory/localStorage.
    const data = await response.json();
    const { username: returnedUsername, is_admin } = data;

    localStorage.setItem(USERNAME_KEY, returnedUsername);
    localStorage.setItem("pm_current_user", returnedUsername);
    setUsername(returnedUsername);
    setIsAdmin(is_admin || false);
    setIsAuthenticated(true);
  };

  const logout = () => {
    // Best-effort cookie clear on the server; clear local state regardless.
    fetch(`${BASE_URL}/auth/logout`, { method: "POST", credentials: "include" }).catch(() => {});
    clearSession();
  };

  return (
    <AuthContext.Provider
      value={{
        username,
        isAdmin,
        isAuthenticated,
        isLoading,
        login,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
