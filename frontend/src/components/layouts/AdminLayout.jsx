import { NavLink, Outlet, useNavigate, Link } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";
import {
  LayoutDashboard, Users, Clock, CalendarDays, Home, Video,
  Megaphone, BarChart3, Settings, LogOut, Building2, Bell, Briefcase, Network, Globe2, Banknote,
  MessageCircle,
} from "lucide-react";
import { useEffect, useState } from "react";
import api from "@/lib/api";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem,
  DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";

const NAV = [
  { to: "/admin", label: "Overview", icon: LayoutDashboard, end: true },
  { to: "/admin/employees", label: "Employees", icon: Users },
  { to: "/admin/org", label: "Org chart", icon: Network },
  { to: "/admin/attendance", label: "Attendance", icon: Clock },
  { to: "/admin/leave", label: "Leave", icon: CalendarDays },
  { to: "/admin/wfh", label: "Work from home", icon: Home },
  { to: "/admin/meetings", label: "Meetings", icon: Video },
  { to: "/admin/announcements", label: "Announcements", icon: Megaphone },
  { to: "/admin/payroll", label: "Payroll", icon: Banknote },
  { to: "/admin/jobs", label: "Jobs", icon: Briefcase },
  { to: "/admin/reports", label: "Reports", icon: BarChart3 },
  { to: "/admin/companies", label: "Companies", icon: Globe2 },
  { to: "/admin/whatsapp", label: "WhatsApp", icon: MessageCircle },
  { to: "/admin/settings", label: "Settings", icon: Settings },
];

export default function AdminLayout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [notifs, setNotifs] = useState([]);
  const accent = user?.company?.accent_color || "#0f172a";

  useEffect(() => {
    const load = async () => {
      try {
        const { data } = await api.get("/notifications");
        setNotifs(data);
      } catch {}
    };
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, []);

  const unread = notifs.filter((n) => !n.read).length;

  const markAll = async () => {
    await api.post("/notifications/read-all");
    setNotifs(notifs.map((n) => ({ ...n, read: true })));
  };

  return (
    <div
      className="min-h-screen flex bg-slate-50"
      style={{ "--company-accent": accent }}
    >
      {/* Sidebar */}
      <aside className="w-64 shrink-0 bg-slate-950 text-slate-200 flex flex-col" data-testid="admin-sidebar">
        <div className="px-5 py-5 border-b border-slate-800/80 flex items-center gap-3">
          {user?.company?.has_logo ? (
            <div
              className="h-12 w-12 rounded-lg grid place-items-center shrink-0 bg-white/95 p-1.5"
              data-testid="sidebar-logo-wrap"
            >
              <img
                src={`${process.env.REACT_APP_BACKEND_URL}/api/companies/${user.company.id}/logo`}
                alt={user.company.name}
                className="max-h-full max-w-full object-contain"
                data-testid="sidebar-company-logo"
              />
            </div>
          ) : (
            <div
              className="h-10 w-10 rounded-lg grid place-items-center shrink-0"
              style={{ background: user?.company?.accent_color || "rgba(255,255,255,0.1)" }}
              data-testid="sidebar-logo-wrap"
            >
              <Building2 className="h-4 w-4 text-white" strokeWidth={1.5} />
            </div>
          )}
          <div className="min-w-0">
            <div className="font-display text-base font-semibold text-white truncate">{user?.company?.name || "Workspace"}</div>
            <div className="text-[10px] uppercase tracking-widest text-slate-400">HRMIS · {user?.role === "super_admin" ? "Admin" : user?.role}</div>
          </div>
        </div>

        <nav className="flex-1 px-3 py-4 space-y-1">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.end}
              className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}
              data-testid={`nav-${n.label.toLowerCase().replace(/\s+/g, '-')}`}
            >
              <n.icon className="h-4 w-4" strokeWidth={1.5} />
              {n.label}
            </NavLink>
          ))}
        </nav>

        <div className="p-3 border-t border-slate-800/80">
          <button
            onClick={() => { logout(); navigate("/login"); }}
            className="nav-link w-full text-rose-200 hover:text-rose-100"
            data-testid="logout-button"
          >
            <LogOut className="h-4 w-4" strokeWidth={1.5} />
            Sign out
          </button>
        </div>
      </aside>

      {/* Main */}
      <div className="flex-1 flex flex-col min-w-0">
        <header className="h-16 px-6 border-b border-slate-200 bg-white flex items-center justify-between">
          <div>
            <div className="text-xs uppercase tracking-widest text-slate-400 font-semibold">Workspace</div>
            <div className="font-display text-lg font-medium text-slate-900">Admin · {user?.name}</div>
          </div>
          <div className="flex items-center gap-3">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button className="relative h-9 w-9 rounded-lg border border-slate-200 hover:bg-slate-50 grid place-items-center" data-testid="notif-bell">
                  <Bell className="h-4 w-4 text-slate-700" strokeWidth={1.5} />
                  {unread > 0 && (
                    <span className="absolute -top-1 -right-1 h-4 min-w-4 px-1 rounded-full bg-rose-500 text-white text-[10px] font-medium grid place-items-center">{unread}</span>
                  )}
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-80">
                <DropdownMenuLabel className="flex items-center justify-between">
                  <span>Notifications</span>
                  {unread > 0 && <button className="text-xs text-blue-600 font-medium" onClick={markAll}>Mark all read</button>}
                </DropdownMenuLabel>
                <DropdownMenuSeparator />
                {notifs.length === 0 ? (
                  <div className="p-4 text-sm text-slate-500 text-center">All caught up</div>
                ) : (
                  notifs.slice(0, 8).map((n) => (
                    <DropdownMenuItem key={n.id} className="flex-col items-start gap-0.5">
                      <div className="text-sm font-medium text-slate-900">{n.title}</div>
                      <div className="text-xs text-slate-500 line-clamp-2">{n.body}</div>
                    </DropdownMenuItem>
                  ))
                )}
              </DropdownMenuContent>
            </DropdownMenu>

            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button className="flex items-center gap-2 px-2 py-1.5 rounded-lg border border-slate-200 hover:bg-slate-50" data-testid="user-menu">
                  <Avatar className="h-7 w-7">
                    <AvatarFallback className="text-xs bg-slate-900 text-white">{user?.name?.split(" ").map((p) => p[0]).slice(0, 2).join("")}</AvatarFallback>
                  </Avatar>
                  <div className="text-left">
                    <div className="text-sm font-medium text-slate-900 leading-tight">{user?.name}</div>
                    <div className="text-[10px] uppercase tracking-widest text-slate-400">{user?.role}</div>
                  </div>
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuLabel>{user?.email}</DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem asChild><Link to="/admin/settings">Settings</Link></DropdownMenuItem>
                <DropdownMenuItem onClick={() => { logout(); navigate("/login"); }} className="text-rose-600">Sign out</DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </header>

        <main className="flex-1 overflow-y-auto" data-testid="admin-main">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
