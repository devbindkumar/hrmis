import { useEffect, useState } from "react";
import api from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Users, UserCheck, House, CalendarDays, BellRing, ArrowUpRight, Sparkles, Users2 } from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Cell } from "recharts";
import StatusPill from "@/components/StatusPill";
import { Link } from "react-router-dom";
import { Skeleton } from "@/components/ui/skeleton";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";

const STATUS_COLORS = {
  present: "#10b981",
  wfh: "#3b82f6",
  leave: "#f59e0b",
  absent: "#f43f5e",
};

function KpiCard({ label, value, icon: Icon, accent, hint, testid }) {
  return (
    <div className="surface p-5 card-hover" data-testid={testid}>
      <div className="flex items-start justify-between">
        <div>
          <div className="text-xs uppercase tracking-[0.05em] font-semibold text-slate-500">{label}</div>
          <div className="font-display text-3xl font-semibold text-slate-900 mt-2">{value}</div>
          {hint && <div className="text-xs text-slate-500 mt-1">{hint}</div>}
        </div>
        <div className={`h-9 w-9 rounded-lg ${accent} grid place-items-center`}>
          <Icon className="h-4 w-4" strokeWidth={1.5} />
        </div>
      </div>
    </div>
  );
}

export default function AdminOverview() {
  const [data, setData] = useState(null);
  const [team, setTeam] = useState([]);

  useEffect(() => {
    api.get("/dashboard/admin").then((r) => setData(r.data)).catch(() => setData({ kpi: {}, trend_7d: [], pending_leaves: [], pending_wfhs: [], department_counts: [] }));
    api.get("/employees/team/today").then((r) => setTeam(r.data.reports || [])).catch(() => setTeam([]));
  }, []);

  if (!data) {
    return (
      <div className="p-6 grid grid-cols-1 lg:grid-cols-12 gap-6">
        {[...Array(4)].map((_, i) => <Skeleton key={i} className="h-28 lg:col-span-3" />)}
      </div>
    );
  }

  const kpi = data.kpi || {};
  return (
    <div className="p-6 space-y-6 animate-fade-up" data-testid="admin-overview">
      <div className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <h1 className="font-display text-3xl font-semibold tracking-tight text-slate-900">Today at a glance</h1>
          <p className="text-sm text-slate-500 mt-1">Workforce, approvals and signal across the company.</p>
        </div>
        <div className="text-xs uppercase tracking-widest font-semibold text-slate-400">{new Date().toLocaleDateString(undefined, { weekday: 'long', month: 'short', day: 'numeric' })}</div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <KpiCard testid="kpi-total" label="Total people" value={kpi.total_employees ?? 0} icon={Users} accent="bg-slate-900 text-white" hint="Active employees" />
        <KpiCard testid="kpi-present" label="Present" value={kpi.present_today ?? 0} icon={UserCheck} accent="bg-emerald-50 text-emerald-700" hint={`Absent ${kpi.absent ?? 0}`} />
        <KpiCard testid="kpi-wfh" label="Working remote" value={kpi.wfh ?? 0} icon={House} accent="bg-blue-50 text-blue-700" hint="Approved WFH" />
        <KpiCard testid="kpi-leave" label="On leave" value={kpi.on_leave ?? 0} icon={CalendarDays} accent="bg-amber-50 text-amber-700" hint={`${kpi.pending_leave ?? 0} pending`} />
      </div>

      {team.length > 0 && (
        <div className="surface p-6 card-hover" data-testid="my-team-today">
          <div className="flex items-center justify-between flex-wrap gap-3">
            <div className="flex items-center gap-2">
              <Users2 className="h-4 w-4 text-slate-500" strokeWidth={1.5} />
              <h3 className="font-display text-lg font-medium text-slate-900">My team today</h3>
              <span className="text-xs text-slate-500 ml-1">· {team.length} direct {team.length === 1 ? "report" : "reports"}</span>
            </div>
            <Link to="/admin/leave" className="text-xs font-medium text-blue-600 hover:underline">Review approvals →</Link>
          </div>
          <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {team.map((m) => (
              <div key={m.employee_id} className="rounded-xl border border-slate-100 hover:border-slate-200 p-3 flex items-center gap-3" data-testid={`team-member-${m.employee_id}`}>
                <Avatar className="h-10 w-10">
                  <AvatarImage src={m.avatar_url} alt={m.name} />
                  <AvatarFallback className="text-xs bg-slate-100">{m.name.split(" ").map(p=>p[0]).slice(0,2).join("")}</AvatarFallback>
                </Avatar>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-slate-900 truncate">{m.name}</span>
                  </div>
                  <div className="text-xs text-slate-500 truncate">{m.detail || m.designation}</div>
                </div>
                <StatusPill status={m.status} />
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        <div className="surface p-6 lg:col-span-8" data-testid="attendance-chart">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="font-display text-lg font-medium text-slate-900">Attendance · last 7 days</h3>
              <p className="text-xs text-slate-500 mt-0.5">People in-office, remote, on leave, or absent</p>
            </div>
          </div>
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data.trend_7d || []} margin={{ top: 6, right: 6, bottom: 0, left: -16 }}>
                <CartesianGrid stroke="#f1f5f9" vertical={false} />
                <XAxis dataKey="date" tickFormatter={(d) => new Date(d).toLocaleDateString(undefined, { weekday: 'short' })} stroke="#94a3b8" fontSize={12} />
                <YAxis stroke="#94a3b8" fontSize={12} />
                <Tooltip contentStyle={{ borderRadius: 8, border: '1px solid #e5e7eb' }} />
                <Bar dataKey="present" stackId="a" fill={STATUS_COLORS.present} radius={[0,0,0,0]} />
                <Bar dataKey="wfh" stackId="a" fill={STATUS_COLORS.wfh} />
                <Bar dataKey="leave" stackId="a" fill={STATUS_COLORS.leave} />
                <Bar dataKey="absent" stackId="a" fill={STATUS_COLORS.absent} radius={[4,4,0,0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="flex items-center gap-4 mt-3 text-xs text-slate-500">
            <Legend color={STATUS_COLORS.present} label="Present" />
            <Legend color={STATUS_COLORS.wfh} label="WFH" />
            <Legend color={STATUS_COLORS.leave} label="On leave" />
            <Legend color={STATUS_COLORS.absent} label="Absent" />
          </div>
        </div>

        <div className="surface p-6 lg:col-span-4 flex flex-col" data-testid="pending-approvals">
          <h3 className="font-display text-lg font-medium text-slate-900">Pending approvals</h3>
          <p className="text-xs text-slate-500 mt-0.5">Leave & WFH waiting on you</p>
          <div className="mt-4 space-y-3 flex-1">
            {(data.pending_leaves || []).slice(0, 4).map((r) => (
              <ApprovalItem key={r.id} type="Leave" name={r.user_name} sub={`${r.leave_type} · ${r.days}d`} date={r.start_date} link="/admin/leave" />
            ))}
            {(data.pending_wfhs || []).slice(0, 3).map((r) => (
              <ApprovalItem key={r.id} type="WFH" name={r.user_name} sub="Single day" date={r.date} link="/admin/wfh" />
            ))}
            {(data.pending_leaves || []).length === 0 && (data.pending_wfhs || []).length === 0 && (
              <div className="text-sm text-slate-400 text-center py-8">No pending requests. </div>
            )}
          </div>
          <div className="flex gap-2 pt-3 border-t border-slate-100 mt-3">
            <Link to="/admin/leave" className="text-xs font-medium text-blue-600 hover:underline">View all leave →</Link>
            <span className="text-slate-200">·</span>
            <Link to="/admin/wfh" className="text-xs font-medium text-blue-600 hover:underline">View all WFH →</Link>
          </div>
        </div>

        <div className="surface p-6 lg:col-span-5" data-testid="dept-breakdown">
          <h3 className="font-display text-lg font-medium text-slate-900">Headcount by department</h3>
          <p className="text-xs text-slate-500 mt-0.5">Active employees distribution</p>
          <div className="mt-4 space-y-3">
            {(data.department_counts || []).map((d) => {
              const max = Math.max(...(data.department_counts || []).map((x) => x.count), 1);
              const pct = (d.count / max) * 100;
              return (
                <div key={d.name}>
                  <div className="flex items-baseline justify-between text-sm">
                    <span className="text-slate-800 font-medium">{d.name}</span>
                    <span className="text-slate-500">{d.count}</span>
                  </div>
                  <div className="h-2 rounded-full bg-slate-100 mt-1 overflow-hidden">
                    <div className="h-full rounded-full bg-slate-900" style={{ width: `${pct}%` }} />
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        <div className="surface p-6 lg:col-span-7" data-testid="announcement-card">
          <div className="flex items-center gap-2">
            <BellRing className="h-4 w-4 text-amber-600" strokeWidth={1.5} />
            <h3 className="font-display text-lg font-medium text-slate-900">Latest announcement</h3>
          </div>
          {data.latest_announcement ? (
            <div className="mt-4">
              <div className="text-base font-medium text-slate-900">{data.latest_announcement.title}</div>
              <p className="text-sm text-slate-600 mt-2 leading-relaxed">{data.latest_announcement.body}</p>
              <div className="text-xs text-slate-400 mt-3">— {data.latest_announcement.author_name}</div>
              <Link to="/admin/announcements" className="inline-flex items-center gap-1 mt-4 text-xs font-medium text-blue-600 hover:underline">
                Post a new one <ArrowUpRight className="h-3 w-3" />
              </Link>
            </div>
          ) : (
            <div className="text-sm text-slate-400 mt-6 text-center py-6">No announcements yet.<br/>
              <Link to="/admin/announcements" className="text-blue-600 font-medium">Create the first one →</Link>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Legend({ color, label }) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="h-2 w-2 rounded-sm" style={{ background: color }} />
      <span>{label}</span>
    </div>
  );
}

function ApprovalItem({ type, name, sub, date, link }) {
  return (
    <Link to={link} className="flex items-center justify-between rounded-lg border border-slate-100 hover:border-slate-200 px-3 py-2.5 hover:bg-slate-50 transition-colors group">
      <div>
        <div className="text-sm font-medium text-slate-900">{name}</div>
        <div className="text-xs text-slate-500">{type} · {sub}</div>
      </div>
      <div className="text-xs text-slate-500 group-hover:text-slate-900">{date}</div>
    </Link>
  );
}
