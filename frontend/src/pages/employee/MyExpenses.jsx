// Employee-side expense claims page — submit + view own claims with receipt upload.

import { useEffect, useState } from "react";
import api, { formatApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { Plus, Loader2, Receipt, Paperclip, Trash2, Pencil, X } from "lucide-react";
import { toast } from "sonner";

const STATUS_STYLES = {
  pending:  { label: "Pending",  cls: "bg-amber-50 text-amber-700 border-amber-200" },
  approved: { label: "Approved", cls: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  rejected: { label: "Rejected", cls: "bg-rose-50 text-rose-700 border-rose-200" },
  paid:     { label: "Reimbursed", cls: "bg-blue-50 text-blue-700 border-blue-200" },
};

export default function MyExpenses() {
  const [mine, setMine] = useState([]);
  const [categories, setCategories] = useState([]);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null); // claim being edited
  const [receipt, setReceipt] = useState(null); // { id, url }

  const load = async () => {
    const [a, b] = await Promise.all([api.get("/expenses/mine"), api.get("/expenses/categories")]);
    setMine(a.data);
    setCategories(b.data.categories || []);
  };
  useEffect(() => { load(); }, []);

  const remove = async (id) => {
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
    } catch (e) { toast.error("Unable to load receipt"); }
  };

  const totalPending = mine.filter(m => m.status === "pending").reduce((a, b) => a + b.amount, 0);
  const totalApproved = mine.filter(m => m.status === "approved").reduce((a, b) => a + b.amount, 0);
  const totalPaid = mine.filter(m => m.status === "paid").reduce((a, b) => a + b.amount, 0);

  return (
    <div className="space-y-6 animate-fade-up" data-testid="my-expenses">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="font-display text-3xl font-semibold tracking-tight text-slate-900">Expense claims</h1>
          <p className="text-sm text-slate-500 mt-1">Submit reimbursements and track their status.</p>
        </div>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button className="bg-slate-900 hover:bg-slate-800 text-white rounded-lg" data-testid="new-expense-btn">
              <Plus className="h-4 w-4 mr-1.5" /> New claim
            </Button>
          </DialogTrigger>
          <NewExpenseDialog categories={categories} onCreated={() => { setOpen(false); load(); }} />
        </Dialog>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <SummaryCard label="Pending" value={totalPending} tone="amber" />
        <SummaryCard label="Approved" value={totalApproved} tone="emerald" />
        <SummaryCard label="Reimbursed" value={totalPaid} tone="blue" />
      </div>

      <div className="surface overflow-hidden" data-testid="my-expenses-table">
        <div className="px-5 py-3 border-b border-slate-100 flex items-center justify-between">
          <h3 className="font-display text-base font-medium text-slate-900">Your claims</h3>
          <span className="text-xs text-slate-500">{mine.length} total</span>
        </div>
        {mine.length === 0 ? (
          <div className="p-10 text-center">
            <Receipt className="h-8 w-8 mx-auto text-slate-300" strokeWidth={1.25} />
            <div className="mt-2 text-sm text-slate-500">No claims yet.</div>
            <div className="text-xs text-slate-400 mt-1">Click &quot;New claim&quot; to submit your first reimbursement.</div>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-slate-50 text-slate-500 text-xs uppercase tracking-wide">
                <th className="text-left font-semibold px-5 py-3">Date</th>
                <th className="text-left font-semibold px-5 py-3">Category</th>
                <th className="text-left font-semibold px-5 py-3">Description</th>
                <th className="text-right font-semibold px-5 py-3">Amount</th>
                <th className="text-left font-semibold px-5 py-3">Status</th>
                <th className="px-5 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {mine.map((m) => {
                const s = STATUS_STYLES[m.status] || STATUS_STYLES.pending;
                return (
                  <tr key={m.id} data-testid={`expense-row-${m.id}`}>
                    <td className="px-5 py-3 text-slate-700 whitespace-nowrap">{m.date_incurred}</td>
                    <td className="px-5 py-3 text-slate-700">{m.category}</td>
                    <td className="px-5 py-3 text-slate-600 max-w-xs truncate" title={m.description}>{m.description}</td>
                    <td className="px-5 py-3 text-slate-900 font-medium text-right tabular-nums">{m.currency} {m.amount.toLocaleString()}</td>
                    <td className="px-5 py-3">
                      <Badge variant="outline" className={`rounded-full font-medium ${s.cls}`}>{s.label}</Badge>
                      {m.decision_note && (
                        <div className="text-[11px] text-slate-500 mt-1 italic max-w-[200px] truncate" title={m.decision_note}>“{m.decision_note}”</div>
                      )}
                    </td>
                    <td className="px-5 py-3 text-right whitespace-nowrap">
                      {m.has_receipt && (
                        <button onClick={() => openReceipt(m.id)} className="text-slate-500 hover:text-slate-900 mr-3" title="View receipt" data-testid={`view-receipt-${m.id}`}>
                          <Paperclip className="h-4 w-4 inline" />
                        </button>
                      )}
                      {m.status === "pending" && (
                        <>
                          <button onClick={() => setEditing(m)} className="text-slate-400 hover:text-slate-900 mr-2" title="Edit claim" data-testid={`edit-expense-${m.id}`}>
                            <Pencil className="h-4 w-4 inline" />
                          </button>
                          <button onClick={() => remove(m.id)} className="text-slate-400 hover:text-rose-600" title="Delete claim" data-testid={`delete-expense-${m.id}`}>
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

      <ReceiptViewer receipt={receipt} onClose={() => { if (receipt?.url) URL.revokeObjectURL(receipt.url); setReceipt(null); }} />

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

function SummaryCard({ label, value, tone }) {
  const styles = {
    amber:   "bg-amber-50 text-amber-700 border-amber-100",
    emerald: "bg-emerald-50 text-emerald-700 border-emerald-100",
    blue:    "bg-blue-50 text-blue-700 border-blue-100",
  }[tone] || "bg-slate-50 text-slate-700 border-slate-100";
  return (
    <div className={`rounded-xl border p-5 ${styles}`} data-testid={`expense-summary-${label.toLowerCase()}`}>
      <div className="text-xs uppercase tracking-widest font-semibold opacity-80">{label}</div>
      <div className="font-display text-3xl font-semibold mt-2 tabular-nums">₹ {value.toLocaleString()}</div>
    </div>
  );
}

export function NewExpenseDialog({ categories, onCreated, initial = null }) {
  const isEdit = !!initial;
  const [form, setForm] = useState({
    category: initial?.category || categories[0] || "Travel",
    amount: initial ? String(initial.amount) : "",
    currency: initial?.currency || "INR",
    date_incurred: initial?.date_incurred || new Date().toISOString().slice(0, 10),
    description: initial?.description || "",
  });
  const [receiptB64, setReceiptB64] = useState(null);
  const [receiptName, setReceiptName] = useState(null);
  const [removeReceipt, setRemoveReceipt] = useState(false);
  const [busy, setBusy] = useState(false);

  const pickFile = (file) => {
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) { toast.error("Receipt must be under 5 MB"); return; }
    const reader = new FileReader();
    reader.onload = () => { setReceiptB64(reader.result); setReceiptName(file.name); setRemoveReceipt(false); };
    reader.readAsDataURL(file);
  };

  const submit = async () => {
    if (!form.amount || !(+form.amount > 0)) { toast.error("Enter a valid amount"); return; }
    if (!form.description.trim()) { toast.error("Description is required"); return; }
    setBusy(true);
    try {
      if (isEdit) {
        const payload = { ...form, amount: +form.amount };
        if (receiptB64) payload.receipt_b64 = receiptB64;
        else if (removeReceipt) payload.remove_receipt = true;
        await api.patch(`/expenses/${initial.id}`, payload);
        toast.success("Claim updated");
      } else {
        await api.post("/expenses", { ...form, amount: +form.amount, receipt_b64: receiptB64 });
        toast.success("Expense submitted for approval");
      }
      onCreated();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };

  return (
    <DialogContent className="rounded-2xl max-w-lg" data-testid="new-expense-dialog">
      <DialogHeader><DialogTitle className="font-display">{isEdit ? "Edit expense claim" : "New expense claim"}</DialogTitle></DialogHeader>
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label>Category</Label>
            <Select value={form.category} onValueChange={(v) => setForm({ ...form, category: v })}>
              <SelectTrigger className="mt-1.5" data-testid="expense-category"><SelectValue /></SelectTrigger>
              <SelectContent>
                {(categories.length ? categories : ["Travel","Meals","Office supplies","Other"]).map((c) => (
                  <SelectItem key={c} value={c}>{c}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label>Date incurred</Label>
            <Input type="date" value={form.date_incurred} onChange={(e) => setForm({ ...form, date_incurred: e.target.value })} className="mt-1.5" data-testid="expense-date" />
          </div>
        </div>
        <div className="grid grid-cols-3 gap-3">
          <div className="col-span-2">
            <Label>Amount</Label>
            <Input type="number" step="0.01" min="0" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} className="mt-1.5" data-testid="expense-amount" placeholder="0.00" />
          </div>
          <div>
            <Label>Currency</Label>
            <Input value={form.currency} onChange={(e) => setForm({ ...form, currency: e.target.value.toUpperCase() })} maxLength={4} className="mt-1.5 font-mono" data-testid="expense-currency" />
          </div>
        </div>
        <div>
          <Label>Description</Label>
          <Textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} className="mt-1.5" rows={3} data-testid="expense-description" placeholder="What was this expense for?" />
        </div>
        <div>
          <Label>Receipt (optional)</Label>
          {isEdit && initial?.has_receipt && !receiptName && !removeReceipt && (
            <div className="mt-1.5 flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
              <Paperclip className="h-3.5 w-3.5" />
              <span className="flex-1">Existing receipt attached — upload a new file to replace it.</span>
              <button
                type="button"
                onClick={() => setRemoveReceipt(true)}
                className="text-slate-500 hover:text-rose-600 font-medium"
                data-testid="expense-remove-existing-receipt"
              >Remove</button>
            </div>
          )}
          <div className="mt-1.5">
            <label className="flex items-center gap-2 rounded-lg border border-dashed border-slate-300 hover:border-slate-400 bg-slate-50/60 px-3 py-2.5 cursor-pointer" data-testid="expense-receipt-label">
              <Paperclip className="h-4 w-4 text-slate-500" />
              <span className="text-sm text-slate-600 truncate flex-1">{receiptName || (removeReceipt ? "Receipt will be removed on save" : "Attach an image or PDF (≤ 5 MB)")}</span>
              <input type="file" accept="image/*,application/pdf" hidden onChange={(e) => pickFile(e.target.files?.[0])} data-testid="expense-receipt-input" />
              {receiptName && (
                <button
                  type="button"
                  onClick={(e) => { e.preventDefault(); setReceiptB64(null); setReceiptName(null); }}
                  className="text-slate-400 hover:text-rose-600"
                ><X className="h-4 w-4" /></button>
              )}
            </label>
          </div>
        </div>
      </div>
      <DialogFooter>
        <Button onClick={submit} disabled={busy} className="bg-slate-900 hover:bg-slate-800 text-white" data-testid="expense-submit">
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : (isEdit ? "Save changes" : "Submit for approval")}
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}

function ReceiptViewer({ receipt, onClose }) {
  if (!receipt) return null;
  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-3xl" data-testid="receipt-viewer">
        <DialogHeader><DialogTitle>Receipt</DialogTitle></DialogHeader>
        <div className="mt-2 rounded-lg overflow-hidden bg-slate-100">
          <img src={receipt.url} alt="Receipt" className="w-full max-h-[70vh] object-contain" />
        </div>
      </DialogContent>
    </Dialog>
  );
}
