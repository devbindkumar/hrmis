import { useEffect, useState, useRef } from "react";
import { Link, useParams, useNavigate } from "react-router-dom";
import axios from "axios";
import { Briefcase, MapPin, Clock, ArrowLeft, CheckCircle2, Building2, Loader2, Paperclip, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "sonner";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

export default function JobDetail() {
  const { id, slug } = useParams();
  const navigate = useNavigate();
  const careersBase = slug ? `/c/${slug}/careers` : "/careers";
  const [job, setJob] = useState(null);
  const [submitted, setSubmitted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({ name: "", email: "", phone: "", linkedin: "", portfolio: "", cover_letter: "" });
  const [resume, setResume] = useState(null); // { path, filename, size }
  const [uploadingResume, setUploadingResume] = useState(false);
  const fileRef = useRef();

  useEffect(() => {
    axios.get(`${API}/careers/jobs/${id}`).then((r) => setJob(r.data)).catch(() => {
      toast.error("This position is no longer open");
      navigate(careersBase);
    });
  }, [id, navigate, careersBase]);

  const submit = async (e) => {
    e.preventDefault();
    if (form.cover_letter.length < 20) { toast.error("Please write at least a short cover letter."); return; }
    setBusy(true);
    try {
      await axios.post(`${API}/careers/apply`, {
        ...form,
        job_id: id,
        resume_path: resume?.path || null,
        resume_filename: resume?.filename || null,
      });
      setSubmitted(true);
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (err) {
      const detail = err.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : "Couldn't submit your application");
    } finally { setBusy(false); }
  };

  const handleResume = async (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    if (f.size > 10 * 1024 * 1024) { toast.error("File must be under 10 MB"); return; }
    setUploadingResume(true);
    try {
      const data = new FormData();
      data.append("file", f);
      const { data: res } = await axios.post(`${API}/careers/resume`, data);
      setResume(res);
      toast.success("Resume uploaded");
    } catch (err) {
      const detail = err.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : "Couldn't upload resume");
    } finally {
      setUploadingResume(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  if (!job) return <div className="min-h-screen grid place-items-center text-slate-400"><Loader2 className="h-6 w-6 animate-spin" /></div>;

  return (
    <div className="min-h-screen bg-slate-50" data-testid="job-detail">
      <header className="bg-white border-b border-slate-200">
        <div className="max-w-4xl mx-auto px-6 h-16 flex items-center justify-between">
          <Link to={careersBase} className="flex items-center gap-2 text-slate-700 hover:text-slate-900">
            <ArrowLeft className="h-4 w-4" strokeWidth={1.5} /> <span className="text-sm font-medium">All openings</span>
          </Link>
          <div className="flex items-center gap-2">
            <div className="h-7 w-7 rounded-lg bg-slate-900 grid place-items-center">
              <Building2 className="h-3.5 w-3.5 text-white" strokeWidth={1.5} />
            </div>
            <div className="font-display text-sm font-semibold text-slate-900">Acme Corp · Careers</div>
          </div>
        </div>
      </header>

      <div className="max-w-4xl mx-auto px-6 py-10">
        {submitted ? (
          <div className="surface p-10 text-center max-w-xl mx-auto" data-testid="application-success">
            <div className="h-14 w-14 rounded-full bg-emerald-50 grid place-items-center mx-auto">
              <CheckCircle2 className="h-7 w-7 text-emerald-600" strokeWidth={1.5} />
            </div>
            <h2 className="font-display text-2xl font-semibold text-slate-900 mt-5">Application received</h2>
            <p className="text-sm text-slate-500 mt-2">Thanks for applying to <b className="text-slate-900">{job.title}</b>. We've sent a confirmation to your email and our recruiting team will be in touch within 5 working days.</p>
            <Link to={careersBase} className="inline-block mt-6 text-sm font-medium text-blue-600 hover:underline">← Browse other roles</Link>
          </div>
        ) : (
          <>
            <div className="surface p-8 mb-6">
              <div className="text-xs uppercase tracking-widest font-semibold text-blue-600">{job.department}</div>
              <h1 className="font-display text-4xl font-semibold tracking-tight text-slate-900 mt-3">{job.title}</h1>
              <div className="flex flex-wrap items-center gap-5 mt-4 text-sm text-slate-600">
                <span className="flex items-center gap-1.5"><MapPin className="h-3.5 w-3.5" strokeWidth={1.5} /> {job.location}</span>
                <span className="flex items-center gap-1.5"><Clock className="h-3.5 w-3.5" strokeWidth={1.5} /> {job.employment_type}</span>
                {job.salary_range && <span className="px-2.5 py-0.5 rounded-md bg-emerald-50 border border-emerald-200 text-emerald-700 text-xs font-medium">{job.salary_range}</span>}
              </div>

              <div className="mt-8 grid md:grid-cols-3 gap-8 text-sm text-slate-700 leading-relaxed">
                <div className="md:col-span-2 space-y-6">
                  <section>
                    <h3 className="text-xs uppercase tracking-widest font-semibold text-slate-500 mb-2">About the role</h3>
                    <p className="whitespace-pre-line">{job.description}</p>
                  </section>
                  {job.requirements && (
                    <section>
                      <h3 className="text-xs uppercase tracking-widest font-semibold text-slate-500 mb-2">What we're looking for</h3>
                      <ul className="space-y-1.5">
                        {job.requirements.split("\n").filter(Boolean).map((r, i) => (
                          <li key={i} className="flex items-start gap-2"><span className="h-1.5 w-1.5 rounded-full bg-slate-400 mt-2 shrink-0" />{r}</li>
                        ))}
                      </ul>
                    </section>
                  )}
                </div>
                <aside className="md:col-span-1">
                  <div className="rounded-xl bg-slate-50 border border-slate-100 p-4">
                    <div className="text-xs uppercase tracking-widest font-semibold text-slate-500">At a glance</div>
                    <dl className="mt-3 space-y-2 text-sm">
                      <div><dt className="text-slate-500">Team</dt><dd className="text-slate-900 font-medium">{job.department}</dd></div>
                      <div><dt className="text-slate-500">Type</dt><dd className="text-slate-900 font-medium">{job.employment_type}</dd></div>
                      <div><dt className="text-slate-500">Location</dt><dd className="text-slate-900 font-medium">{job.location}</dd></div>
                      {job.salary_range && <div><dt className="text-slate-500">Compensation</dt><dd className="text-slate-900 font-medium">{job.salary_range}</dd></div>}
                    </dl>
                  </div>
                </aside>
              </div>
            </div>

            {/* Application form */}
            <form onSubmit={submit} className="surface p-8" data-testid="application-form">
              <h2 className="font-display text-2xl font-semibold text-slate-900">Apply for this role</h2>
              <p className="text-sm text-slate-500 mt-1">It takes about 3 minutes. We read every application.</p>

              <div className="mt-6 grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="md:col-span-2">
                  <Label>Full name *</Label>
                  <Input value={form.name} onChange={(e)=>setForm({...form, name: e.target.value})} className="mt-1.5" required data-testid="apply-name" />
                </div>
                <div>
                  <Label>Email *</Label>
                  <Input type="email" value={form.email} onChange={(e)=>setForm({...form, email: e.target.value})} className="mt-1.5" required data-testid="apply-email" />
                </div>
                <div>
                  <Label>Phone</Label>
                  <Input value={form.phone} onChange={(e)=>setForm({...form, phone: e.target.value})} className="mt-1.5" data-testid="apply-phone" />
                </div>
                <div>
                  <Label>LinkedIn</Label>
                  <Input placeholder="linkedin.com/in/..." value={form.linkedin} onChange={(e)=>setForm({...form, linkedin: e.target.value})} className="mt-1.5" data-testid="apply-linkedin" />
                </div>
                <div>
                  <Label>Portfolio / GitHub</Label>
                  <Input placeholder="https://…" value={form.portfolio} onChange={(e)=>setForm({...form, portfolio: e.target.value})} className="mt-1.5" data-testid="apply-portfolio" />
                </div>
                <div className="md:col-span-2">
                  <Label>Why are you a great fit for this role? *</Label>
                  <Textarea value={form.cover_letter} onChange={(e)=>setForm({...form, cover_letter: e.target.value})} placeholder="Tell us a bit about you — your relevant work, what excites you about this role, and anything else we should know." className="mt-1.5 min-h-[140px]" required data-testid="apply-cover" />
                  <div className="text-xs text-slate-400 mt-1">{form.cover_letter.length} characters · min 20</div>
                </div>
                <div className="md:col-span-2">
                  <Label>Resume (PDF or DOC, optional)</Label>
                  <div className="mt-1.5">
                    {resume ? (
                      <div className="flex items-center justify-between rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3" data-testid="resume-uploaded">
                        <div className="flex items-center gap-2 text-sm text-emerald-700 min-w-0">
                          <Paperclip className="h-4 w-4 shrink-0" strokeWidth={1.5} />
                          <span className="font-medium truncate">{resume.filename}</span>
                          <span className="text-xs text-emerald-600">{(resume.size / 1024).toFixed(0)} KB</span>
                        </div>
                        <button type="button" onClick={()=>setResume(null)} className="text-emerald-700 hover:text-emerald-900 ml-3 shrink-0" data-testid="remove-resume">
                          <X className="h-4 w-4" />
                        </button>
                      </div>
                    ) : (
                      <label className="flex items-center justify-center gap-2 rounded-lg border-2 border-dashed border-slate-200 hover:border-slate-300 hover:bg-slate-50 px-4 py-6 cursor-pointer transition-colors" data-testid="resume-upload-zone">
                        {uploadingResume ? (
                          <span className="flex items-center gap-2 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" /> Uploading…</span>
                        ) : (
                          <span className="flex items-center gap-2 text-sm text-slate-600">
                            <Paperclip className="h-4 w-4" strokeWidth={1.5} />
                            <span><b className="text-slate-900">Click to upload</b> · PDF or DOC, max 10 MB</span>
                          </span>
                        )}
                        <input ref={fileRef} type="file" className="hidden" accept=".pdf,.doc,.docx,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document" onChange={handleResume} data-testid="apply-resume" />
                      </label>
                    )}
                  </div>
                </div>
              </div>

              <div className="mt-6 flex items-center justify-between">
                <p className="text-xs text-slate-500">By applying you agree to our recruiting privacy notice.</p>
                <Button type="submit" disabled={busy} className="bg-slate-900 hover:bg-slate-800 text-white rounded-lg h-11 px-6" data-testid="apply-submit">
                  {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : "Submit application"}
                </Button>
              </div>
            </form>
          </>
        )}
      </div>
    </div>
  );
}
