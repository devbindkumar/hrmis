import { useEffect, useState } from "react";
import api, { formatApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Plus, Loader2, Briefcase, MapPin, Clock, Users2, Trash2, ExternalLink, Mail, Phone, Linkedin, Globe, Download, FileText } from "lucide-react";
import { toast } from "sonner";
import StatusPill from "@/components/StatusPill";
import { getToken } from "@/lib/api";

const STAGE_COLORS = {
  new: "bg-blue-50 text-blue-700 border-blue-200",
  reviewing: "bg-amber-50 text-amber-700 border-amber-200",
  interview: "bg-fuchsia-50 text-fuchsia-700 border-fuchsia-200",
  offered: "bg-emerald-50 text-emerald-700 border-emerald-200",
  hired: "bg-emerald-50 text-emerald-700 border-emerald-200",
  rejected: "bg-slate-100 text-slate-600 border-slate-200",
};
const STAGES = ["new", "reviewing", "interview", "offered", "hired", "rejected"];

export default function AdminJobs() {
  const [tab, setTab] = useState("jobs");
  const [jobs, setJobs] = useState([]);
  const [apps, setApps] = useState([]);
  const [open, setOpen] = useState(false);
  const [selectedJob, setSelectedJob] = useState("all");
  const [stageFilter, setStageFilter] = useState("all");
  const [viewing, setViewing] = useState(null);

  const loadJobs = () => api.get("/jobs").then((r) => setJobs(r.data));
  const loadApps = () => api.get("/jobs/applications/list", { params: { job_id: selectedJob, stage: stageFilter } }).then((r) => setApps(r.data));

  useEffect(() => { loadJobs(); }, []);
  useEffect(() => { loadApps(); /* eslint-disable-next-line */ }, [selectedJob, stageFilter]);

  const removeJob = async (id) => {
    if (!window.confirm("Delete this job posting?")) return;
    try { await api.delete(`/jobs/${id}`); toast.success("Job removed"); loadJobs(); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  const toggleStatus = async (j) => {
    const newStatus = j.status === "open" ? "closed" : "open";
    await api.patch(`/jobs/${j.id}`, { status: newStatus });
    toast.success(`Job ${newStatus === "open" ? "re-opened" : "closed"}`);
    loadJobs();
  };

  const moveStage = async (a, stage) => {
    await api.patch(`/jobs/applications/${a.id}`, { stage, notify_candidate: true });
    toast.success("Stage updated — candidate notified");
    loadApps();
    if (viewing?.id === a.id) setViewing({ ...viewing, stage });
  };

  const exportCsv = async () => {
    const url = `${process.env.REACT_APP_BACKEND_URL}/api/jobs/applications/export.csv?job_id=${encodeURIComponent(selectedJob)}&stage=${encodeURIComponent(stageFilter)}`;
    try {
      const res = await fetch(url, { headers: { Authorization: `Bearer ${getToken()}` } });
      if (!res.ok) throw new Error("Export failed");
      const blob = await res.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `applicants-${new Date().toISOString().slice(0,10)}.csv`;
      a.click();
      URL.revokeObjectURL(a.href);
      toast.success("Exported");
    } catch (e) { toast.error("Couldn't export CSV"); }
  };

  const downloadResume = async (a) => {
    try {
      const res = await fetch(`${process.env.REACT_APP_BACKEND_URL}/api/jobs/applications/${a.id}/resume`, {
        headers: { Authorization: `Bearer ${getToken()}` },
      });
      if (!res.ok) throw new Error("Couldn't fetch");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank");
      setTimeout(() => URL.revokeObjectURL(url), 30000);
    } catch (e) { toast.error("Couldn't download resume"); }
  };

  const careersUrl = `${window.location.origin}/careers`;

  return (
    <div className="p-6 space-y-5 animate-fade-up" data-testid="admin-jobs">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="font-display text-3xl font-semibold tracking-tight text-slate-900">Jobs & applicants</h1>
          <p className="text-sm text-slate-500 mt-1">Public careers site + applicant tracking.</p>
        </div>
        <div className="flex items-center gap-2">
          <a href={careersUrl} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 text-sm font-medium text-blue-600 hover:underline" data-testid="open-careers-link">
            Open public careers page <ExternalLink className="h-3.5 w-3.5" />
          </a>
        </div>
      </div>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="jobs" data-testid="tab-jobs">Postings ({jobs.length})</TabsTrigger>
          <TabsTrigger value="applications" data-testid="tab-applications">Applications ({apps.length})</TabsTrigger>
        </TabsList>

        <TabsContent value="jobs" className="mt-4 space-y-4">
          <div className="flex justify-end">
            <Dialog open={open} onOpenChange={setOpen}>
              <DialogTrigger asChild>
                <Button className="bg-slate-900 hover:bg-slate-800 text-white rounded-lg" data-testid="new-job-btn"><Plus className="h-4 w-4 mr-1.5" /> Post a job</Button>
              </DialogTrigger>
              <NewJobDialog onCreated={() => { setOpen(false); loadJobs(); }} />
            </Dialog>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {jobs.length === 0 ? <div className="surface p-12 text-center text-slate-400 md:col-span-2">No jobs posted yet.</div> :
              jobs.map((j) => (
                <div key={j.id} className="surface p-5 card-hover" data-testid={`job-${j.id}`}>
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="text-xs uppercase tracking-widest font-semibold text-blue-600">{j.department}</div>
                      <h3 className="font-display text-lg font-medium text-slate-900 mt-1.5 truncate">{j.title}</h3>
                      <div className="flex flex-wrap items-center gap-3 mt-2 text-xs text-slate-500">
                        <span className="flex items-center gap-1"><MapPin className="h-3 w-3" />{j.location}</span>
                        <span className="flex items-center gap-1"><Clock className="h-3 w-3" />{j.employment_type}</span>
                        <span className="flex items-center gap-1"><Users2 className="h-3 w-3" />{j.applicant_count || 0} applied</span>
                      </div>
                    </div>
                    <StatusPill status={j.status === "open" ? "active" : "absent"} label={j.status === "open" ? "Open" : "Closed"} />
                  </div>
                  <p className="text-sm text-slate-600 mt-3 line-clamp-2">{j.description}</p>
                  <div className="flex items-center justify-between mt-4 pt-3 border-t border-slate-100">
                    <button onClick={()=>{ setSelectedJob(j.id); setTab("applications"); }} className="text-xs font-medium text-blue-600 hover:underline" data-testid={`view-apps-${j.id}`}>
                      View applicants →
                    </button>
                    <div className="flex items-center gap-1">
                      <button onClick={()=>toggleStatus(j)} className="text-xs text-slate-600 hover:text-slate-900 px-2 py-1 rounded-md border border-slate-200 hover:bg-slate-50" data-testid={`toggle-job-${j.id}`}>
                        {j.status === "open" ? "Close" : "Re-open"}
                      </button>
                      <button onClick={()=>removeJob(j.id)} className="text-slate-400 hover:text-rose-600 p-1" data-testid={`del-job-${j.id}`}>
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  </div>
                </div>
              ))}
          </div>
        </TabsContent>

        <TabsContent value="applications" className="mt-4 space-y-4">
          <div className="flex items-center gap-3">
            <Select value={selectedJob} onValueChange={setSelectedJob}>
              <SelectTrigger className="w-64 h-10 rounded-lg" data-testid="filter-app-job"><SelectValue placeholder="Filter by role" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All roles</SelectItem>
                {jobs.map((j) => <SelectItem key={j.id} value={j.id}>{j.title}</SelectItem>)}
              </SelectContent>
            </Select>
            <Select value={stageFilter} onValueChange={setStageFilter}>
              <SelectTrigger className="w-40 h-10 rounded-lg" data-testid="filter-app-stage"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All stages</SelectItem>
                {STAGES.map((s) => <SelectItem key={s} value={s}>{s.charAt(0).toUpperCase() + s.slice(1)}</SelectItem>)}
              </SelectContent>
            </Select>
            <div className="text-sm text-slate-500 flex-1">{apps.length} applicants</div>
            <Button variant="outline" onClick={exportCsv} className="rounded-lg" data-testid="export-applicants-csv">
              <Download className="h-4 w-4 mr-1.5" /> Export CSV
            </Button>
          </div>

          <div className="surface overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-slate-50 text-slate-500 text-xs uppercase tracking-wide">
                  <th className="text-left font-semibold px-5 py-3">Applicant</th>
                  <th className="text-left font-semibold px-5 py-3">Role</th>
                  <th className="text-left font-semibold px-5 py-3">Applied</th>
                  <th className="text-left font-semibold px-5 py-3">Stage</th>
                  <th className="text-right font-semibold px-5 py-3">Action</th>
                </tr>
              </thead>
              <tbody>
                {apps.length === 0 ? <tr><td colSpan="5" className="px-5 py-12 text-center text-slate-400">No applications yet.</td></tr> :
                  apps.map((a) => (
                    <tr key={a.id} className="border-t border-slate-100 hover:bg-slate-50/60">
                      <td className="px-5 py-3">
                        <div className="font-medium text-slate-900">{a.name}</div>
                        <div className="text-xs text-slate-500 flex items-center gap-1"><Mail className="h-3 w-3" />{a.email}</div>
                      </td>
                      <td className="px-5 py-3 text-slate-700">{a.job_title}</td>
                      <td className="px-5 py-3 text-slate-500 text-xs">{new Date(a.created_at).toLocaleDateString()}</td>
                      <td className="px-5 py-3">
                        <span className={`inline-block px-2.5 py-0.5 rounded-full text-xs font-medium border ${STAGE_COLORS[a.stage] || STAGE_COLORS.new}`}>
                          {a.stage}
                        </span>
                      </td>
                      <td className="px-5 py-3 text-right">
                        {a.resume_path && (
                          <Button size="sm" variant="ghost" className="h-8 mr-1 text-slate-600" onClick={()=>downloadResume(a)} title="Download resume" data-testid={`dl-resume-${a.id}`}>
                            <FileText className="h-4 w-4" />
                          </Button>
                        )}
                        <Button size="sm" variant="outline" className="h-8 rounded-md" onClick={()=>setViewing(a)} data-testid={`view-app-${a.id}`}>Review</Button>
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </TabsContent>
      </Tabs>

      {/* Application review dialog */}
      <Dialog open={!!viewing} onOpenChange={(o)=>{ if(!o) setViewing(null); }}>
        <DialogContent className="rounded-2xl max-w-2xl max-h-[85vh] overflow-y-auto">
          {viewing && (
            <>
              <DialogHeader>
                <DialogTitle className="font-display text-2xl">{viewing.name}</DialogTitle>
                <div className="text-sm text-slate-500">Applied for <b className="text-slate-900">{viewing.job_title}</b> · {new Date(viewing.created_at).toLocaleString()}</div>
              </DialogHeader>
              <div className="space-y-4">
                <div className="grid grid-cols-2 gap-3 text-sm">
                  {viewing.email && <ContactRow icon={Mail} label="Email" value={viewing.email} href={`mailto:${viewing.email}`} />}
                  {viewing.phone && <ContactRow icon={Phone} label="Phone" value={viewing.phone} href={`tel:${viewing.phone}`} />}
                  {viewing.linkedin && <ContactRow icon={Linkedin} label="LinkedIn" value={viewing.linkedin} href={viewing.linkedin.startsWith("http") ? viewing.linkedin : `https://${viewing.linkedin}`} />}
                  {viewing.portfolio && <ContactRow icon={Globe} label="Portfolio" value={viewing.portfolio} href={viewing.portfolio} />}
                </div>
                <div>
                  <div className="text-xs uppercase tracking-widest font-semibold text-slate-500 mb-2">Cover letter</div>
                  <p className="text-sm text-slate-700 leading-relaxed whitespace-pre-line bg-slate-50 rounded-lg p-4 border border-slate-100">{viewing.cover_letter}</p>
                </div>
                {viewing.resume_path && (
                  <div>
                    <div className="text-xs uppercase tracking-widest font-semibold text-slate-500 mb-2">Resume</div>
                    <button onClick={()=>downloadResume(viewing)} className="inline-flex items-center gap-2 rounded-lg border border-slate-200 hover:border-slate-300 px-3 py-2 hover:bg-slate-50 text-sm" data-testid="dialog-dl-resume">
                      <FileText className="h-4 w-4 text-blue-600" strokeWidth={1.5} />
                      <span className="font-medium text-slate-900">{viewing.resume_filename || "View resume"}</span>
                      <Download className="h-3.5 w-3.5 text-slate-400" />
                    </button>
                  </div>
                )}
                <div>
                  <div className="text-xs uppercase tracking-widest font-semibold text-slate-500 mb-2">Move to stage</div>
                  <div className="flex flex-wrap gap-2">
                    {STAGES.map((s) => (
                      <button
                        key={s}
                        onClick={()=>moveStage(viewing, s)}
                        className={`px-3 py-1.5 rounded-full text-xs font-medium border ${viewing.stage === s ? STAGE_COLORS[s] : "border-slate-200 text-slate-600 hover:bg-slate-50"}`}
                        data-testid={`stage-${s}-${viewing.id}`}
                      >
                        {s}
                      </button>
                    ))}
                  </div>
                  <p className="text-xs text-slate-400 mt-2">The candidate is automatically emailed when the stage changes.</p>
                </div>
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

function ContactRow({ icon: Icon, label, value, href }) {
  return (
    <div className="rounded-lg border border-slate-100 p-3">
      <div className="text-[10px] uppercase tracking-widest font-semibold text-slate-400">{label}</div>
      <a href={href} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1.5 text-sm text-slate-900 hover:text-blue-700 truncate">
        <Icon className="h-3.5 w-3.5 shrink-0 text-slate-400" strokeWidth={1.5} />
        <span className="truncate">{value}</span>
      </a>
    </div>
  );
}

function NewJobDialog({ onCreated }) {
  const [form, setForm] = useState({
    title: "", department: "", location: "Remote", employment_type: "Full-time",
    description: "", requirements: "", salary_range: "",
  });
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!form.title || !form.department || !form.description) { toast.error("Title, department and description are required"); return; }
    setBusy(true);
    try {
      await api.post("/jobs", form);
      toast.success("Job posted on careers page");
      onCreated();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };

  return (
    <DialogContent className="rounded-2xl max-w-2xl">
      <DialogHeader><DialogTitle className="font-display">Post a new job</DialogTitle></DialogHeader>
      <div className="grid grid-cols-2 gap-3">
        <div className="col-span-2"><Label>Title *</Label><Input value={form.title} onChange={(e)=>setForm({...form, title: e.target.value})} className="mt-1.5" data-testid="job-title" /></div>
        <div><Label>Department *</Label><Input value={form.department} onChange={(e)=>setForm({...form, department: e.target.value})} className="mt-1.5" data-testid="job-dept" /></div>
        <div>
          <Label>Type</Label>
          <Select value={form.employment_type} onValueChange={(v)=>setForm({...form, employment_type: v})}>
            <SelectTrigger className="mt-1.5" data-testid="job-type"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="Full-time">Full-time</SelectItem>
              <SelectItem value="Part-time">Part-time</SelectItem>
              <SelectItem value="Contract">Contract</SelectItem>
              <SelectItem value="Internship">Internship</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div><Label>Location</Label><Input value={form.location} onChange={(e)=>setForm({...form, location: e.target.value})} className="mt-1.5" /></div>
        <div><Label>Salary range</Label><Input value={form.salary_range} onChange={(e)=>setForm({...form, salary_range: e.target.value})} placeholder="$100k – $130k" className="mt-1.5" /></div>
        <div className="col-span-2"><Label>Description *</Label><Textarea value={form.description} onChange={(e)=>setForm({...form, description: e.target.value})} className="mt-1.5 min-h-[100px]" data-testid="job-desc" /></div>
        <div className="col-span-2"><Label>Requirements (one per line)</Label><Textarea value={form.requirements} onChange={(e)=>setForm({...form, requirements: e.target.value})} className="mt-1.5 min-h-[100px]" placeholder="3+ years experience\nStrong Python skills\nGreat communication" /></div>
      </div>
      <DialogFooter><Button onClick={submit} disabled={busy} className="bg-slate-900 hover:bg-slate-800 text-white" data-testid="job-submit">{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : "Publish"}</Button></DialogFooter>
    </DialogContent>
  );
}
