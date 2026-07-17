import { useEffect, useState } from "react";
import api, { formatApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import { Building2, Plus, Trash2, Settings as SettingsIcon, Camera, Clock, ShieldCheck, RefreshCw, Copy, ExternalLink } from "lucide-react";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";
import { useAuth } from "@/contexts/AuthContext";
import LeaveTypesPanel from "@/pages/admin/LeaveTypesPanel";
import MeetingRoomsPanel from "@/pages/admin/MeetingRoomsPanel";

export default function AdminSettings() {
  const [departments, setDepartments] = useState([]);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ name: "", head: "" });

  const load = () => api.get("/departments").then((r) => setDepartments(r.data));
  useEffect(() => { load(); }, []);

  const add = async () => {
    if (!form.name) return;
    try {
      await api.post("/departments", form);
      toast.success("Department added");
      setForm({ name: "", head: "" });
      setOpen(false);
      load();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  const remove = async (id) => {
    if (!window.confirm("Delete this department? Existing employees will not be removed.")) return;
    await api.delete(`/departments/${id}`);
    toast.success("Department removed");
    load();
  };

  return (
    <div className="p-6 space-y-6 animate-fade-up" data-testid="admin-settings">
      <div>
        <h1 className="font-display text-3xl font-semibold tracking-tight text-slate-900">Settings</h1>
        <p className="text-sm text-slate-500 mt-1">Departments and leave policies.</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="surface p-6">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Building2 className="h-4 w-4 text-slate-500" strokeWidth={1.5} />
              <h3 className="font-display text-lg font-medium text-slate-900">Departments</h3>
            </div>
            <Dialog open={open} onOpenChange={setOpen}>
              <DialogTrigger asChild>
                <Button variant="outline" size="sm" className="rounded-lg" data-testid="add-dept-btn"><Plus className="h-3.5 w-3.5 mr-1" /> Add</Button>
              </DialogTrigger>
              <DialogContent className="rounded-2xl">
                <DialogHeader><DialogTitle className="font-display">New department</DialogTitle></DialogHeader>
                <div className="space-y-3">
                  <div><Label>Name</Label><Input value={form.name} onChange={(e)=>setForm({...form, name: e.target.value})} className="mt-1.5" data-testid="dept-name" /></div>
                  <div><Label>Head (optional)</Label><Input value={form.head} onChange={(e)=>setForm({...form, head: e.target.value})} className="mt-1.5" /></div>
                </div>
                <DialogFooter><Button onClick={add} className="bg-slate-900 hover:bg-slate-800 text-white" data-testid="dept-submit">Create</Button></DialogFooter>
              </DialogContent>
            </Dialog>
          </div>
          <div className="mt-4 divide-y divide-slate-100">
            {departments.map((d) => (
              <div key={d.id} className="flex items-center justify-between py-3">
                <div>
                  <div className="text-sm font-medium text-slate-900">{d.name}</div>
                  <div className="text-xs text-slate-500">{d.head || 'No head'} · {d.headcount} {d.headcount === 1 ? 'person' : 'people'}</div>
                </div>
                <button onClick={()=>remove(d.id)} className="text-slate-400 hover:text-rose-600" data-testid={`del-dept-${d.id}`}>
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            ))}
          </div>
        </div>

        <div className="surface p-6">
          <div className="flex items-center gap-2">
            <SettingsIcon className="h-4 w-4 text-slate-500" strokeWidth={1.5} />
            <h3 className="font-display text-lg font-medium text-slate-900">Leave policy (default)</h3>
          </div>
          <p className="text-xs text-slate-500 mt-1">These annual quotas are applied to every new employee on creation.</p>
          <div className="mt-4 grid grid-cols-2 gap-3">
            <PolicyCard type="Casual" days={12} />
            <PolicyCard type="Sick" days={8} />
            <PolicyCard type="Earned" days={15} />
            <PolicyCard type="WFH Quota" days={60} />
          </div>
        </div>
      </div>

      <LeaveTypesPanel />

      <MeetingRoomsPanel />

      <ShiftAndKioskPanel />
    </div>
  );
}

function ShiftAndKioskPanel() {
  const { user } = useAuth();
  const [company, setCompany] = useState(null);
  const [kiosk, setKiosk] = useState(null);
  const [saving, setSaving] = useState(false);
  const [rotating, setRotating] = useState(false);
  const isSuperAdmin = user?.role === "super_admin";

  const load = async () => {
    try {
      const c = await api.get("/companies/mine");
      setCompany(c.data);
      if (isSuperAdmin) {
        const k = await api.get(`/companies/${c.data.id}/kiosk-token`);
        setKiosk(k.data);
      }
    } catch (e) { /* ignore */ }
  };
  useEffect(() => { load(); }, []);

  if (!company) return null;

  const kioskUrl = kiosk?.kiosk_token
    ? `${window.location.origin}/kiosk/scan?token=${kiosk.kiosk_token}`
    : null;

  const saveShift = async () => {
    setSaving(true);
    try {
      await api.patch(`/companies/${company.id}`, {
        shift_start_time: company.shift_start_time || "09:30",
        late_grace_minutes: Number.isFinite(+company.late_grace_minutes) ? +company.late_grace_minutes : 15,
      });
      toast.success("Shift settings saved");
      load();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setSaving(false); }
  };

  const toggleKiosk = async (v) => {
    try {
      await api.patch(`/companies/${company.id}`, { kiosk_enabled: v });
      toast.success(v ? "Kiosk enabled" : "Kiosk disabled");
      load();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  const rotateToken = async () => {
    if (kiosk?.kiosk_token && !window.confirm("Rotate the kiosk token? Any device holding the old URL will stop working.")) return;
    setRotating(true);
    try {
      const { data } = await api.post(`/companies/${company.id}/kiosk-token/rotate`);
      setKiosk((k) => ({ ...(k || {}), kiosk_token: data.kiosk_token, kiosk_enabled: true, has_token: true }));
      toast.success("New kiosk URL generated");
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setRotating(false); }
  };

  return (
    <>
      {/* Shift + late detection */}
      <div className="surface p-6" data-testid="shift-panel">
        <div className="flex items-center gap-2">
          <Clock className="h-4 w-4 text-slate-500" strokeWidth={1.5} />
          <h3 className="font-display text-lg font-medium text-slate-900">Shift & late-coming policy</h3>
        </div>
        <p className="text-xs text-slate-500 mt-1">
          Company defaults. Departments and individual employees can override these values.
          Times are interpreted in the tenant timezone configured under WhatsApp Integration.
        </p>
        <div className="mt-4 grid grid-cols-1 md:grid-cols-3 gap-4">
          <div>
            <Label>Shift starts at</Label>
            <Input
              type="time"
              className="mt-1.5 font-mono"
              value={company.shift_start_time || "09:30"}
              onChange={(e) => setCompany({ ...company, shift_start_time: e.target.value })}
              data-testid="shift-start-input"
            />
          </div>
          <div>
            <Label>Grace period (minutes)</Label>
            <Input
              type="number" min="0" max="240"
              className="mt-1.5"
              value={company.late_grace_minutes ?? 15}
              onChange={(e) => setCompany({ ...company, late_grace_minutes: e.target.value })}
              data-testid="shift-grace-input"
            />
            <p className="text-[11px] text-slate-400 mt-1">A check-in after start + grace is flagged as late.</p>
          </div>
          <div className="flex items-end">
            <Button onClick={saveShift} disabled={saving} className="w-full bg-slate-900 hover:bg-slate-800 text-white" data-testid="shift-save">
              {saving ? "Saving…" : "Save shift settings"}
            </Button>
          </div>
        </div>
      </div>

      {/* Kiosk */}
      {isSuperAdmin && (
        <div className="surface p-6" data-testid="kiosk-panel">
          <div className="flex items-start justify-between gap-3 flex-wrap">
            <div>
              <div className="flex items-center gap-2">
                <Camera className="h-4 w-4 text-slate-500" strokeWidth={1.5} />
                <h3 className="font-display text-lg font-medium text-slate-900">Face-recognition attendance kiosk</h3>
              </div>
              <p className="text-xs text-slate-500 mt-1">
                Open the kiosk URL on a device pointed at your entrance. Employees are recognised by face and can tap Check in / Check out.
                Anti-spoof + liveness are enforced in-browser and re-validated server-side.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <Label htmlFor="kiosk-enabled" className="text-sm">Enabled</Label>
              <Switch
                id="kiosk-enabled"
                checked={!!kiosk?.kiosk_enabled}
                onCheckedChange={toggleKiosk}
                data-testid="kiosk-enabled-switch"
              />
            </div>
          </div>

          <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50/50 p-4">
            <div className="flex items-center justify-between gap-3 flex-wrap">
              <div className="min-w-0 flex-1">
                <div className="text-[10px] uppercase tracking-widest text-slate-500 font-semibold">Kiosk URL</div>
                <div className="mt-1 font-mono text-xs text-slate-800 break-all" data-testid="kiosk-url">
                  {kioskUrl || "— rotate to generate —"}
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                {kioskUrl && (
                  <>
                    <Button size="sm" variant="outline" onClick={() => { navigator.clipboard.writeText(kioskUrl); toast.success("Copied"); }} data-testid="kiosk-copy">
                      <Copy className="h-3.5 w-3.5 mr-1" /> Copy
                    </Button>
                    <a href={kioskUrl} target="_blank" rel="noreferrer">
                      <Button size="sm" variant="outline" data-testid="kiosk-open">
                        <ExternalLink className="h-3.5 w-3.5 mr-1" /> Open
                      </Button>
                    </a>
                  </>
                )}
                <Button size="sm" onClick={rotateToken} disabled={rotating} className="bg-indigo-600 hover:bg-indigo-700 text-white" data-testid="kiosk-rotate">
                  <RefreshCw className={`h-3.5 w-3.5 mr-1 ${rotating ? "animate-spin" : ""}`} />
                  {kiosk?.kiosk_token ? "Rotate" : "Generate"}
                </Button>
              </div>
            </div>
          </div>

          <div className="mt-3 flex items-start gap-2 text-[11px] text-slate-500">
            <ShieldCheck className="h-4 w-4 text-emerald-600 shrink-0 mt-0.5" />
            <div>
              Anti-spoof + liveness threshold: <b>≥ 60%</b> both. Face embeddings never leave the browser
              during scan (only the 128-float vector is posted). Enroll employees from{" "}
              <b>Employees → Edit → Face-recognition enrollment</b>.
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function PolicyCard({ type, days }) {
  return (
    <div className="rounded-lg border border-slate-100 p-4">
      <div className="text-xs uppercase tracking-widest text-slate-400 font-semibold">{type}</div>
      <div className="font-display text-2xl font-semibold text-slate-900 mt-1">{days}<span className="text-sm text-slate-400 ml-1 font-normal">days / year</span></div>
    </div>
  );
}
