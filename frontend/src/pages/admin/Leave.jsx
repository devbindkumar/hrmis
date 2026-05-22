import { useEffect, useState } from "react";
import api, { formatApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import StatusPill from "@/components/StatusPill";
import { toast } from "sonner";
import { Check, X, Loader2 } from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/contexts/AuthContext";

export default function AdminLeave() {
  const { user } = useAuth();
  const isManagerOnly = user?.role === "manager";
  const [teamOnly, setTeamOnly] = useState(isManagerOnly);
  const [tab, setTab] = useState("pending");
  const [list, setList] = useState([]);
  const [loading, setLoading] = useState(true);
  const [decisionFor, setDecisionFor] = useState(null);
  const [note, setNote] = useState("");
  const [action, setAction] = useState("approve");

  const load = async () => {
    setLoading(true);
    const { data } = await api.get("/leave/all", { params: { status: tab, scope: teamOnly ? "team" : undefined } });
    setList(data);
    setLoading(false);
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [tab, teamOnly]);

  const decide = async () => {
    try {
      await api.post(`/leave/${decisionFor.id}/${action}`, { note });
      toast.success(`Leave ${action === 'approve' ? 'approved' : 'rejected'}`);
      setDecisionFor(null);
      setNote("");
      load();
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail));
    }
  };

  return (
    <div className="p-6 space-y-5 animate-fade-up" data-testid="admin-leave">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h1 className="font-display text-3xl font-semibold tracking-tight text-slate-900">Leave management</h1>
          <p className="text-sm text-slate-500 mt-1">Approve, reject, and track leave requests across teams.</p>
        </div>
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg border border-slate-200 bg-white">
          <Switch
            checked={teamOnly}
            onCheckedChange={setTeamOnly}
            disabled={isManagerOnly}
            id="team-only-leave"
            data-testid="leave-team-toggle"
          />
          <Label htmlFor="team-only-leave" className="text-sm font-medium text-slate-700 cursor-pointer">
            My team only
          </Label>
        </div>
      </div>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList data-testid="leave-tabs">
          <TabsTrigger value="pending" data-testid="tab-pending">Pending</TabsTrigger>
          <TabsTrigger value="approved" data-testid="tab-approved">Approved</TabsTrigger>
          <TabsTrigger value="rejected" data-testid="tab-rejected">Rejected</TabsTrigger>
          <TabsTrigger value="all" data-testid="tab-all">All</TabsTrigger>
        </TabsList>
        <TabsContent value={tab} className="mt-4">
          <div className="surface overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-slate-50 text-slate-500 text-xs uppercase tracking-wide">
                  <th className="text-left font-semibold px-5 py-3">Employee</th>
                  <th className="text-left font-semibold px-5 py-3">Type</th>
                  <th className="text-left font-semibold px-5 py-3">Range</th>
                  <th className="text-left font-semibold px-5 py-3">Days</th>
                  <th className="text-left font-semibold px-5 py-3">Reason</th>
                  <th className="text-left font-semibold px-5 py-3">Status</th>
                  <th className="text-right font-semibold px-5 py-3">Actions</th>
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr><td colSpan="7" className="px-5 py-12 text-center text-slate-400"><Loader2 className="h-5 w-5 animate-spin inline" /></td></tr>
                ) : list.length === 0 ? (
                  <tr><td colSpan="7" className="px-5 py-12 text-center text-slate-400">No requests in this tab.</td></tr>
                ) : list.map((r) => (
                  <tr key={r.id} className="border-t border-slate-100 hover:bg-slate-50/60">
                    <td className="px-5 py-3 font-medium text-slate-900">{r.user_name}</td>
                    <td className="px-5 py-3 text-slate-700">{r.leave_type}</td>
                    <td className="px-5 py-3 text-slate-700">{r.start_date} → {r.end_date}</td>
                    <td className="px-5 py-3 text-slate-700">{r.days}</td>
                    <td className="px-5 py-3 text-slate-600 max-w-xs truncate" title={r.reason}>{r.reason}</td>
                    <td className="px-5 py-3"><StatusPill status={r.status} /></td>
                    <td className="px-5 py-3 text-right">
                      {r.status === "pending" ? (
                        <div className="flex justify-end gap-1">
                          <Button size="sm" variant="outline" className="h-8 rounded-md border-emerald-200 text-emerald-700 hover:bg-emerald-50"
                            onClick={()=>{ setDecisionFor(r); setAction("approve"); }}
                            data-testid={`approve-leave-${r.id}`}>
                            <Check className="h-3.5 w-3.5 mr-1" /> Approve
                          </Button>
                          <Button size="sm" variant="outline" className="h-8 rounded-md border-rose-200 text-rose-700 hover:bg-rose-50"
                            onClick={()=>{ setDecisionFor(r); setAction("reject"); }}
                            data-testid={`reject-leave-${r.id}`}>
                            <X className="h-3.5 w-3.5 mr-1" /> Reject
                          </Button>
                        </div>
                      ) : (
                        <span className="text-xs text-slate-400">{r.decided_by ? `by ${r.decided_by}` : ''}</span>
                      )}
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
          <DialogHeader>
            <DialogTitle className="font-display">{action === 'approve' ? 'Approve' : 'Reject'} leave</DialogTitle>
          </DialogHeader>
          <div className="text-sm text-slate-600">
            {decisionFor && (
              <p><b>{decisionFor.user_name}</b> · {decisionFor.leave_type} · {decisionFor.days} day(s) · {decisionFor.start_date} → {decisionFor.end_date}</p>
            )}
            <Textarea value={note} onChange={(e)=>setNote(e.target.value)} placeholder="Add a note (optional)" className="mt-3" />
          </div>
          <DialogFooter>
            <Button onClick={decide} className={action === 'approve' ? "bg-emerald-600 hover:bg-emerald-700" : "bg-rose-600 hover:bg-rose-700"} data-testid="confirm-leave-decision">
              Confirm {action}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
