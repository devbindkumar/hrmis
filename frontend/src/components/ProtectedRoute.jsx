import { Navigate } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";

const ADMIN_ROLES = ["super_admin", "hr", "manager"];

export default function ProtectedRoute({ children, allow }) {
  const { user } = useAuth();

  if (user === null) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50" data-testid="auth-loading">
        <div className="flex flex-col items-center gap-3">
          <div className="h-8 w-8 rounded-full border-2 border-slate-900 border-t-transparent animate-spin" />
          <p className="text-sm text-slate-500">Loading workspace…</p>
        </div>
      </div>
    );
  }

  if (!user) return <Navigate to="/login" replace />;

  if (allow === "admin" && !ADMIN_ROLES.includes(user.role)) {
    return <Navigate to="/employee" replace />;
  }
  if (allow === "employee" && ADMIN_ROLES.includes(user.role)) {
    return <Navigate to="/admin" replace />;
  }

  return children;
}

export function RoleRedirect() {
  const { user } = useAuth();
  if (user === null) return null;
  if (!user) return <Navigate to="/login" replace />;
  return <Navigate to={ADMIN_ROLES.includes(user.role) ? "/admin" : "/employee"} replace />;
}
