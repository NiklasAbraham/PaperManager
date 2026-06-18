export type ToastKind = "error" | "success" | "info";

export type ToastDetail = {
  id: string;
  message: string;
  kind: ToastKind;
};

export function notify(message: string, kind: ToastKind = "error") {
  const detail: ToastDetail = {
    id: typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random()}`,
    message,
    kind,
  };
  window.dispatchEvent(new CustomEvent<ToastDetail>("app:toast", { detail }));
}
