import { useEffect, useState } from "react";
import api from "@/lib/api";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import StatusPill from "@/components/StatusPill";
import { Input } from "@/components/ui/input";
import { Search, CalendarClock } from "lucide-react";

function fmt(t) {
  if (!t) return "—";
  return new Date(t).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

export default function AdminAttendance() {
  const [data, setData] = useState({ rows: [], date: "" });
  const [q, setQ] = useState("");
  const [day, setDay] = useState(new Date().toISOString().slice(0, 10));

  useEffect(() => {
    api.get("/attendance/monitor", { params: { day } }).then((r) => setData(r.data));
  }, [day]);

  const rows = data.rows.filter((r) => !q || r.name.toLowerCase().includes(q.toLowerCase()) || r.department?.toLowerCase().includes(q.toLowerCase()));

  const counts = data.rows.reduce((m, r) => { m[r.status] = (m[r.status] || 0) + 1; return m; }, {});

  return (
    <div className="p-6 space-y-5 animate-fade-up" data-testid="admin-attendance">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="font-display text-3xl font-semibold tracking-tight text-slate-900">Attendance monitor</h1>
          <p className="text-sm text-slate-500 mt-1">Live status across all teams</p>
        </div>
        <div className="flex items-center gap-2">
          <CalendarClock className="h-4 w-4 text-slate-400" strokeWidth={1.5} />
          <Input type="date" value={day} onChange={(e)=>setDay(e.target.value)} className="h-10 rounded-lg border-slate-200 w-40" data-testid="att-date" />
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <Quick label="Present" value={counts.present || 0} pill="present" />
        <Quick label="Remote" value={counts.remote || 0} pill="remote" />
        <Quick label="On leave" value={counts.on_leave || 0} pill="on_leave" />
        <Quick label="In meeting" value={counts.in_meeting || 0} pill="in_meeting" />
        <Quick label="Absent" value={counts.absent || 0} pill="absent" />
      </div>

      <div className="surface overflow-hidden">
        <div className="px-5 py-3 border-b border-slate-100 flex items-center gap-3">
          <Search className="h-4 w-4 text-slate-400" strokeWidth={1.5} />
          <input
            value={q}
            onChange={(e)=>setQ(e.target.value)}
            placeholder="Filter by name or department…"
            className="text-sm bg-transparent outline-none flex-1"
            data-testid="att-search"
          />
        </div>
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-slate-50 text-slate-500 text-xs uppercase tracking-wide">
              <th className="text-left font-semibold px-5 py-3">Employee</th>
              <th className="text-left font-semibold px-5 py-3">Department</th>
              <th className="text-left font-semibold px-5 py-3">Check in</th>
              <th className="text-left font-semibold px-5 py-3">Check out</th>
              <th className="text-left font-semibold px-5 py-3">Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr><td colSpan="5" className="px-5 py-10 text-center text-slate-400">Nothing to show.</td></tr>
            ) : rows.map((r) => (
              <tr key={r.user_id} className="border-t border-slate-100 hover:bg-slate-50/60">
                <td className="px-5 py-3">
                  <div className="flex items-center gap-3">
                    <Avatar className="h-9 w-9">
                      <AvatarImage src={r.avatar_url} alt={r.name} />
                      <AvatarFallback className="text-xs">{r.name.split(" ").map(p=>p[0]).slice(0,2).join("")}</AvatarFallback>
                    </Avatar>
                    <div>
                      <div className="font-medium text-slate-900">{r.name}</div>
                      <div className="text-xs text-slate-500">{r.designation}</div>
                    </div>
                  </div>
                </td>
                <td className="px-5 py-3 text-slate-700">{r.department}</td>
                <td className="px-5 py-3 text-slate-700">
                  {fmt(r.check_in)} {r.is_late && <span className="ml-2 text-[10px] uppercase font-semibold text-rose-600">Late</span>}
                </td>
                <td className="px-5 py-3 text-slate-700">{fmt(r.check_out)}</td>
                <td className="px-5 py-3"><StatusPill status={r.status} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Quick({ label, value, pill }) {
  return (
    <div className="surface p-4">
      <div className="text-xs uppercase tracking-widest text-slate-400 font-semibold">{label}</div>
      <div className="flex items-baseline justify-between mt-2">
        <span className="font-display text-2xl font-semibold text-slate-900">{value}</span>
        <StatusPill status={pill} label={label} />
      </div>
    </div>
  );
}
