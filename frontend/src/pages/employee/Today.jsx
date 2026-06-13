import { useEffect, useState } from "react";
import api, { formatApiError } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { Button } from "@/components/ui/button";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Skeleton } from "@/components/ui/skeleton";
import { LogIn, LogOut, Coffee, Video, House, Activity, CalendarDays, BellRing } from "lucide-react";
import { toast } from "sonner";
import { Link } from "react-router-dom";
import StatusPill from "@/components/StatusPill";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

const STATUS_OPTIONS = [
  { v: "active", label: "Active", icon: Activity },
  { v: "in_meeting", label: "In meeting", icon: Video },
  { v: "on_break", label: "On break", icon: Coffee },
  { v: "wfh", label: "Working from home", icon: House },
];

function fmtDur(seconds) {
  if (!seconds || seconds < 0) return "0h 0m";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `${h}h ${m}m`;
}

function liveDuration(startIso) {
  if (!startIso) return 0;
  return Math.floor((Date.now() - new Date(startIso).getTime()) / 1000);
}

export default function EmployeeToday() {
  const { user } = useAuth();
  const [dash, setDash] = useState(null);
  const [today, setToday] = useState(null);
  const [tick, setTick] = useState(0);

  const load = async () => {
    const [a, b] = await Promise.all([
      api.get("/dashboard/employee"),
      api.get("/attendance/today"),
    ]);
    setDash(a.data);
    setToday(b.data);
  };
  useEffect(() => { load(); }, []);
  useEffect(() => { const t = setInterval(() => setTick((x)=>x+1), 30000); return () => clearInterval(t); }, []);

  const checkIn = async () => {
    try { await api.post("/attendance/check-in"); toast.success("Checked in. Have a great day!"); load(); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };
  const checkOut = async () => {
    try { await api.post("/attendance/check-out"); toast.success("Checked out. See you tomorrow!"); load(); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };
  const setStatus = async (s) => {
    try { await api.post("/attendance/status", { status: s }); toast.success(`Status updated`); load(); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  if (!dash || !today) return <div className="p-6 grid grid-cols-1 md:grid-cols-8 gap-6"><Skeleton className="h-48 md:col-span-5" /><Skeleton className="h-48 md:col-span-3" /></div>;

  const checked = !!today.check_in && !today.check_out;
  const done = !!today.check_out;
  const duration = checked ? liveDuration(today.check_in) : (today.duration_seconds || 0);

  return (
    <div className="space-y-8 animate-fade-up" data-testid="employee-today">
      {/* greeting */}
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="font-display text-4xl sm:text-5xl font-semibold tracking-tight text-slate-900">Hi, {user?.name?.split(" ")[0]}.</h1>
          <p className="text-base text-slate-500 mt-2">Here's your day, all in one place.</p>
        </div>
        <div className="text-xs uppercase tracking-widest font-semibold text-slate-400">{new Date().toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' })}</div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-8 gap-6">
        {/* hero check-in */}
        <div className="surface md:col-span-5 p-8 relative overflow-hidden" data-testid="checkin-hero">
          <div className="absolute inset-0 grid-bg opacity-60" />
          <div className="relative">
            <div className="flex items-center gap-2 text-xs uppercase tracking-widest font-semibold text-slate-400">
              <Activity className="h-3.5 w-3.5" strokeWidth={1.5} />
              {done ? "Day complete" : checked ? "Currently working" : "Not checked in"}
            </div>
            <div className="mt-6 flex items-end gap-6 flex-wrap">
              <div>
                <div className="font-display text-6xl font-semibold tabular-nums tracking-tight text-slate-900">
                  {fmtDur(duration)}
                </div>
                <div className="text-sm text-slate-500 mt-2">
                  {today.check_in && <>In at <b>{new Date(today.check_in).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</b>{today.is_late && <span className="ml-2 text-rose-600 text-xs font-medium uppercase tracking-wide">Late</span>}</>}
                  {today.check_out && <> · Out at <b>{new Date(today.check_out).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</b></>}
                  {!today.check_in && "Tap below to start your day."}
                </div>
              </div>
              {checked && (
                <StatusPill status={today.current_status || 'active'} />
              )}
            </div>

            <div className="mt-8 flex flex-wrap items-center gap-3">
              {!checked && !done ? (
                <Button onClick={checkIn} size="lg" className="h-14 rounded-xl px-6 bg-slate-900 hover:bg-slate-800 text-white text-base font-medium" data-testid="check-in-button">
                  <LogIn className="h-5 w-5 mr-2" strokeWidth={1.5} /> Check in
                </Button>
              ) : checked ? (
                <>
                  <Button onClick={checkOut} size="lg" className="h-14 rounded-xl px-6 bg-rose-600 hover:bg-rose-700 text-white text-base font-medium" data-testid="check-out-button">
                    <LogOut className="h-5 w-5 mr-2" strokeWidth={1.5} /> Check out
                  </Button>
                  <Select value={today.current_status || 'active'} onValueChange={setStatus}>
                    <SelectTrigger className="h-14 w-56 rounded-xl border-slate-200" data-testid="status-select">
                      <SelectValue placeholder="Set status" />
                    </SelectTrigger>
                    <SelectContent>
                      {STATUS_OPTIONS.map((s) => (
                        <SelectItem key={s.v} value={s.v}>
                          <div className="flex items-center gap-2"><s.icon className="h-3.5 w-3.5" strokeWidth={1.5} /> {s.label}</div>
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </>
              ) : (
                <div className="px-4 py-3 rounded-xl bg-slate-100 text-slate-600 text-sm">You wrapped up at {new Date(today.check_out).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}. </div>
              )}
            </div>
          </div>
        </div>

        {/* leave balance + quick */}
        <div className="md:col-span-3 space-y-6" data-testid="employee-side">
          <div className="surface p-6">
            <div className="flex items-center justify-between">
              <h3 className="font-display text-lg font-medium text-slate-900">Leave balance</h3>
              <Link to="/employee/leave" className="text-xs text-blue-600 font-medium hover:underline">Manage</Link>
            </div>
            <div className="mt-4 space-y-3">
              {dash.balances.map((b) => {
                const remaining = b.total - b.used;
                const pct = b.total ? (remaining / b.total) * 100 : 0;
                return (
                  <div key={b.id}>
                    <div className="flex justify-between text-sm">
                      <span className="text-slate-800 font-medium">{b.leave_type}</span>
                      <span className="text-slate-500"><b className="text-slate-900">{remaining}</b> / {b.total}</span>
                    </div>
                    <div className="h-1.5 rounded-full bg-slate-100 mt-1.5 overflow-hidden">
                      <div className="h-full rounded-full bg-slate-900" style={{ width: `${pct}%` }} />
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="surface p-6">
            <h3 className="font-display text-lg font-medium text-slate-900">Quick actions</h3>
            <div className="mt-4 grid grid-cols-2 gap-3">
              <QuickAction icon={CalendarDays} label="Apply leave" to="/employee/leave" testid="apply-leave-link" />
              <QuickAction icon={House} label="Apply WFH" to="/employee/wfh" testid="apply-wfh-link" />
              <QuickAction icon={Video} label="Schedule" to="/employee/meetings" testid="schedule-meeting-link" />
              <QuickAction icon={BellRing} label="Notifications" to="/employee" testid="notifications-link" />
            </div>
          </div>
        </div>

        {/* upcoming meetings */}
        <div className="surface md:col-span-5 p-6" data-testid="upcoming-meetings">
          <div className="flex items-center justify-between">
            <h3 className="font-display text-lg font-medium text-slate-900">Upcoming meetings</h3>
            <Link to="/employee/meetings" className="text-xs text-blue-600 font-medium hover:underline">All meetings</Link>
          </div>
          <div className="mt-4 divide-y divide-slate-100">
            {dash.upcoming_meetings.length === 0 ? (
              <div className="text-sm text-slate-400 text-center py-8">Nothing on your calendar.</div>
            ) : dash.upcoming_meetings.map((m) => {
              const s = new Date(m.starts_at);
              return (
                <div key={m.id} className="py-3 flex items-center gap-4">
                  <div className="text-center px-3 py-1.5 rounded-lg bg-slate-100">
                    <div className="text-[10px] uppercase tracking-widest font-semibold text-slate-500">{s.toLocaleDateString(undefined, { month: 'short' })}</div>
                    <div className="font-display text-lg font-semibold text-slate-900">{s.getDate()}</div>
                  </div>
                  <div className="flex-1">
                    <div className="text-sm font-medium text-slate-900">{m.title}</div>
                    <div className="text-xs text-slate-500">
                      {s.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} · {m.location}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* announcements */}
        <div className="surface md:col-span-3 p-6" data-testid="announcements-card">
          <div className="flex items-center gap-2">
            <BellRing className="h-4 w-4 text-amber-600" strokeWidth={1.5} />
            <h3 className="font-display text-lg font-medium text-slate-900">From HR</h3>
          </div>
          <div className="mt-4 space-y-4">
            {dash.announcements.length === 0 ? <div className="text-sm text-slate-400">No announcements.</div> :
              dash.announcements.map((a) => (
                <div key={a.id}>
                  <div className="text-sm font-medium text-slate-900">{a.title}</div>
                  <div className="text-xs text-slate-500 mt-1 line-clamp-3">{a.body}</div>
                  <div className="text-[10px] text-slate-400 mt-1">{new Date(a.created_at).toLocaleDateString()} · {a.author_name}</div>
                </div>
              ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function QuickAction({ icon: Icon, label, to, testid }) {
  return (
    <Link to={to} className="rounded-xl border border-slate-200 hover:border-slate-300 hover:bg-slate-50 px-4 py-3 text-left transition" data-testid={testid}>
      <Icon className="h-4 w-4 text-slate-700" strokeWidth={1.5} />
      <div className="text-sm font-medium text-slate-900 mt-2">{label}</div>
    </Link>
  );
}
