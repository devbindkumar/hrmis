import { useEffect, useState } from "react";
import api from "@/lib/api";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Mail, Phone, Building2, MapPin, Briefcase, IdCard, Clock, Calendar, Users2, ChevronRight } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";

export default function Profile() {
  const [me, setMe] = useState(null);
  const [hist, setHist] = useState([]);
  const [reports, setReports] = useState([]);

  useEffect(() => {
    const load = async () => {
      const { data: emp } = await api.get("/employees/me");
      setMe(emp);
      api.get("/attendance/history").then((r)=>setHist(r.data));
      if (emp?.id) {
        api.get(`/employees/${emp.id}/reports`).then((r)=>setReports(r.data)).catch(()=>{});
      }
    };
    load();
  }, []);

  if (!me) return <div className="space-y-4"><Skeleton className="h-44" /><Skeleton className="h-44" /></div>;

  return (
    <div className="space-y-6 animate-fade-up" data-testid="profile-page">
      <div className="surface p-6 md:p-8 relative overflow-hidden">
        <div className="absolute inset-x-0 top-0 h-24 bg-gradient-to-r from-slate-900 to-slate-700" />
        <div className="relative flex flex-col md:flex-row md:items-end gap-5">
          <Avatar className="h-24 w-24 ring-4 ring-white">
            <AvatarImage src={me.avatar_url} alt={me.name} />
            <AvatarFallback className="text-lg bg-slate-200">{me.name.split(" ").map(p=>p[0]).slice(0,2).join("")}</AvatarFallback>
          </Avatar>
          <div className="flex-1">
            <h1 className="font-display text-3xl font-semibold tracking-tight text-slate-900 mt-3">{me.name}</h1>
            <p className="text-slate-500 text-sm">{me.designation} · {me.department}</p>
            <div className="mt-3 flex flex-wrap gap-4 text-sm text-slate-600">
              <span className="flex items-center gap-1.5"><IdCard className="h-3.5 w-3.5" strokeWidth={1.5} /> {me.employee_code}</span>
              <span className="flex items-center gap-1.5"><Mail className="h-3.5 w-3.5" strokeWidth={1.5} /> {me.email}</span>
              {me.phone && <span className="flex items-center gap-1.5"><Phone className="h-3.5 w-3.5" strokeWidth={1.5} /> {me.phone}</span>}
              <span className="flex items-center gap-1.5"><MapPin className="h-3.5 w-3.5" strokeWidth={1.5} /> {me.location}</span>
            </div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="surface p-6">
          <h3 className="font-display text-lg font-medium text-slate-900">Employment</h3>
          <dl className="mt-4 space-y-3 text-sm">
            <Row icon={Briefcase} label="Designation" value={me.designation} />
            <Row icon={Building2} label="Department" value={me.department} />
            <Row icon={MapPin} label="Location" value={me.location} />
            <Row icon={Clock} label="Shift" value={me.shift} />
            <Row icon={Calendar} label="Joined" value={me.joined_at} />
          </dl>

          {/* Reports-to / manager */}
          <div className="mt-6 pt-5 border-t border-slate-100" data-testid="manager-card">
            <div className="text-xs uppercase tracking-widest text-slate-400 font-semibold">Reports to</div>
            {me.manager_name ? (
              <div className="mt-3 flex items-center gap-3">
                <Avatar className="h-10 w-10">
                  <AvatarImage src={me.manager_avatar_url} alt={me.manager_name} />
                  <AvatarFallback className="text-xs bg-slate-100">{me.manager_name.split(" ").map(p=>p[0]).slice(0,2).join("")}</AvatarFallback>
                </Avatar>
                <div className="min-w-0">
                  <div className="text-sm font-medium text-slate-900 truncate">{me.manager_name}</div>
                  <div className="text-xs text-slate-500 truncate">{me.manager_designation}</div>
                </div>
                {me.manager_email && (
                  <a href={`mailto:${me.manager_email}`} className="ml-auto text-xs text-blue-600 hover:underline">Email</a>
                )}
              </div>
            ) : (
              <p className="text-sm text-slate-400 mt-2">You report directly to leadership.</p>
            )}
          </div>
        </div>

        <div className="surface p-6 lg:col-span-2">
          <h3 className="font-display text-lg font-medium text-slate-900">Attendance · last 30 days</h3>
          <div className="mt-4 grid grid-cols-7 gap-2">
            {Array.from({ length: 30 }).map((_, i) => {
              const day = new Date();
              day.setDate(day.getDate() - (29 - i));
              const iso = day.toISOString().slice(0, 10);
              const rec = hist.find((h) => h.date === iso);
              const state = !rec ? "empty" : (rec.check_in ? (rec.is_late ? "late" : "present") : "absent");
              const c =
                state === "present" ? "bg-emerald-500/90" :
                state === "late" ? "bg-amber-500/80" :
                state === "absent" ? "bg-rose-500/50" : "bg-slate-100";
              return (
                <div key={i} className={`h-9 rounded-md ${c}`} title={`${iso} · ${state}`} />
              );
            })}
          </div>
          <div className="mt-4 flex items-center gap-4 text-xs text-slate-500">
            <Legend color="bg-emerald-500/90" label="Present" />
            <Legend color="bg-amber-500/80" label="Late" />
            <Legend color="bg-rose-500/50" label="Absent" />
            <Legend color="bg-slate-100" label="Weekend / No data" />
          </div>
        </div>
      </div>

      {/* Direct reports section - only shown if person has any */}
      {reports.length > 0 && (
        <div className="surface p-6" data-testid="direct-reports-card">
          <div className="flex items-center gap-2">
            <Users2 className="h-4 w-4 text-slate-500" strokeWidth={1.5} />
            <h3 className="font-display text-lg font-medium text-slate-900">Your team</h3>
            <span className="text-xs text-slate-500 ml-1">· {reports.length} direct {reports.length === 1 ? "report" : "reports"}</span>
          </div>
          <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {reports.map((r) => (
              <div key={r.id} className="rounded-lg border border-slate-100 hover:border-slate-200 p-3 flex items-center gap-3 transition-colors" data-testid={`report-${r.id}`}>
                <Avatar className="h-10 w-10">
                  <AvatarImage src={r.avatar_url} alt={r.name} />
                  <AvatarFallback className="text-xs bg-slate-100">{r.name.split(" ").map(p=>p[0]).slice(0,2).join("")}</AvatarFallback>
                </Avatar>
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium text-slate-900 truncate">{r.name}</div>
                  <div className="text-xs text-slate-500 truncate">{r.designation}</div>
                </div>
                <a href={`mailto:${r.email}`} className="text-slate-400 hover:text-blue-600" title="Email">
                  <Mail className="h-4 w-4" strokeWidth={1.5} />
                </a>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function Row({ icon: Icon, label, value }) {
  return (
    <div className="flex items-start gap-3">
      <Icon className="h-4 w-4 text-slate-400 mt-0.5" strokeWidth={1.5} />
      <div>
        <dt className="text-xs uppercase tracking-widest text-slate-400 font-semibold">{label}</dt>
        <dd className="text-slate-800">{value || "—"}</dd>
      </div>
    </div>
  );
}

function Legend({ color, label }) {
  return <div className="flex items-center gap-1.5"><span className={`h-3 w-3 rounded-sm ${color}`} /> {label}</div>;
}
