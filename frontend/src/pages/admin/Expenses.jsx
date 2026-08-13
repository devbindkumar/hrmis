// Admin-side expense claims — review, approve, reject, mark reimbursed.

import { useEffect, useState } from "react";
import api, { formatApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { toast } from "sonner";
import { Loader2, Receipt, Paperclip, Check, X, Banknote, User, Plus, Trash2, Pencil } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import { NewExpenseDialog } from "@/pages/employee/MyExpenses";

const STATUS_STYLES = {
  pending:  { label: "Pending",  cls: "bg-amber-50 text-amber-700 border-amber-200" },
  approved: { label: "Approved", cls: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  rejected: { label: "Rejected", cls: "bg-rose-50 text-rose-700 border-rose-200" },
  paid:     { label: "Reimbursed", cls: "bg-blue-50 text-blue-700 border-blue-200" },
};

export default function AdminExpenses() {
  const { user } = useAuth();
  const canReimburse = user?.role === "super_admin" || user?.role === "hr";
  const [items, setItems] = useState([]);
  const [status, setStatus] = useState("pending");
  const [summary, setSummary] = useState(null);
  const [scope, setScope] = useState("all"); // all | team | mine
  const [decision, setDecision] = useState(null); // { id, action, name, category, amount, currency }
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [receipt, setReceipt] = useState(null);
  const [categories, setCategories] = useState([]);
  const [newOpen, setNewOpen] = useState(false);
  const [editing, setEditing] = useState(null);

  const load = async () => {
    try {
      const params = { status };
      if (scope === "team") params.scope = "team";
      const listUrl = scope === "mine" ? "/expenses/mine" : "/expenses/all";
      const [a, b] = await Promise.all([
        api.get(listUrl, { params: scope === "mine" ? {} : params }),
        api.get("/expenses/summary"),
      ]);
      // /expenses/mine ignores the status filter → apply client-side
      const rows = scope === "mine" && status !== "all"
        ? a.data.filter((r) => r.status === status)
        : a.data;
      setItems(rows);
      setSummary(b.data);
    } catch { /* ignore */ }
  };
  useEffect(() => { load(); }, [status, scope]);
  useEffect(() => {
    api.get("/expenses/categories").then((r) => setCategories(r.data.categories || [])).catch(() => {});
  }, []);

  const deleteMine = async (id) => {
    if (!window.confirm("Delete this claim?")) return;
    try {
      await api.delete(`/expenses/${id}`);
      toast.success("Claim deleted");
      load();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  const openReceipt = async (id) => {
    try {
      const { data } = await api.get(`/expenses/${id}/receipt`, { responseType: "blob" });
      const url = URL.createObjectURL(data);
      setReceipt({ id, url });
    } catch { toast.error("Unable to load receipt"); }
  };

  const openDecision = (item, action) => {
    setDecision({ id: item.id, action, name: item.user_name, category: item.category, amount: item.amount, currency: item.currency });
    setNote("");
  };
  const submitDecision = async () => {
    if (!decision) return;
    setBusy(true);
    try {
      if (decision.action === "paid") {
        await api.post(`/expenses/${decision.id}/mark-paid`);
      } else {
        await api.post(`/expenses/${decision.id}/${decision.action}`, { note });
      }
      toast.success(
        decision.action === "approve" ? "Claim approved" :
        decision.action === "reject" ? "Claim rejected" : "Marked as reimbursed"
      );
      setDecision(null);
      load();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };

  return (
    <div className="p-6 space-y-6 animate-fade-up" data-testid="admin-expenses">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="font-display text-3xl font-semibold tracking-tight text-slate-900">Expense claims</h1>
          <p className="text-sm text-slate-500 mt-1">Review reimbursement requests, submit your own, and mark them paid.</p>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          <Tabs value={scope} onValueChange={setScope}>
            <TabsList>
              {user?.role === "manager" && (
                <TabsTrigger value="team" data-testid="scope-team">My team</TabsTrigger>
              )}
              <TabsTrigger value="all" data-testid="scope-all">All claims</TabsTrigger>
              <TabsTrigger value="mine" data-testid="scope-mine">My claims</TabsTrigger>
            </TabsList>
          </Tabs>
          <Dialog open={newOpen} onOpenChange={setNewOpen}>
            <DialogTrigger asChild>
              <Button className="bg-slate-900 hover:bg-slate-800 text-white rounded-lg" data-testid="admin-new-expense-btn">
                <Plus className="h-4 w-4 mr-1.5" /> New claim
              </Button>
            </DialogTrigger>
            <NewExpenseDialog
              categories={categories}
              onCreated={() => { setNewOpen(false); setScope("mine"); setStatus("pending"); load(); }}
            />
          </Dialog>
        </div>
      </div>

      {summary && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <SummaryCard label="Pending"    value={summary.pending?.total || 0}   count={summary.pending?.count || 0}   tone="amber" />
          <SummaryCard label="Approved"   value={summary.approved?.total || 0}  count={summary.approved?.count || 0}  tone="emerald" />
          <SummaryCard label="Rejected"   value={summary.rejected?.total || 0}  count={summary.rejected?.count || 0}  tone="rose" />
          <SummaryCard label="Reimbursed" value={summary.paid?.total || 0}      count={summary.paid?.count || 0}      tone="blue" />
        </div>
      )}

      <div className="surface overflow-hidden">
        <div className="px-5 py-3 border-b border-slate-100 flex items-center justify-between flex-wrap gap-3">
          <h3 className="font-display text-base font-medium text-slate-900">Claims</h3>
          <Tabs value={status} onValueChange={setStatus}>
            <TabsList>
              <TabsTrigger value="pending"  data-testid="tab-pending">Pending</TabsTrigger>
              <TabsTrigger value="approved" data-testid="tab-approved">Approved</TabsTrigger>
              <TabsTrigger value="rejected" data-testid="tab-rejected">Rejected</TabsTrigger>
              <TabsTrigger value="paid"     data-testid="tab-paid">Reimbursed</TabsTrigger>
              <TabsTrigger value="all"      data-testid="tab-all">All</TabsTrigger>
            </TabsList>
          </Tabs>
        </div>

        {items.length === 0 ? (
          <div className="p-10 text-center">
            <Receipt className="h-8 w-8 mx-auto text-slate-300" strokeWidth={1.25} />
            <div className="mt-2 text-sm text-slate-500">No claims in this status.</div>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-slate-50 text-slate-500 text-xs uppercase tracking-wide">
                <th className="text-left font-semibold px-5 py-3">Employee</th>
                <th className="text-left font-semibold px-5 py-3">Date</th>
                <th className="text-left font-semibold px-5 py-3">Category</th>
                <th className="text-left font-semibold px-5 py-3">Description</th>
                <th className="text-right font-semibold px-5 py-3">Amount</th>
                <th className="text-left font-semibold px-5 py-3">Status</th>
                <th className="px-5 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {items.map((m) => {
                const s = STATUS_STYLES[m.status] || STATUS_STYLES.pending;
                return (
                  <tr key={m.id} data-testid={`admin-expense-row-${m.id}`}>
                    <td className="px-5 py-3">
                      <div className="flex items-center gap-2">
                        <div className="h-7 w-7 rounded-full bg-slate-100 grid place-items-center">
                          <User className="h-3.5 w-3.5 text-slate-500" />
                        </div>
                        <div>
                          <div className="text-slate-900 font-medium">{m.user_name}</div>
                          {m.manager_name && <div className="text-[11px] text-slate-500">via {m.manager_name}</div>}
                        </div>
                      </div>
                    </td>
                    <td className="px-5 py-3 text-slate-700 whitespace-nowrap">{m.date_incurred}</td>
                    <td className="px-5 py-3 text-slate-700">{m.category}</td>
                    <td className="px-5 py-3 text-slate-600 max-w-xs truncate" title={m.description}>{m.description}</td>
                    <td className="px-5 py-3 text-slate-900 font-medium text-right tabular-nums whitespace-nowrap">
                      {m.currency} {m.amount.toLocaleString()}
                    </td>
                    <td className="px-5 py-3">
                      <Badge variant="outline" className={`rounded-full font-medium ${s.cls}`}>{s.label}</Badge>
                      {m.decision_note && (
                        <div className="text-[11px] text-slate-500 mt-1 italic max-w-[180px] truncate" title={m.decision_note}>“{m.decision_note}”</div>
                      )}
                    </td>
                    <td className="px-5 py-3 text-right whitespace-nowrap">
                      {m.has_receipt && (
                        <button onClick={() => openReceipt(m.id)} className="text-slate-500 hover:text-slate-900 mr-2" title="View receipt" data-testid={`admin-view-receipt-${m.id}`}>
                          <Paperclip className="h-4 w-4 inline" />
                        </button>
                      )}
                      {m.status === "pending" && (
                        <>
                          {/* Only super_admin can approve their own claim; managers/HR cannot self-approve */}
                          {(m.user_id !== user?.id || user?.role === "super_admin") && (
                            <>
                              <Button size="sm" variant="outline" className="text-emerald-700 border-emerald-200 hover:bg-emerald-50 mr-1.5" onClick={() => openDecision(m, "approve")} data-testid={`approve-expense-${m.id}`}>
                                <Check className="h-3.5 w-3.5 mr-1" /> Approve
                              </Button>
                              <Button size="sm" variant="outline" className="text-rose-700 border-rose-200 hover:bg-rose-50" onClick={() => openDecision(m, "reject")} data-testid={`reject-expense-${m.id}`}>
                                <X className="h-3.5 w-3.5 mr-1" /> Reject
                              </Button>
                            </>
                          )}
                        </>
                      )}
                      {m.status === "approved" && canReimburse && (
                        <Button size="sm" className="bg-blue-600 hover:bg-blue-700 text-white" onClick={() => openDecision(m, "paid")} data-testid={`pay-expense-${m.id}`}>
                          <Banknote className="h-3.5 w-3.5 mr-1" /> Mark reimbursed
                        </Button>
                      )}
                      {m.status === "pending" && m.user_id === user?.id && (
                        <>
                          <button
                            onClick={() => setEditing(m)}
                            className="text-slate-400 hover:text-slate-900 ml-1 align-middle"
                            title="Edit your claim"
                            data-testid={`admin-edit-expense-${m.id}`}
                          >
                            <Pencil className="h-4 w-4 inline" />
                          </button>
                          <button
                            onClick={() => deleteMine(m.id)}
                            className="text-slate-400 hover:text-rose-600 ml-1 align-middle"
                            title="Delete your claim"
                            data-testid={`admin-delete-expense-${m.id}`}
                          >
                            <Trash2 className="h-4 w-4 inline" />
                          </button>
                        </>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      <Dialog open={!!decision} onOpenChange={(v) => !v && setDecision(null)}>
        <DialogContent className="rounded-2xl" data-testid="decision-dialog">
          <DialogHeader>
            <DialogTitle className="font-display">
              {decision?.action === "approve" ? "Approve claim"
                : decision?.action === "reject" ? "Reject claim"
                : "Mark as reimbursed"}
            </DialogTitle>
          </DialogHeader>
          {decision && (
            <div className="space-y-3">
              <div className="rounded-lg border border-slate-100 bg-slate-50/50 p-3">
                <div className="text-sm text-slate-900 font-medium">{decision.name}</div>
                <div className="text-xs text-slate-500 mt-0.5">
                  {decision.category} · {decision.currency} {decision.amount.toLocaleString()}
                </div>
              </div>
              {decision.action !== "paid" && (
                <div>
                  <label className="text-sm font-medium text-slate-700">Note (optional)</label>
                  <Textarea value={note} onChange={(e) => setNote(e.target.value)} className="mt-1.5" rows={3} placeholder="Feedback for the employee..." data-testid="decision-note" />
                </div>
              )}
              {decision.action === "paid" && (
                <div className="text-sm text-slate-600">
                  Confirm that this claim has been paid out to the employee. This action is final.
                </div>
              )}
            </div>
          )}
          <DialogFooter>
            <Button
              onClick={submitDecision}
              disabled={busy}
              className={
                decision?.action === "approve" ? "bg-emerald-600 hover:bg-emerald-700 text-white" :
                decision?.action === "reject"  ? "bg-rose-600 hover:bg-rose-700 text-white" :
                                                 "bg-blue-600 hover:bg-blue-700 text-white"
              }
              data-testid="decision-submit"
            >
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> :
                decision?.action === "approve" ? "Approve" :
                decision?.action === "reject" ? "Reject" : "Confirm reimbursement"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {receipt && (
        <Dialog open onOpenChange={(v) => { if (!v) { URL.revokeObjectURL(receipt.url); setReceipt(null); } }}>
          <DialogContent className="max-w-3xl">
            <DialogHeader><DialogTitle>Receipt</DialogTitle></DialogHeader>
            <div className="mt-2 rounded-lg overflow-hidden bg-slate-100">
              <img src={receipt.url} alt="Receipt" className="w-full max-h-[70vh] object-contain" />
            </div>
          </DialogContent>
        </Dialog>
      )}

      <Dialog open={!!editing} onOpenChange={(v) => !v && setEditing(null)}>
        {editing && (
          <NewExpenseDialog
            categories={categories}
            initial={editing}
            onCreated={() => { setEditing(null); load(); }}
          />
        )}
      </Dialog>
    </div>
  );
}

function SummaryCard({ label, value, count, tone }) {
  const styles = {
    amber:   "bg-amber-50 text-amber-700 border-amber-100",
    emerald: "bg-emerald-50 text-emerald-700 border-emerald-100",
    rose:    "bg-rose-50 text-rose-700 border-rose-100",
    blue:    "bg-blue-50 text-blue-700 border-blue-100",
  }[tone] || "bg-slate-50 text-slate-700 border-slate-100";
  return (
    <div className={`rounded-xl border p-5 ${styles}`} data-testid={`admin-expense-summary-${label.toLowerCase()}`}>
      <div className="text-xs uppercase tracking-widest font-semibold opacity-80">{label}</div>
      <div className="font-display text-3xl font-semibold mt-2 tabular-nums">₹ {value.toLocaleString()}</div>
      <div className="text-xs opacity-70 mt-1">{count} claim{count === 1 ? "" : "s"}</div>
    </div>
  );
}
