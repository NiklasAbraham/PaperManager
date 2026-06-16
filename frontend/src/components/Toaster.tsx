import { useEffect, useState } from "react";
import type { ToastDetail } from "../lib/notify";

const KIND_STYLES: Record<string, string> = {
  error: "bg-red-600 text-white",
  success: "bg-green-600 text-white",
  info: "bg-gray-800 text-white",
};

export default function Toaster() {
  const [toasts, setToasts] = useState<ToastDetail[]>([]);

  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<ToastDetail>).detail;
      setToasts((prev) => [...prev, detail]);
      setTimeout(() => {
        setToasts((prev) => prev.filter((t) => t.id !== detail.id));
      }, 4000);
    };
    window.addEventListener("app:toast", handler);
    return () => window.removeEventListener("app:toast", handler);
  }, []);

  if (toasts.length === 0) return null;

  return (
    <div className="fixed bottom-4 right-4 z-[9999] flex flex-col gap-2 max-w-sm">
      {toasts.map((t) => (
        <div
          key={t.id}
          role="alert"
          className={`px-4 py-2 rounded-lg shadow-lg text-sm font-medium animate-[fadeIn_0.15s_ease-out] ${KIND_STYLES[t.kind] ?? KIND_STYLES.info}`}
          onClick={() => setToasts((prev) => prev.filter((x) => x.id !== t.id))}
        >
          {t.message}
        </div>
      ))}
    </div>
  );
}
