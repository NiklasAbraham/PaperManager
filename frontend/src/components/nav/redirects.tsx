import { Navigate, useSearchParams } from "react-router-dom";

/** /cypher became the Query view of the Graph page; keeps `?q=` and any other parameter. */
export function CypherRedirect() {
  const [params] = useSearchParams();
  const out = new URLSearchParams({ view: "query" });
  params.forEach((v, k) => {
    if (k !== "view") out.append(k, v);
  });
  return <Navigate to={`/graph?${out.toString()}`} replace />;
}

/** /chat is the short URL of the knowledge chat. */
export function ChatRedirect() {
  return <Navigate to="/knowledge" replace />;
}
