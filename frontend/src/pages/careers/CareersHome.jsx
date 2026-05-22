import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import axios from "axios";
import { Briefcase, MapPin, Clock, Search, ArrowUpRight, Building2 } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

export default function CareersHome() {
  const [jobs, setJobs] = useState([]);
  const [q, setQ] = useState("");
  const [dept, setDept] = useState("all");

  useEffect(() => {
    axios.get(`${API}/careers/jobs`, { params: { q: q || undefined, department: dept } }).then((r) => setJobs(r.data));
  }, [q, dept]);

  const departments = Array.from(new Set(jobs.map((j) => j.department)));

  return (
    <div className="min-h-screen bg-slate-50" data-testid="careers-home">
      {/* Header */}
      <header className="bg-white border-b border-slate-200">
        <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
          <Link to="/careers" className="flex items-center gap-2">
            <div className="h-8 w-8 rounded-lg bg-slate-900 grid place-items-center">
              <Building2 className="h-4 w-4 text-white" strokeWidth={1.5} />
            </div>
            <div>
              <div className="font-display text-base font-semibold text-slate-900 leading-none">Acme Corp</div>
              <div className="text-[10px] uppercase tracking-widest text-slate-400">Careers</div>
            </div>
          </Link>
          <Link to="/login" className="text-sm font-medium text-slate-600 hover:text-slate-900" data-testid="careers-employee-login-link">
            Employee sign in →
          </Link>
        </div>
      </header>

      {/* Hero */}
      <section className="relative overflow-hidden border-b border-slate-200 bg-white">
        <div className="absolute inset-0 grid-bg opacity-60" />
        <div className="relative max-w-6xl mx-auto px-6 py-20 lg:py-28">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-slate-200 bg-slate-50 text-xs uppercase tracking-widest font-semibold text-slate-600">
            <Briefcase className="h-3.5 w-3.5" strokeWidth={1.5} />
            We're hiring
          </div>
          <h1 className="font-display text-5xl sm:text-6xl lg:text-7xl font-semibold tracking-tight text-slate-900 mt-6 leading-[1.02]">
            Build the future of <br className="hidden sm:block" /> people operations.
          </h1>
          <p className="mt-6 text-lg text-slate-600 max-w-2xl leading-relaxed">
            We're a small team building software that treats people like people. Browse open roles below — we read every application.
          </p>
          <div className="mt-8 flex flex-wrap items-center gap-3">
            <a href="#openings" className="inline-flex items-center gap-2 px-5 h-11 rounded-lg bg-slate-900 hover:bg-slate-800 text-white text-sm font-medium" data-testid="see-openings-btn">
              See open roles <ArrowUpRight className="h-4 w-4" strokeWidth={1.5} />
            </a>
            <div className="text-sm text-slate-500"><b className="text-slate-900">{jobs.length}</b> open positions</div>
          </div>
        </div>
      </section>

      {/* Filters + listings */}
      <section id="openings" className="max-w-6xl mx-auto px-6 py-14">
        <div className="flex items-end justify-between flex-wrap gap-3 mb-6">
          <div>
            <h2 className="font-display text-2xl sm:text-3xl font-medium tracking-tight text-slate-900">Open positions</h2>
            <p className="text-sm text-slate-500 mt-1">Find your next role. Apply in 3 minutes.</p>
          </div>
          <div className="flex items-center gap-2">
            <div className="relative">
              <Search className="h-4 w-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" strokeWidth={1.5} />
              <Input value={q} onChange={(e)=>setQ(e.target.value)} placeholder="Search roles…" className="pl-9 h-10 w-56 rounded-lg border-slate-200" data-testid="job-search" />
            </div>
            <Select value={dept} onValueChange={setDept}>
              <SelectTrigger className="w-44 h-10 rounded-lg" data-testid="job-dept-filter"><SelectValue placeholder="Department" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All teams</SelectItem>
                {departments.map((d) => <SelectItem key={d} value={d}>{d}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
        </div>

        <div className="space-y-3">
          {jobs.length === 0 ? (
            <div className="surface p-12 text-center text-slate-400 text-sm">No open positions right now. Check back soon.</div>
          ) : jobs.map((j) => (
            <Link
              key={j.id}
              to={`/careers/${j.id}`}
              className="surface p-6 card-hover flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 group block"
              data-testid={`job-card-${j.id}`}
            >
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 text-xs uppercase tracking-widest font-semibold text-blue-600">
                  <span>{j.department}</span>
                </div>
                <h3 className="font-display text-xl font-medium text-slate-900 mt-2 group-hover:text-blue-700 transition-colors">{j.title}</h3>
                <div className="flex flex-wrap items-center gap-4 mt-2 text-sm text-slate-500">
                  <span className="flex items-center gap-1.5"><MapPin className="h-3.5 w-3.5" strokeWidth={1.5} />{j.location}</span>
                  <span className="flex items-center gap-1.5"><Clock className="h-3.5 w-3.5" strokeWidth={1.5} />{j.employment_type}</span>
                  {j.salary_range && <span className="text-slate-600 font-medium">{j.salary_range}</span>}
                </div>
              </div>
              <div className="text-blue-600 font-medium text-sm flex items-center gap-1 shrink-0 group-hover:gap-2 transition-all">
                View role <ArrowUpRight className="h-4 w-4" strokeWidth={1.5} />
              </div>
            </Link>
          ))}
        </div>
      </section>

      <footer className="border-t border-slate-200 bg-white">
        <div className="max-w-6xl mx-auto px-6 py-8 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
          <div className="text-sm text-slate-500">© Acme Corp · We're an equal opportunity employer.</div>
          <Link to="/login" className="text-sm font-medium text-slate-700 hover:text-slate-900">Employee sign in →</Link>
        </div>
      </footer>
    </div>
  );
}
