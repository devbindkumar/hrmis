import { useEffect, useState } from "react";
import api, { formatApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Plus, Loader2 } from "lucide-react";
import { toast } from "sonner";
import StatusPill from "@/components/StatusPill";

export default function MyWFH() {
  const [mine, setMine] = useState([]);
  const [today, setToday] = useState([]);
  const [open, setOpen] = useState(false);

  const load = async () => {
    const [a, b] = await Promise.all([api.get("/wfh/mine"), api.get("/wfh/today")]);
    setMine(a.data); setToday(b.data);
  };
  useEffect(() => { load(); }, []);

  return (
    <div className="space-y-6 animate-fade-up" data-testid="my-wfh">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="font-display text-3xl font-semibold tracking-tight text-slate-900">Work from home</h1>
          <p className="text-sm text-slate-500 mt-1">Request remote days and see your history.</p>
        </div>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button className="bg-slate-900 hover:bg-slate-800 text-white rounded-lg" data-testid="apply-wfh-btn"><Plus className="h-4 w-4 mr-1.5" /> Apply for WFH</Button>
          </DialogTrigger>
          <ApplyDialog onCreated={() => { setOpen(false); load(); }} />
        </Dialog>
      </div>

      <div className="surface p-6" data-testid="wfh-today">
        <div className="text-xs uppercase tracking-widest text-slate-400 font-semibold">Remote today</div>
        <div className="mt-3 flex flex-wrap gap-2">
          {today.length === 0 ? <div className="text-sm text-slate-400">Nobody is WFH today.</div> :
            today.map((t) => <div key={t.id} className="px-3 py-1.5 rounded-full bg-blue-50 border border-blue-200 text-blue-700 text-xs font-medium">{t.user_name}</div>)}
        </div>
      </div>

      <div className="surface overflow-hidden">
        <div className="px-5 py-3 border-b border-slate-100"><h3 className="font-display text-base font-medium text-slate-900">Your requests</h3></div>
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-slate-50 text-slate-500 text-xs uppercase tracking-wide">
              <th className="text-left font-semibold px-5 py-3">Date</th>
              <th className="text-left font-semibold px-5 py-3">Reason</th>
              <th className="text-left font-semibold px-5 py-3">Status</th>
            </tr>
          </thead>
          <tbody>
            {mine.length === 0 ? <tr><td colSpan="3" className="px-5 py-10 text-center text-slate-400">No WFH requests yet.</td></tr> :
              mine.map((r) => (
                <tr key={r.id} className="border-t border-slate-100 hover:bg-slate-50/60">
                  <td className="px-5 py-3 font-medium text-slate-900">{r.date}</td>
                  <td className="px-5 py-3 text-slate-600 max-w-md truncate">{r.reason}</td>
                  <td className="px-5 py-3"><StatusPill status={r.status} /></td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ApplyDialog({ onCreated }) {
  const [form, setForm] = useState({ date: "", reason: "" });
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    if (!form.date || !form.reason) { toast.error("Fill all fields"); return; }
    setBusy(true);
    try {
      await api.post("/wfh/apply", form);
      toast.success("WFH request submitted");
      onCreated();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };
  return (
    <DialogContent className="rounded-2xl">
      <DialogHeader><DialogTitle className="font-display">Apply for work from home</DialogTitle></DialogHeader>
      <div className="space-y-3">
        <div><Label>Date</Label><Input type="date" value={form.date} onChange={(e)=>setForm({...form, date: e.target.value})} className="mt-1.5" data-testid="wfh-date" /></div>
        <div><Label>Reason</Label><Textarea value={form.reason} onChange={(e)=>setForm({...form, reason: e.target.value})} className="mt-1.5" data-testid="wfh-reason" /></div>
      </div>
      <DialogFooter><Button onClick={submit} disabled={busy} className="bg-slate-900 hover:bg-slate-800 text-white" data-testid="wfh-submit">{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : "Submit"}</Button></DialogFooter>
    </DialogContent>
  );
}
