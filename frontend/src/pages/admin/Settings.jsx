import { useEffect, useState } from "react";
import api, { formatApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import { Building2, Plus, Trash2, Settings as SettingsIcon } from "lucide-react";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import LeaveTypesPanel from "@/pages/admin/LeaveTypesPanel";

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
    </div>
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
