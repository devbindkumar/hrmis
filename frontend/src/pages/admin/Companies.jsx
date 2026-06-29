import { useEffect, useRef, useState } from "react";
import api, { formatApiError, getToken } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Plus, Building2, Users2, Clock, Loader2, Pencil, Image as ImageIcon, X } from "lucide-react";
import { toast } from "sonner";
import StatusPill from "@/components/StatusPill";
import { useAuth } from "@/contexts/AuthContext";

const PRESET_COLORS = ["#0f172a", "#2563eb", "#0ea5e9", "#10b981", "#a855f7", "#ec4899", "#f59e0b", "#ef4444"];

const logoUrl = (companyId, bust) => `${process.env.REACT_APP_BACKEND_URL}/api/companies/${companyId}/logo${bust ? `?v=${bust}` : ""}`;

export default function Companies() {
  const { user } = useAuth();
  const [list, setList] = useState([]);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);

  const load = () => api.get("/companies").then((r) => setList(r.data));
  useEffect(() => { load(); }, []);

  return (
    <div className="p-6 space-y-5 animate-fade-up" data-testid="admin-companies">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="font-display text-3xl font-semibold tracking-tight text-slate-900">Companies</h1>
          <p className="text-sm text-slate-500 mt-1">
            {user?.role === "super_admin"
              ? "Onboard new companies. Each one gets isolated data, employees, and an initial admin."
              : "Your company and its policy."}
          </p>
        </div>
        {user?.role === "super_admin" && (
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
              <Button className="bg-slate-900 hover:bg-slate-800 text-white rounded-lg" data-testid="new-company-btn">
                <Plus className="h-4 w-4 mr-1.5" strokeWidth={1.5} /> Onboard a company
              </Button>
            </DialogTrigger>
            <NewCompanyDialog onCreated={() => { setOpen(false); load(); }} />
          </Dialog>
        )}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {list.length === 0 ? (
          <div className="surface p-12 text-center text-slate-400 col-span-full">No companies yet.</div>
        ) : list.map((c) => (
          <div key={c.id} className="surface p-5 card-hover" data-testid={`company-card-${c.id}`}>
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0 flex items-center gap-3">
                <div className="h-12 w-12 rounded-lg grid place-items-center overflow-hidden border border-slate-200" style={{ background: c.accent_color || "#0f172a" }}>
                  {c.has_logo ? (
                    <img src={logoUrl(c.id, c.created_at)} alt={c.name} className="h-full w-full object-cover" data-testid={`company-logo-${c.id}`} />
                  ) : (
                    <Building2 className="h-5 w-5 text-white" strokeWidth={1.5} />
                  )}
                </div>
                <div className="min-w-0">
                  <h3 className="font-display text-lg font-medium text-slate-900 truncate">{c.name}</h3>
                  <div className="text-xs text-slate-500 truncate font-mono">/{c.slug}</div>
                </div>
              </div>
              <StatusPill status={c.status === "active" ? "active" : "absent"} label={c.status === "active" ? "Active" : c.status} />
            </div>
            <div className="grid grid-cols-2 gap-3 mt-5 text-sm">
              <div className="rounded-lg border border-slate-100 p-3">
                <div className="text-[10px] uppercase tracking-widest font-semibold text-slate-400 flex items-center gap-1">
                  <Users2 className="h-3 w-3" strokeWidth={1.5} /> Employees
                </div>
                <div className="font-display text-xl font-semibold text-slate-900 mt-1">{c.employee_count ?? 0}</div>
              </div>
              <div className="rounded-lg border border-slate-100 p-3">
                <div className="text-[10px] uppercase tracking-widest font-semibold text-slate-400 flex items-center gap-1">
                  <Clock className="h-3 w-3" strokeWidth={1.5} /> Escalation
                </div>
                <div className="font-display text-xl font-semibold text-slate-900 mt-1">{c.escalation_hours}h</div>
              </div>
            </div>
            <div className="flex items-center justify-between mt-4 pt-3 border-t border-slate-100">
              <div className="text-xs text-slate-400">Created {new Date(c.created_at).toLocaleDateString()}</div>
              {(user?.role === "super_admin" || user?.company_id === c.id) && (
                <button onClick={()=>setEditing(c)} className="text-xs font-medium text-blue-600 hover:underline inline-flex items-center gap-1" data-testid={`edit-company-${c.id}`}>
                  <Pencil className="h-3 w-3" /> Edit policy
                </button>
              )}
            </div>
          </div>
        ))}
      </div>

      <Dialog open={!!editing} onOpenChange={(o)=>{ if(!o) setEditing(null); }}>
        {editing && (
          <EditCompanyDialog
            company={editing}
            canRename={user?.role === "super_admin"}
            onSaved={() => { setEditing(null); load(); }}
          />
        )}
      </Dialog>
    </div>
  );
}

function NewCompanyDialog({ onCreated }) {
  const [form, setForm] = useState({
    name: "", slug: "", escalation_hours: 48, accent_color: "#0f172a",
    admin_email: "", admin_name: "", admin_password: "Admin@123",
  });
  const [busy, setBusy] = useState(false);

  const onNameChange = (v) => {
    const slug = v.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
    setForm({ ...form, name: v, slug: form.slug || slug });
  };

  const submit = async () => {
    if (!form.name || !form.slug || !form.admin_email || !form.admin_name) {
      toast.error("Name, slug, admin email and admin name are required"); return;
    }
    setBusy(true);
    try {
      await api.post("/companies", form);
      toast.success(`${form.name} onboarded. Admin can sign in now.`);
      onCreated();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };

  return (
    <DialogContent className="rounded-2xl max-w-xl" data-testid="new-company-dialog">
      <DialogHeader>
        <DialogTitle className="font-display">Onboard a new company</DialogTitle>
      </DialogHeader>
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label>Company name *</Label>
            <Input value={form.name} onChange={(e)=>onNameChange(e.target.value)} className="mt-1.5" data-testid="nc-name" />
          </div>
          <div>
            <Label>URL slug *</Label>
            <Input value={form.slug} onChange={(e)=>setForm({...form, slug: e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, "")})} placeholder="imd" className="mt-1.5 font-mono" data-testid="nc-slug" />
            <p className="text-[10px] text-slate-400 mt-1">Used for the careers page: /careers?company=slug</p>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label>Escalation policy (hours)</Label>
            <Input type="number" min="1" value={form.escalation_hours} onChange={(e)=>setForm({...form, escalation_hours: parseInt(e.target.value) || 1})} className="mt-1.5" data-testid="nc-escalation" />
          </div>
          <div>
            <Label>Accent color</Label>
            <ColorPicker value={form.accent_color} onChange={(c)=>setForm({...form, accent_color: c})} />
          </div>
        </div>
        <p className="text-[10px] text-slate-400 -mt-1">You can upload a logo from the edit dialog after the company is created.</p>
        <div className="border-t border-slate-100 pt-3">
          <div className="text-xs uppercase tracking-widest font-semibold text-slate-500 mb-2">Initial admin user</div>
          <div className="grid grid-cols-2 gap-3">
            <div><Label>Admin name *</Label><Input value={form.admin_name} onChange={(e)=>setForm({...form, admin_name: e.target.value})} className="mt-1.5" data-testid="nc-admin-name" /></div>
            <div><Label>Admin email *</Label><Input type="email" value={form.admin_email} onChange={(e)=>setForm({...form, admin_email: e.target.value})} className="mt-1.5" data-testid="nc-admin-email" /></div>
            <div className="col-span-2"><Label>Temporary password</Label><Input value={form.admin_password} onChange={(e)=>setForm({...form, admin_password: e.target.value})} className="mt-1.5" /></div>
          </div>
        </div>
      </div>
      <DialogFooter>
        <Button onClick={submit} disabled={busy} className="bg-slate-900 hover:bg-slate-800 text-white" data-testid="nc-submit">
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : "Create company"}
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}

function ColorPicker({ value, onChange }) {
  return (
    <div className="mt-1.5 flex items-center gap-2">
      <input
        type="color"
        value={value}
        onChange={(e)=>onChange(e.target.value)}
        className="h-10 w-12 rounded-lg border border-slate-200 cursor-pointer"
        data-testid="color-picker"
      />
      <Input value={value} onChange={(e)=>onChange(e.target.value)} className="font-mono h-10 rounded-lg" />
      <div className="flex flex-wrap gap-1">
        {PRESET_COLORS.map((c) => (
          <button
            key={c}
            type="button"
            onClick={()=>onChange(c)}
            className={`h-6 w-6 rounded-md border ${value === c ? "ring-2 ring-offset-1 ring-slate-900" : "border-slate-200"}`}
            style={{ background: c }}
            aria-label={c}
            data-testid={`preset-${c.replace('#', '')}`}
          />
        ))}
      </div>
    </div>
  );
}


function EditCompanyDialog({ company, canRename, onSaved }) {
  const [form, setForm] = useState({
    name: company.name,
    escalation_hours: company.escalation_hours,
    accent_color: company.accent_color || "#0f172a",
    status: company.status || "active",
  });
  const [busy, setBusy] = useState(false);
  const [uploadingLogo, setUploadingLogo] = useState(false);
  const [bust, setBust] = useState(0);
  const fileRef = useRef();

  const submit = async () => {
    setBusy(true);
    try {
      const payload = {
        escalation_hours: form.escalation_hours,
        accent_color: form.accent_color,
      };
      if (canRename) {
        payload.name = form.name;
        payload.status = form.status;
      }
      await api.patch(`/companies/${company.id}`, payload);
      toast.success("Saved");
      onSaved();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };

  const handleLogo = async (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    setUploadingLogo(true);
    try {
      const data = new FormData();
      data.append("file", f);
      const res = await fetch(`${process.env.REACT_APP_BACKEND_URL}/api/companies/${company.id}/logo`, {
        method: "POST",
        headers: { Authorization: `Bearer ${getToken()}` },
        body: data,
      });
      if (!res.ok) throw new Error("upload failed");
      setBust(Date.now());
      toast.success("Logo uploaded");
    } catch {
      toast.error("Couldn't upload logo");
    } finally {
      setUploadingLogo(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  return (
    <DialogContent className="rounded-2xl max-w-lg" data-testid="edit-company-dialog">
      <DialogHeader>
        <DialogTitle className="font-display">Edit · {company.name}</DialogTitle>
      </DialogHeader>
      <div className="space-y-4">
        <div>
          <Label>Logo</Label>
          <div className="mt-1.5 flex items-center gap-3">
            <div className="h-16 w-16 rounded-xl border border-slate-200 grid place-items-center overflow-hidden" style={{ background: form.accent_color }}>
              {company.has_logo || bust ? (
                <img
                  src={logoUrl(company.id, bust || company.created_at)}
                  alt={company.name}
                  className="h-full w-full object-cover"
                />
              ) : (
                <Building2 className="h-6 w-6 text-white" strokeWidth={1.5} />
              )}
            </div>
            <div className="flex-1">
              <label className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-slate-200 hover:bg-slate-50 cursor-pointer text-sm">
                {uploadingLogo ? <Loader2 className="h-4 w-4 animate-spin" /> : <ImageIcon className="h-4 w-4" strokeWidth={1.5} />}
                <span>{uploadingLogo ? "Uploading…" : (company.has_logo ? "Replace logo" : "Upload logo")}</span>
                <input ref={fileRef} type="file" className="hidden" accept="image/png,image/jpeg,image/webp,image/svg+xml" onChange={handleLogo} data-testid="logo-upload" />
              </label>
              <p className="text-[10px] text-slate-400 mt-1">PNG, JPG, WEBP, or SVG · max 2 MB</p>
            </div>
          </div>
        </div>
        {canRename && (
          <div>
            <Label>Company name</Label>
            <Input value={form.name} onChange={(e)=>setForm({...form, name: e.target.value})} className="mt-1.5" data-testid="ec-name" />
          </div>
        )}
        <div>
          <Label>Accent color</Label>
          <ColorPicker value={form.accent_color} onChange={(c)=>setForm({...form, accent_color: c})} />
          <p className="text-xs text-slate-500 mt-1">Applied to the sidebar logo tile, active nav, and key highlights.</p>
        </div>
        <div>
          <Label>Escalation policy (hours)</Label>
          <Input type="number" min="1" value={form.escalation_hours} onChange={(e)=>setForm({...form, escalation_hours: parseInt(e.target.value) || 1})} className="mt-1.5" data-testid="ec-escalation" />
        </div>
        {canRename && (
          <div>
            <Label>Status</Label>
            <select value={form.status} onChange={(e)=>setForm({...form, status: e.target.value})} className="mt-1.5 w-full h-10 rounded-lg border border-slate-200 px-3 text-sm">
              <option value="active">Active</option>
              <option value="suspended">Suspended</option>
            </select>
          </div>
        )}
      </div>
      <DialogFooter>
        <Button onClick={submit} disabled={busy} className="bg-slate-900 hover:bg-slate-800 text-white" data-testid="ec-save">
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : "Save"}
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}

