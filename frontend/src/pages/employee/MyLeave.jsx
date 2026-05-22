import { useEffect, useState } from "react";
import api, { formatApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Plus, Loader2 } from "lucide-react";
import { toast } from "sonner";
import StatusPill from "@/components/StatusPill";

export default function MyLeave() {
  const [balances, setBalances] = useState([]);
  const [mine, setMine] = useState([]);
  const [open, setOpen] = useState(false);

  const load = async () => {
    const [a, b] = await Promise.all([api.get("/leave/balances"), api.get("/leave/mine")]);
    setBalances(a.data); setMine(b.data);
  };
  useEffect(() => { load(); }, []);

  return (
    <div className="space-y-6 animate-fade-up" data-testid="my-leave">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="font-display text-3xl font-semibold tracking-tight text-slate-900">Leave</h1>
          <p className="text-sm text-slate-500 mt-1">Balances, history and new requests.</p>
        </div>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button className="bg-slate-900 hover:bg-slate-800 text-white rounded-lg" data-testid="apply-leave-btn"><Plus className="h-4 w-4 mr-1.5" /> Apply for leave</Button>
          </DialogTrigger>
          <ApplyDialog balances={balances} onCreated={() => { setOpen(false); load(); }} />
        </Dialog>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {balances.map((b) => {
          const rem = b.total - b.used;
          const pct = b.total ? (rem / b.total) * 100 : 0;
          return (
            <div key={b.id} className="surface p-5">
              <div className="text-xs uppercase tracking-widest text-slate-400 font-semibold">{b.leave_type}</div>
              <div className="font-display text-3xl font-semibold text-slate-900 mt-2">{rem}<span className="text-sm text-slate-400 ml-1 font-normal">/ {b.total}</span></div>
              <div className="h-1.5 rounded-full bg-slate-100 mt-3 overflow-hidden">
                <div className="h-full rounded-full bg-slate-900" style={{ width: `${pct}%` }} />
              </div>
            </div>
          );
        })}
      </div>

      <div className="surface overflow-hidden">
        <div className="px-5 py-3 border-b border-slate-100"><h3 className="font-display text-base font-medium text-slate-900">Your requests</h3></div>
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-slate-50 text-slate-500 text-xs uppercase tracking-wide">
              <th className="text-left font-semibold px-5 py-3">Type</th>
              <th className="text-left font-semibold px-5 py-3">Range</th>
              <th className="text-left font-semibold px-5 py-3">Days</th>
              <th className="text-left font-semibold px-5 py-3">Reason</th>
              <th className="text-left font-semibold px-5 py-3">Status</th>
              <th className="text-left font-semibold px-5 py-3">Decision</th>
            </tr>
          </thead>
          <tbody>
            {mine.length === 0 ? <tr><td colSpan="6" className="px-5 py-10 text-center text-slate-400">No leave requests yet.</td></tr> :
              mine.map((r) => (
                <tr key={r.id} className="border-t border-slate-100 hover:bg-slate-50/60 align-top">
                  <td className="px-5 py-3 font-medium text-slate-900">{r.leave_type}</td>
                  <td className="px-5 py-3 text-slate-700">{r.start_date} → {r.end_date}</td>
                  <td className="px-5 py-3 text-slate-700">{r.days}</td>
                  <td className="px-5 py-3 text-slate-600 max-w-xs truncate" title={r.reason}>{r.reason}</td>
                  <td className="px-5 py-3"><StatusPill status={r.status} /></td>
                  <td className="px-5 py-3 max-w-sm">
                    {r.status === "pending" ? (
                      <span className="text-xs text-slate-400">{r.manager_name ? `Awaiting ${r.manager_name}` : "Awaiting HR"}</span>
                    ) : (
                      <div>
                        <div className="text-xs text-slate-500">by <b className="text-slate-700">{r.decided_by || "HR"}</b>{r.decided_at && <span className="text-slate-400"> · {new Date(r.decided_at).toLocaleDateString()}</span>}</div>
                        {r.decision_note ? <div className="text-xs text-slate-700 mt-1 italic">"{r.decision_note}"</div> : null}
                      </div>
                    )}
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ApplyDialog({ balances, onCreated }) {
  const [form, setForm] = useState({ leave_type: balances[0]?.leave_type || "Casual", start_date: "", end_date: "", reason: "" });
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    if (!form.start_date || !form.end_date || !form.reason) { toast.error("Please fill all fields"); return; }
    setBusy(true);
    try {
      await api.post("/leave/apply", form);
      toast.success("Leave request submitted");
      onCreated();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };
  return (
    <DialogContent className="rounded-2xl">
      <DialogHeader><DialogTitle className="font-display">Apply for leave</DialogTitle></DialogHeader>
      <div className="grid grid-cols-2 gap-3">
        <div className="col-span-2">
          <Label>Leave type</Label>
          <Select value={form.leave_type} onValueChange={(v)=>setForm({...form, leave_type: v})}>
            <SelectTrigger className="mt-1.5" data-testid="leave-type"><SelectValue /></SelectTrigger>
            <SelectContent>
              {balances.map((b)=> <SelectItem key={b.id} value={b.leave_type}>{b.leave_type} ({b.total - b.used} left)</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <div><Label>Start</Label><Input type="date" value={form.start_date} onChange={(e)=>setForm({...form, start_date: e.target.value})} className="mt-1.5" data-testid="leave-start" /></div>
        <div><Label>End</Label><Input type="date" value={form.end_date} onChange={(e)=>setForm({...form, end_date: e.target.value})} className="mt-1.5" data-testid="leave-end" /></div>
        <div className="col-span-2"><Label>Reason</Label><Textarea value={form.reason} onChange={(e)=>setForm({...form, reason: e.target.value})} className="mt-1.5" data-testid="leave-reason" /></div>
      </div>
      <DialogFooter><Button onClick={submit} disabled={busy} className="bg-slate-900 hover:bg-slate-800 text-white" data-testid="leave-submit">{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : "Submit"}</Button></DialogFooter>
    </DialogContent>
  );
}
