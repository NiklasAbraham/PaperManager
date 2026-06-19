import { createContext, useContext, useState, useEffect, type ReactNode } from "react";

const STORAGE_KEY = "pm_current_user";

interface UserContextValue {
  currentUser: string | null;
  setCurrentUser: (name: string) => void;
  clearUser: () => void;
}

const UserContext = createContext<UserContextValue>({
  currentUser: null,
  setCurrentUser: () => {},
  clearUser: () => {},
});

export function UserProvider({ children }: { children: ReactNode }) {
  const [currentUser, setCurrentUserState] = useState<string | null>(
    () => localStorage.getItem(STORAGE_KEY)
  );

  const setCurrentUser = (name: string) => {
    localStorage.setItem(STORAGE_KEY, name);
    setCurrentUserState(name);
    // Register with backend (fire-and-forget)
    fetch(`${import.meta.env.VITE_API_URL ?? "http://localhost:8000"}/users/identify`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ name }),
    }).catch(() => {});
  };

  const clearUser = () => {
    localStorage.removeItem(STORAGE_KEY);
    setCurrentUserState(null);
  };

  // Register existing user on mount
  useEffect(() => {
    if (currentUser) {
      fetch(`${import.meta.env.VITE_API_URL ?? "http://localhost:8000"}/users/identify`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ name: currentUser }),
      }).catch(() => {});
    }
  }, []);

  return (
    <UserContext.Provider value={{ currentUser, setCurrentUser, clearUser }}>
      {children}
    </UserContext.Provider>
  );
}

export function useUser() {
  return useContext(UserContext);
}
