import { Navigate } from "react-router-dom";

/** Discover was merged into "Find papers"; keep the old URL working. */
export default function Discover() {
  return <Navigate to="/literature?tab=search" replace />;
}
