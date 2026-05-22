import { useEffect, useState } from "react";
import api from "@/lib/api";
import { Card } from "@/components/ui/card";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, PieChart, Pie, Cell, Legend as RLegend } from "recharts";
import { Download } from "lucide-react";
import { Button } from "@/components/ui/button";

const COLORS = ["#0f172a", "#3b82f6", "#10b981", "#f59e0b", "#a855f7", "#ef4444", "#14b8a6"];

export default function AdminReports() {
  const [dash, setDash] = useState(null);
  const [leaves, setLeaves] = useState([]);

  useEffect(() => {
    api.get("/dashboard/admin").then((r)=>setDash(r.data));
    api.get("/leave/all").then((r)=>setLeaves(r.data));
  }, []);

  const exportCsv = () => {
    if (!leaves.length) return;
    const headers = ["employee", "type", "start", "end", "days", "status", "created_at"];
    const rows = leaves.map((l) => [l.user_name, l.leave_type, l.start_date, l.end_date, l.days, l.status, l.created_at]);
    const csv = [headers, ...rows].map((r) => r.map((c)=>`"${String(c||'').replace(/"/g, '""')}"`).join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `leave-report-${Date.now()}.csv`; a.click();
    URL.revokeObjectURL(url);
  };

  if (!dash) return null;

  // leave type breakdown
  const typeMap = {};
  leaves.forEach((l) => { typeMap[l.leave_type] = (typeMap[l.leave_type] || 0) + l.days; });
  const typeData = Object.entries(typeMap).map(([name, value]) => ({ name, value }));

  return (
    <div className="p-6 space-y-6 animate-fade-up" data-testid="admin-reports">
      <div className="flex items-end justify-between gap-3 flex-wrap">
        <div>
          <h1 className="font-display text-3xl font-semibold tracking-tight text-slate-900">Reports</h1>
          <p className="text-sm text-slate-500 mt-1">Attendance and leave analytics across the org.</p>
        </div>
        <Button onClick={exportCsv} variant="outline" className="rounded-lg" data-testid="export-csv-btn"><Download className="h-4 w-4 mr-1.5" /> Export leave CSV</Button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="surface p-6">
          <h3 className="font-display text-lg font-medium text-slate-900">Attendance trend</h3>
          <p className="text-xs text-slate-500 mt-0.5">Last 7 days</p>
          <div className="h-72 mt-4">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={dash.trend_7d}>
                <CartesianGrid stroke="#f1f5f9" vertical={false} />
                <XAxis dataKey="date" stroke="#94a3b8" fontSize={11} tickFormatter={(d)=>new Date(d).toLocaleDateString(undefined, { weekday: 'short' })} />
                <YAxis stroke="#94a3b8" fontSize={11} />
                <Tooltip contentStyle={{ borderRadius: 8, border: '1px solid #e5e7eb' }} />
                <Bar dataKey="present" fill="#10b981" />
                <Bar dataKey="wfh" fill="#3b82f6" />
                <Bar dataKey="leave" fill="#f59e0b" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="surface p-6">
          <h3 className="font-display text-lg font-medium text-slate-900">Leave by type</h3>
          <p className="text-xs text-slate-500 mt-0.5">Days requested across all employees</p>
          <div className="h-72 mt-4">
            {typeData.length === 0 ? (
              <div className="h-full flex items-center justify-center text-slate-400 text-sm">No data yet</div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={typeData} dataKey="value" nameKey="name" outerRadius={90} innerRadius={50} paddingAngle={4}>
                    {typeData.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
                  </Pie>
                  <Tooltip />
                  <RLegend />
                </PieChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>

        <div className="surface p-6 lg:col-span-2">
          <h3 className="font-display text-lg font-medium text-slate-900">Headcount by department</h3>
          <div className="mt-4 space-y-3">
            {dash.department_counts.map((d) => {
              const max = Math.max(...dash.department_counts.map((x) => x.count), 1);
              const pct = (d.count / max) * 100;
              return (
                <div key={d.name}>
                  <div className="flex items-baseline justify-between text-sm">
                    <span className="text-slate-800 font-medium">{d.name}</span>
                    <span className="text-slate-500">{d.count} {d.count === 1 ? 'person' : 'people'}</span>
                  </div>
                  <div className="h-2 rounded-full bg-slate-100 mt-1 overflow-hidden">
                    <div className="h-full rounded-full bg-blue-600" style={{ width: `${pct}%` }} />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
