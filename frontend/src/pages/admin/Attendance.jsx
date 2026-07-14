import { useEffect, useState } from "react";
import api, { formatApiError } from "@/lib/api";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import StatusPill from "@/components/StatusPill";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Search, CalendarClock, Download, Loader2, FileDown, RotateCcw } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "@/contexts/AuthContext";

function fmt(t) {
  if (!t) return "—";
  return new Date(t).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

export default function AdminAttendance() {
  const { user } = useAuth();
  const canExport = ["super_admin", "hr"].includes(user?.role);
  const [data, setData] = useState({ rows: [], date: "" });
  const [q, setQ] = useState("");
  const [day, setDay] = useState(new Date().toISOString().slice(0, 10));
  const [departments, setDepartments] = useState([]);
  const [exportOpen, setExportOpen] = useState(false);

  useEffect(() => {
    api.get("/attendance/monitor", { params: { day } }).then((r) => setData(r.data));
  }, [day]);
  useEffect(() => {
    api.get("/departments").then((r) => setDepartments(r.data)).catch(() => {});
  }, []);

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
          {canExport && (
            <Dialog open={exportOpen} onOpenChange={setExportOpen}>
              <DialogTrigger asChild>
                <Button className="h-10 rounded-lg bg-slate-900 hover:bg-slate-800 text-white" data-testid="att-export-btn">
                  <Download className="h-4 w-4 mr-1.5" strokeWidth={1.75} /> Export report
                </Button>
              </DialogTrigger>
              <ExportDialog departments={departments} onClose={() => setExportOpen(false)} />
            </Dialog>
          )}
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
                <td className="px-5 py-3 text-slate-700">
                  {fmt(r.check_out)}
                  {r.sessions_count > 1 && (
                    <span className="ml-2 inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md text-[10px] font-semibold text-blue-700 bg-blue-50 border border-blue-100" title={`${r.sessions_count} sessions today`}>
                      <RotateCcw className="h-2.5 w-2.5" strokeWidth={2} /> {r.sessions_count}×
                    </span>
                  )}
                </td>
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

function ExportDialog({ departments, onClose }) {
  const today = new Date().toISOString().slice(0, 10);
  const monthStart = (() => {
    const d = new Date(); d.setDate(1); return d.toISOString().slice(0, 10);
  })();
  const [start, setStart] = useState(monthStart);
  const [end, setEnd] = useState(today);
  const [department, setDepartment] = useState("all");
  const [busy, setBusy] = useState(false);

  const setRange = (preset) => {
    const now = new Date();
    if (preset === "today") { setStart(today); setEnd(today); return; }
    if (preset === "week") {
      const s = new Date(now); s.setDate(now.getDate() - 6);
      setStart(s.toISOString().slice(0, 10)); setEnd(today); return;
    }
    if (preset === "month") { setStart(monthStart); setEnd(today); return; }
    if (preset === "prev_month") {
      const s = new Date(now.getFullYear(), now.getMonth() - 1, 1);
      const e = new Date(now.getFullYear(), now.getMonth(), 0);
      setStart(s.toISOString().slice(0, 10));
      setEnd(e.toISOString().slice(0, 10));
      return;
    }
    if (preset === "quarter") {
      const s = new Date(now); s.setDate(now.getDate() - 89);
      setStart(s.toISOString().slice(0, 10)); setEnd(today); return;
    }
  };

  const download = async () => {
    if (!start || !end) { toast.error("Pick a start and end date"); return; }
    if (end < start) { toast.error("End date must be on or after start"); return; }
    setBusy(true);
    try {
      const { data, headers } = await api.get("/attendance/export", {
        params: { start, end, department },
        responseType: "blob",
      });
      const cd = headers["content-disposition"] || "";
      const m = /filename="?([^"]+)"?/.exec(cd);
      const filename = m ? m[1] : `attendance_${start}_to_${end}.csv`;
      const url = URL.createObjectURL(new Blob([data], { type: "text/csv" }));
      const a = document.createElement("a");
      a.href = url; a.download = filename; a.click();
      URL.revokeObjectURL(url);
      toast.success("Attendance report downloaded");
      onClose();
    } catch (e) {
      // With blob responseType, the error body is also a blob — read it
      let msg = "Export failed";
      try {
        const txt = await e.response?.data?.text?.();
        if (txt) { const j = JSON.parse(txt); msg = j?.detail || msg; }
      } catch { /* noop */ }
      toast.error(msg);
    } finally { setBusy(false); }
  };

  const days = (() => {
    try {
      const s = new Date(start), e = new Date(end);
      return Math.round((e - s) / 86400000) + 1;
    } catch { return 0; }
  })();

  return (
    <DialogContent className="rounded-2xl max-w-lg" data-testid="attendance-export-dialog">
      <DialogHeader>
        <DialogTitle className="font-display flex items-center gap-2">
          <FileDown className="h-5 w-5 text-slate-700" strokeWidth={1.5} />
          Export attendance report
        </DialogTitle>
      </DialogHeader>
      <div className="space-y-4 py-2">
        <div className="flex flex-wrap gap-2">
          {[["today","Today"],["week","Last 7 days"],["month","This month"],["prev_month","Last month"],["quarter","Last 90 days"]].map(([k,label]) => (
            <button key={k} type="button" onClick={() => setRange(k)}
              className="px-3 py-1.5 rounded-full border border-slate-200 hover:border-slate-400 hover:bg-slate-50 text-xs font-medium text-slate-700"
              data-testid={`export-preset-${k}`}
            >{label}</button>
          ))}
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label>Start date</Label>
            <Input type="date" value={start} onChange={(e) => setStart(e.target.value)} className="mt-1.5" data-testid="export-start" />
          </div>
          <div>
            <Label>End date</Label>
            <Input type="date" value={end} onChange={(e) => setEnd(e.target.value)} className="mt-1.5" data-testid="export-end" />
          </div>
        </div>
        <div>
          <Label>Department</Label>
          <Select value={department} onValueChange={setDepartment}>
            <SelectTrigger className="mt-1.5" data-testid="export-department"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All departments</SelectItem>
              {departments.map((d) => <SelectItem key={d.id} value={d.name}>{d.name}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <div className="rounded-lg bg-slate-50 border border-slate-100 p-3 text-xs text-slate-600 leading-relaxed">
          <div className="font-semibold text-slate-900 mb-1">CSV columns included:</div>
          Date · Employee code · Name · Department · Designation · Email · First check-in · Last check-out · Sessions · Total hours · Late (Y/N) · Late minutes · Early-departure minutes · Overtime hours · Status · Notes
        </div>
        <div className="text-[11px] text-slate-500">
          {days > 0 ? <>Range: <b>{days}</b> day{days === 1 ? "" : "s"}.</> : ""} Opens directly in Excel or Google Sheets.
        </div>
      </div>
      <DialogFooter>
        <Button onClick={download} disabled={busy} className="bg-slate-900 hover:bg-slate-800 text-white" data-testid="export-download">
          {busy ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : <Download className="h-4 w-4 mr-1.5" />}
          Download CSV
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}
