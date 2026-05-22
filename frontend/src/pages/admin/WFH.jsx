import { useEffect, useState } from "react";
import api, { formatApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import StatusPill from "@/components/StatusPill";
import { Check, X, Loader2, House, Users } from "lucide-react";
import { toast } from "sonner";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/contexts/AuthContext";

export default function AdminWFH() {
  const { user } = useAuth();
  const isManagerOnly = user?.role === "manager";
  const [teamOnly, setTeamOnly] = useState(isManagerOnly);
  const [tab, setTab] = useState("pending");
  const [list, setList] = useState([]);
  const [today, setToday] = useState([]);
  const [loading, setLoading] = useState(true);
  const [decisionFor, setDecisionFor] = useState(null);
  const [action, setAction] = useState("approve");
  const [note, setNote] = useState("");

  const load = async () => {
    setLoading(true);
    const { data } = await api.get("/wfh/all", { params: { status: tab, scope: teamOnly ? "team" : undefined } });
    setList(data);
    setLoading(false);
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [tab, teamOnly]);
  useEffect(() => { api.get("/wfh/today").then((r) => setToday(r.data)); }, []);

  const decide = async () => {
    try {
      await api.post(`/wfh/${decisionFor.id}/${action}`, { note });
      toast.success(`WFH ${action === 'approve' ? 'approved' : 'rejected'}`);
      setDecisionFor(null); setNote(""); load();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  return (
    <div className="p-6 space-y-5 animate-fade-up" data-testid="admin-wfh">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h1 className="font-display text-3xl font-semibold tracking-tight text-slate-900">Work from home</h1>
          <p className="text-sm text-slate-500 mt-1">Approve remote-day requests and see who's offsite.</p>
        </div>
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg border border-slate-200 bg-white">
          <Switch
            checked={teamOnly}
            onCheckedChange={setTeamOnly}
            disabled={isManagerOnly}
            id="team-only-wfh"
            data-testid="wfh-team-toggle"
          />
          <Label htmlFor="team-only-wfh" className="text-sm font-medium text-slate-700 cursor-pointer">
            My team only
          </Label>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="surface p-5">
          <div className="text-xs uppercase tracking-widest text-slate-400 font-semibold flex items-center gap-1.5"><House className="h-3.5 w-3.5" /> Remote today</div>
          <div className="font-display text-3xl font-semibold text-slate-900 mt-2">{today.length}</div>
        </div>
        <div className="surface p-5 md:col-span-2">
          <div className="text-xs uppercase tracking-widest text-slate-400 font-semibold flex items-center gap-1.5"><Users className="h-3.5 w-3.5" /> Who's WFH today</div>
          <div className="mt-3 flex flex-wrap gap-2">
            {today.length === 0 ? <div className="text-sm text-slate-400">Nobody is WFH today.</div> :
              today.map((t) => (
                <div key={t.id} className="px-3 py-1.5 rounded-full bg-blue-50 border border-blue-200 text-blue-700 text-xs font-medium">{t.user_name}</div>
              ))}
          </div>
        </div>
      </div>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList data-testid="wfh-tabs">
          <TabsTrigger value="pending">Pending</TabsTrigger>
          <TabsTrigger value="approved">Approved</TabsTrigger>
          <TabsTrigger value="rejected">Rejected</TabsTrigger>
          <TabsTrigger value="all">All</TabsTrigger>
        </TabsList>
        <TabsContent value={tab} className="mt-4">
          <div className="surface overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-slate-50 text-slate-500 text-xs uppercase tracking-wide">
                  <th className="text-left font-semibold px-5 py-3">Employee</th>
                  <th className="text-left font-semibold px-5 py-3">Date</th>
                  <th className="text-left font-semibold px-5 py-3">Reason</th>
                  <th className="text-left font-semibold px-5 py-3">Status</th>
                  <th className="text-right font-semibold px-5 py-3">Actions</th>
                </tr>
              </thead>
              <tbody>
                {loading ? <tr><td colSpan="5" className="px-5 py-12 text-center text-slate-400"><Loader2 className="h-5 w-5 animate-spin inline" /></td></tr> :
                 list.length === 0 ? <tr><td colSpan="5" className="px-5 py-12 text-center text-slate-400">Nothing here.</td></tr> :
                 list.map((r) => (
                  <tr key={r.id} className="border-t border-slate-100 hover:bg-slate-50/60">
                    <td className="px-5 py-3 font-medium text-slate-900">{r.user_name}</td>
                    <td className="px-5 py-3 text-slate-700">{r.date}</td>
                    <td className="px-5 py-3 text-slate-600 max-w-md truncate" title={r.reason}>{r.reason}</td>
                    <td className="px-5 py-3"><StatusPill status={r.status} /></td>
                    <td className="px-5 py-3 text-right">
                      {r.status === "pending" ? (
                        <div className="flex justify-end gap-1">
                          <Button size="sm" variant="outline" className="h-8 rounded-md border-emerald-200 text-emerald-700 hover:bg-emerald-50" onClick={()=>{ setDecisionFor(r); setAction("approve"); }} data-testid={`approve-wfh-${r.id}`}>
                            <Check className="h-3.5 w-3.5 mr-1" /> Approve
                          </Button>
                          <Button size="sm" variant="outline" className="h-8 rounded-md border-rose-200 text-rose-700 hover:bg-rose-50" onClick={()=>{ setDecisionFor(r); setAction("reject"); }} data-testid={`reject-wfh-${r.id}`}>
                            <X className="h-3.5 w-3.5 mr-1" /> Reject
                          </Button>
                        </div>
                      ) : <span className="text-xs text-slate-400">{r.decided_by ? `by ${r.decided_by}` : ''}</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </TabsContent>
      </Tabs>

      <Dialog open={!!decisionFor} onOpenChange={(o)=>{ if(!o) setDecisionFor(null); }}>
        <DialogContent className="rounded-2xl">
          <DialogHeader><DialogTitle className="font-display">{action === 'approve' ? 'Approve' : 'Reject'} WFH</DialogTitle></DialogHeader>
          <div className="text-sm text-slate-600">
            {decisionFor && <p><b>{decisionFor.user_name}</b> · {decisionFor.date}</p>}
            <Textarea value={note} onChange={(e)=>setNote(e.target.value)} placeholder="Note (optional)" className="mt-3" />
          </div>
          <DialogFooter>
            <Button onClick={decide} className={action === 'approve' ? "bg-emerald-600 hover:bg-emerald-700" : "bg-rose-600 hover:bg-rose-700"} data-testid="confirm-wfh-decision">Confirm {action}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
