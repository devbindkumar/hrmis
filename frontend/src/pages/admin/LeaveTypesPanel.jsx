import { useEffect, useState } from "react";
import api, { formatApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Plus, Trash2, Loader2, CheckCircle2, XCircle, Pencil } from "lucide-react";
import { toast } from "sonner";

export default function LeaveTypesPanel() {
  const [types, setTypes] = useState([]);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);

  const load = () => api.get("/leave-types").then((r) => setTypes(r.data));
  useEffect(() => { load(); }, []);

  const remove = async (t) => {
    if (!window.confirm(`Delete leave type "${t.name}"? Existing balances will be removed if unused.`)) return;
    try {
      await api.delete(`/leave-types/${t.id}`);
      toast.success("Removed");
      load();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  return (
    <div className="surface p-6" data-testid="leave-types-panel">
      <div className="flex items-center justify-between mb-1">
        <div>
          <h3 className="font-display text-lg font-medium text-slate-900">Leave types</h3>
          <p className="text-xs text-slate-500 mt-0.5">Unpaid types count as Loss-of-Pay during payroll runs.</p>
        </div>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button variant="outline" size="sm" className="rounded-lg" data-testid="add-leave-type-btn">
              <Plus className="h-3.5 w-3.5 mr-1" /> Add type
            </Button>
          </DialogTrigger>
          <EditLeaveTypeDialog onSaved={() => { setOpen(false); load(); }} />
        </Dialog>
      </div>
      <div className="mt-4 divide-y divide-slate-100">
        {types.length === 0 ? (
          <div className="text-sm text-slate-400 py-6 text-center">No leave types configured.</div>
        ) : types.map((t) => (
          <div key={t.id} className="flex items-center justify-between py-3 gap-3" data-testid={`leave-type-${t.id}`}>
            <div className="flex items-center gap-3 min-w-0 flex-1">
              <div className={`h-8 w-8 rounded-lg grid place-items-center shrink-0 ${t.is_paid ? "bg-emerald-50 text-emerald-700 border border-emerald-100" : "bg-rose-50 text-rose-700 border border-rose-100"}`}>
                {t.is_paid ? <CheckCircle2 className="h-4 w-4" strokeWidth={1.5} /> : <XCircle className="h-4 w-4" strokeWidth={1.5} />}
              </div>
              <div className="min-w-0">
                <div className="text-sm font-medium text-slate-900 truncate">{t.name}</div>
                <div className="text-xs text-slate-500">
                  Default quota: <b>{t.default_quota}</b> days/year ·&nbsp;
                  <span className={t.is_paid ? "text-emerald-700" : "text-rose-700"}>{t.is_paid ? "Paid leave" : "Unpaid (counts as LOP)"}</span>
                </div>
              </div>
            </div>
            <div className="flex items-center gap-1 shrink-0">
              <button onClick={()=>setEditing(t)} className="text-slate-400 hover:text-slate-900 p-1.5 rounded-md hover:bg-slate-50" data-testid={`edit-leave-type-${t.id}`}>
                <Pencil className="h-4 w-4" strokeWidth={1.5} />
              </button>
              <button onClick={()=>remove(t)} className="text-slate-400 hover:text-rose-600 p-1.5 rounded-md hover:bg-slate-50" data-testid={`del-leave-type-${t.id}`}>
                <Trash2 className="h-4 w-4" strokeWidth={1.5} />
              </button>
            </div>
          </div>
        ))}
      </div>
      <Dialog open={!!editing} onOpenChange={(o)=>{ if(!o) setEditing(null); }}>
        {editing && <EditLeaveTypeDialog type={editing} onSaved={() => { setEditing(null); load(); }} />}
      </Dialog>
    </div>
  );
}

function EditLeaveTypeDialog({ type, onSaved }) {
  const isEdit = !!type;
  const [form, setForm] = useState({
    name: type?.name || "",
    default_quota: type?.default_quota ?? 12,
    is_paid: type?.is_paid ?? true,
  });
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!form.name || form.name.length < 2) { toast.error("Name is required"); return; }
    setBusy(true);
    try {
      if (isEdit) {
        await api.patch(`/leave-types/${type.id}`, form);
        toast.success("Saved");
      } else {
        await api.post(`/leave-types`, form);
        toast.success("Added");
      }
      onSaved();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };

  return (
    <DialogContent className="rounded-2xl" data-testid="leave-type-dialog">
      <DialogHeader>
        <DialogTitle className="font-display">{isEdit ? `Edit · ${type.name}` : "New leave type"}</DialogTitle>
      </DialogHeader>
      <div className="space-y-3">
        <div>
          <Label>Name</Label>
          <Input value={form.name} onChange={(e)=>setForm({...form, name: e.target.value})} className="mt-1.5" data-testid="lt-name" placeholder="e.g. Sabbatical, Bereavement, Unpaid Leave" />
        </div>
        <div>
          <Label>Default quota (days / year)</Label>
          <Input type="number" min="0" step="0.5" value={form.default_quota} onChange={(e)=>setForm({...form, default_quota: parseFloat(e.target.value) || 0})} className="mt-1.5" data-testid="lt-quota" />
          <p className="text-xs text-slate-500 mt-1">New employees are seeded with this many days. Unlimited? Use a large number.</p>
        </div>
        <div className="flex items-center gap-3 p-3 rounded-lg bg-slate-50 border border-slate-100">
          <Switch checked={form.is_paid} onCheckedChange={(v)=>setForm({...form, is_paid: v})} data-testid="lt-paid" />
          <div className="text-sm">
            <div className="font-medium text-slate-900">{form.is_paid ? "Paid leave" : "Unpaid (LOP)"}</div>
            <div className="text-xs text-slate-500">{form.is_paid ? "Employee is paid as if working." : "Days off under this type reduce the payslip via Loss-of-Pay deduction during payroll."}</div>
          </div>
        </div>
      </div>
      <DialogFooter>
        <Button onClick={submit} disabled={busy} className="bg-slate-900 hover:bg-slate-800 text-white" data-testid="lt-submit">
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : (isEdit ? "Save" : "Create")}
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}
