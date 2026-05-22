import { NavLink, Outlet, useNavigate, Link } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";
import { Home, CalendarDays, House as HouseIcon, Video, MessagesSquare, User, LogOut, Briefcase, Bell } from "lucide-react";
import { useEffect, useState } from "react";
import api from "@/lib/api";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem,
  DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

const NAV = [
  { to: "/employee", label: "Today", icon: Home, end: true },
  { to: "/employee/leave", label: "Leave", icon: CalendarDays },
  { to: "/employee/wfh", label: "WFH", icon: HouseIcon },
  { to: "/employee/meetings", label: "Meetings", icon: Video },
  { to: "/employee/chat", label: "Chat", icon: MessagesSquare },
  { to: "/employee/profile", label: "Profile", icon: User },
];

export default function EmployeeLayout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [notifs, setNotifs] = useState([]);

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
    <div className="min-h-screen bg-slate-50">
      <header className="bg-white border-b border-slate-200">
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
          <Link to="/employee" className="flex items-center gap-2">
            <div className="h-8 w-8 rounded-lg bg-slate-900 grid place-items-center">
              <Briefcase className="h-4 w-4 text-white" strokeWidth={1.5} />
            </div>
            <div className="min-w-0">
              <div className="font-display text-base font-semibold text-slate-900 leading-none truncate max-w-[180px]">{user?.company?.name || "My HR"}</div>
              <div className="text-[10px] uppercase tracking-widest text-slate-400">My workspace</div>
            </div>
          </Link>

          <nav className="hidden md:flex items-center gap-1">
            {NAV.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                end={n.end}
                className={({ isActive }) => `emp-nav-link ${isActive ? "active" : ""}`}
                data-testid={`emp-nav-${n.label.toLowerCase()}`}
              >
                <n.icon className="h-4 w-4" strokeWidth={1.5} />
                {n.label}
              </NavLink>
            ))}
          </nav>

          <div className="flex items-center gap-3">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button className="relative h-9 w-9 rounded-lg border border-slate-200 hover:bg-slate-50 grid place-items-center" data-testid="emp-notif-bell">
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
                <button className="flex items-center gap-2 px-2 py-1.5 rounded-lg border border-slate-200 hover:bg-slate-50" data-testid="emp-user-menu">
                  <Avatar className="h-7 w-7">
                    <AvatarFallback className="text-xs bg-slate-900 text-white">{user?.name?.split(" ").map((p) => p[0]).slice(0, 2).join("")}</AvatarFallback>
                  </Avatar>
                  <div className="text-left hidden sm:block">
                    <div className="text-sm font-medium text-slate-900 leading-tight">{user?.name}</div>
                    <div className="text-[10px] uppercase tracking-widest text-slate-400">{user?.role}</div>
                  </div>
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuLabel>{user?.email}</DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem asChild><Link to="/employee/profile">Profile</Link></DropdownMenuItem>
                <DropdownMenuItem onClick={() => { logout(); navigate("/login"); }} className="text-rose-600">
                  <LogOut className="h-3.5 w-3.5 mr-2" /> Sign out
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
        {/* Mobile nav */}
        <nav className="md:hidden flex items-center gap-1 px-4 pb-3 overflow-x-auto">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end} className={({ isActive }) => `emp-nav-link ${isActive ? "active" : ""}`}>
              <n.icon className="h-4 w-4" strokeWidth={1.5} /> {n.label}
            </NavLink>
          ))}
        </nav>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 py-8" data-testid="employee-main">
        <Outlet />
      </main>
    </div>
  );
}
