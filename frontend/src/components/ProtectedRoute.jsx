import { Navigate } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";

const ADMIN_ROLES = ["super_admin", "hr", "manager"];

export default function ProtectedRoute({ children, allow, roles }) {
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

  // Fine-grained role guard: if `roles` provided, user must be in the list.
  if (Array.isArray(roles) && roles.length > 0 && !roles.includes(user.role)) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50 p-8" data-testid="role-forbidden">
        <div className="max-w-md w-full bg-white rounded-2xl border border-slate-200 shadow-sm p-8 text-center">
          <div className="mx-auto h-12 w-12 rounded-full bg-rose-50 grid place-items-center mb-4">
            <span className="text-2xl font-semibold text-rose-600">403</span>
          </div>
          <h1 className="font-display text-xl font-semibold text-slate-900 mb-2">Access denied</h1>
          <p className="text-sm text-slate-500">
            This page is restricted to <span className="font-medium text-slate-700">{roles.join(" and ")}</span> roles only.
          </p>
        </div>
      </div>
    );
  }

  return children;
}

export function RoleRedirect() {
  const { user } = useAuth();
  if (user === null) return null;
  if (!user) return <Navigate to="/login" replace />;
  return <Navigate to={ADMIN_ROLES.includes(user.role) ? "/admin" : "/employee"} replace />;
}
