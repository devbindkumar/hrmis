import { useEffect, useState } from "react";
import api, { formatApiError, getToken } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Banknote, Wallet, Users2, Loader2, Pencil, Play, CheckCircle2, FileText, ShieldCheck, Download, Printer } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "@/contexts/AuthContext";

const STAGE_COLORS = {
  draft: "bg-slate-100 text-slate-700 border-slate-200",
  finalized: "bg-blue-50 text-blue-700 border-blue-200",
  paid: "bg-emerald-50 text-emerald-700 border-emerald-200",
};

function fmtMoney(amount, currency = "USD") {
  try {
    return new Intl.NumberFormat(undefined, { style: "currency", currency, maximumFractionDigits: 0 }).format(amount || 0);
  } catch {
    return `${currency} ${(amount || 0).toLocaleString()}`;
  }
}

function monthDisplay(period) {
  if (!period) return "";
  const [y, m] = period.split("-");
  const d = new Date(parseInt(y), parseInt(m) - 1, 1);
  return d.toLocaleDateString(undefined, { month: "long", year: "numeric" });
}

function thisMonth() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

export default function Payroll() {
  const { user } = useAuth();
  const isSuperAdmin = user?.role === "super_admin";
  const [tab, setTab] = useState("summary");
  const [summary, setSummary] = useState(null);
  const [structures, setStructures] = useState([]);
  const [payslips, setPayslips] = useState([]);
  const [periodStatus, setPeriodStatus] = useState(null);
  const [period, setPeriod] = useState(thisMonth());
  const [editing, setEditing] = useState(null);
  const [viewing, setViewing] = useState(null);
  const [runningPayroll, setRunningPayroll] = useState(false);
  const [approving, setApproving] = useState(false);

  const loadSummary = () => api.get("/payroll/summary").then((r) => setSummary(r.data));
  const loadStructures = () => api.get("/payroll/structures").then((r) => setStructures(r.data));
  const loadPayslips = () => api.get("/payroll/payslips", { params: { period } }).then((r) => setPayslips(r.data));
  const loadPeriodStatus = () => api.get("/payroll/period-status", { params: { period } }).then((r) => setPeriodStatus(r.data));

  useEffect(() => { loadSummary(); loadStructures(); loadPayslips(); loadPeriodStatus(); /* eslint-disable-next-line */ }, []);
  useEffect(() => { loadPayslips(); loadPeriodStatus(); /* eslint-disable-next-line */ }, [period]);

  const runPayroll = async () => {
    setRunningPayroll(true);
    try {
      const { data } = await api.post("/payroll/run", { period });
      toast.success(`Payroll for ${monthDisplay(period)} · created ${data.created}, updated ${data.updated}, skipped ${data.skipped}`);
      loadPayslips(); loadSummary(); loadPeriodStatus();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setRunningPayroll(false); }
  };

  const approveMonth = async () => {
    if (!periodStatus?.draft_count) { toast.error("No drafts to approve"); return; }
    if (!window.confirm(`Approve and finalize ${periodStatus.draft_count} payslip(s) for ${monthDisplay(period)}? Total payable: ${fmtMoney(periodStatus.total_draft_net, periodStatus.currency)}`)) return;
    setApproving(true);
    try {
      const { data } = await api.post("/payroll/approve-month", { period });
      toast.success(`Approved ${data.finalized} payslip(s) · total net ${fmtMoney(data.total_net, periodStatus.currency)}`);
      loadPayslips(); loadSummary(); loadPeriodStatus();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setApproving(false); }
  };

  const finalizeOne = async (ps) => {
    try {
      await api.post(`/payroll/payslips/${ps.id}/finalize`);
      toast.success("Finalized — employee notified");
      loadPayslips(); loadSummary(); loadPeriodStatus();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };
  const markPaidOne = async (ps) => {
    try {
      await api.post(`/payroll/payslips/${ps.id}/mark-paid`);
      toast.success("Marked as paid");
      loadPayslips(); loadPeriodStatus();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  const exportCsv = async () => {
    const url = `${process.env.REACT_APP_BACKEND_URL}/api/payroll/payslips/export.csv?period=${encodeURIComponent(period)}`;
    try {
      const res = await fetch(url, { headers: { Authorization: `Bearer ${getToken()}` } });
      if (!res.ok) throw new Error("Export failed");
      const blob = await res.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `payslips-${period}.csv`;
      a.click();
      URL.revokeObjectURL(a.href);
      toast.success(`Exported ${period} payslips`);
    } catch { toast.error("Couldn't export CSV"); }
  };

  const exportCsvHandler = exportCsv;

  return (
    <div className="p-6 space-y-5 animate-fade-up" data-testid="admin-payroll">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="font-display text-3xl font-semibold tracking-tight text-slate-900">Payroll</h1>
          <p className="text-sm text-slate-500 mt-1">Salary structures, monthly runs, and payslip history.</p>
        </div>
      </div>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="summary" data-testid="tab-summary">Summary</TabsTrigger>
          <TabsTrigger value="run" data-testid="tab-run">Run payroll</TabsTrigger>
          <TabsTrigger value="structures" data-testid="tab-structures">Salary structures</TabsTrigger>
          <TabsTrigger value="payslips" data-testid="tab-payslips">Payslip history</TabsTrigger>
        </TabsList>

        {/* SUMMARY */}
        <TabsContent value="summary" className="mt-4">
          {!summary ? <div className="surface p-12 text-center text-slate-400"><Loader2 className="h-5 w-5 animate-spin inline" /></div> : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
              <KpiCard label="Monthly cost" value={fmtMoney(summary.monthly_cost, summary.currency)} icon={Wallet} accent="bg-slate-900 text-white" />
              <KpiCard label="Coverage" value={`${summary.coverage_pct}%`} icon={Users2} accent="bg-blue-50 text-blue-700" hint={`${summary.employees_with_structure}/${summary.employee_count} employees`} />
              <KpiCard label="Last payroll" value={monthDisplay(summary.last_run_period) || "—"} icon={Banknote} accent="bg-emerald-50 text-emerald-700" hint={summary.last_run_period ? "Most recent run" : "No runs yet"} />
              <KpiCard label="Periods archived" value={summary.period_stats.length} icon={FileText} accent="bg-fuchsia-50 text-fuchsia-700" />
              <div className="surface p-6 md:col-span-2 lg:col-span-4">
                <h3 className="font-display text-lg font-medium text-slate-900">Recent periods</h3>
                <div className="mt-4 overflow-x-auto">
                  {summary.period_stats.length === 0 ? <div className="text-sm text-slate-400 py-6 text-center">No payroll runs yet.</div> : (
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="text-slate-500 text-xs uppercase tracking-wide">
                          <th className="text-left font-semibold py-2">Period</th>
                          <th className="text-left font-semibold py-2">Payslips</th>
                          <th className="text-right font-semibold py-2">Gross</th>
                          <th className="text-right font-semibold py-2">Net paid</th>
                        </tr>
                      </thead>
                      <tbody>
                        {summary.period_stats.map((p) => (
                          <tr key={p.period} className="border-t border-slate-100">
                            <td className="py-2.5 font-medium text-slate-900">{monthDisplay(p.period)}</td>
                            <td className="py-2.5 text-slate-700">{p.count}</td>
                            <td className="py-2.5 text-right text-slate-700">{fmtMoney(p.total_gross, summary.currency)}</td>
                            <td className="py-2.5 text-right text-slate-900 font-medium">{fmtMoney(p.total_net, summary.currency)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              </div>
            </div>
          )}
        </TabsContent>

        {/* RUN PAYROLL */}
        <TabsContent value="run" className="mt-4 space-y-4">
          <div className="surface p-6">
            <div className="flex flex-wrap items-center gap-4">
              <div className="flex-1 min-w-[200px]">
                <Label className="text-xs uppercase tracking-widest font-semibold text-slate-500">Pay period</Label>
                <Input type="month" value={period} onChange={(e)=>setPeriod(e.target.value)} className="mt-1.5 h-11 w-56" data-testid="run-period" />
              </div>
              <Button onClick={runPayroll} disabled={runningPayroll} className="bg-slate-900 hover:bg-slate-800 text-white rounded-lg h-11 px-6" data-testid="run-payroll-btn">
                {runningPayroll ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : <Play className="h-4 w-4 mr-2" strokeWidth={1.5} />}
                Generate {monthDisplay(period)} draft payslips
              </Button>
            </div>
            <p className="text-xs text-slate-500 mt-3">
              Generation creates a draft payslip for every employee with a salary structure. Drafts can be re-run safely; finalized & paid payslips are preserved.
              <br/>Only <b>Super Admin</b> can approve the monthly total payable.
            </p>
          </div>

          {/* Super Admin approval banner */}
          {periodStatus && periodStatus.draft_count > 0 && (
            <div
              className={`surface p-6 border-l-4 ${isSuperAdmin ? "border-amber-500" : "border-slate-300"}`}
              data-testid="approval-banner"
            >
              <div className="flex flex-wrap items-center justify-between gap-4">
                <div className="flex items-start gap-3">
                  <div className={`h-10 w-10 rounded-lg ${isSuperAdmin ? "bg-amber-50 text-amber-700" : "bg-slate-100 text-slate-600"} grid place-items-center shrink-0`}>
                    <ShieldCheck className="h-5 w-5" strokeWidth={1.5} />
                  </div>
                  <div>
                    <div className="font-display text-lg font-medium text-slate-900">
                      {periodStatus.draft_count} draft payslip(s) awaiting Super Admin approval
                    </div>
                    <div className="text-sm text-slate-600 mt-0.5">
                      Total payable for <b>{monthDisplay(period)}</b>:&nbsp;
                      <span className="font-display font-semibold text-slate-900 text-base">{fmtMoney(periodStatus.total_draft_net, periodStatus.currency)}</span>
                      <span className="text-slate-500 ml-2">net · {fmtMoney(periodStatus.total_draft_gross, periodStatus.currency)} gross</span>
                    </div>
                  </div>
                </div>
                {isSuperAdmin ? (
                  <Button
                    onClick={approveMonth}
                    disabled={approving}
                    className="bg-amber-600 hover:bg-amber-700 text-white rounded-lg h-11 px-6"
                    data-testid="approve-month-btn"
                  >
                    {approving ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : <ShieldCheck className="h-4 w-4 mr-2" strokeWidth={1.5} />}
                    Approve &amp; finalize all
                  </Button>
                ) : (
                  <div className="text-xs text-slate-500 px-3 py-2 rounded-lg bg-slate-50 border border-slate-200">
                    Only your Super Admin can approve this run
                  </div>
                )}
              </div>
            </div>
          )}

          <PayslipTable payslips={payslips} onFinalize={finalizeOne} onMarkPaid={markPaidOne} onView={setViewing} canApprove={isSuperAdmin} />
        </TabsContent>

        {/* STRUCTURES */}
        <TabsContent value="structures" className="mt-4">
          <div className="surface overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-slate-50 text-slate-500 text-xs uppercase tracking-wide">
                  <th className="text-left font-semibold px-5 py-3">Employee</th>
                  <th className="text-left font-semibold px-5 py-3">Base</th>
                  <th className="text-left font-semibold px-5 py-3">Allowances</th>
                  <th className="text-left font-semibold px-5 py-3">Gross</th>
                  <th className="text-left font-semibold px-5 py-3">Net (estimate)</th>
                  <th className="text-right font-semibold px-5 py-3 w-24">Actions</th>
                </tr>
              </thead>
              <tbody>
                {structures.length === 0 ? <tr><td colSpan="6" className="px-5 py-12 text-center text-slate-400">No employees.</td></tr> :
                  structures.map((s) => {
                    const allowSum = s.structure ? (s.structure.allowances?.hra || 0) + (s.structure.allowances?.transport || 0) + (s.structure.allowances?.special || 0) : 0;
                    return (
                      <tr key={s.user_id} className="border-t border-slate-100 hover:bg-slate-50/60">
                        <td className="px-5 py-3">
                          <div className="flex items-center gap-3">
                            <Avatar className="h-9 w-9"><AvatarImage src={s.avatar_url} /><AvatarFallback className="text-xs">{s.name.split(" ").map(p=>p[0]).slice(0,2).join("")}</AvatarFallback></Avatar>
                            <div>
                              <div className="font-medium text-slate-900">{s.name}</div>
                              <div className="text-xs text-slate-500">{s.designation} · {s.department}</div>
                            </div>
                          </div>
                        </td>
                        <td className="px-5 py-3 text-slate-700">{s.structure ? fmtMoney(s.structure.base_salary, s.structure.currency) : <span className="text-slate-400 text-xs">Not set</span>}</td>
                        <td className="px-5 py-3 text-slate-700">{s.structure ? fmtMoney(allowSum, s.structure.currency) : "—"}</td>
                        <td className="px-5 py-3 text-slate-900 font-medium">{s.calc ? fmtMoney(s.calc.gross, s.calc.currency) : "—"}</td>
                        <td className="px-5 py-3 text-emerald-700 font-medium">{s.calc ? fmtMoney(s.calc.net, s.calc.currency) : "—"}</td>
                        <td className="px-5 py-3 text-right">
                          <button onClick={()=>setEditing(s)} className="inline-flex items-center gap-1 text-xs font-medium text-slate-600 hover:text-slate-900 px-2 py-1 rounded-md border border-slate-200 hover:bg-slate-50" data-testid={`edit-struct-${s.user_id}`}>
                            <Pencil className="h-3 w-3" /> {s.structure ? "Edit" : "Set"}
                          </button>
                        </td>
                      </tr>
                    );
                  })}
              </tbody>
            </table>
          </div>
        </TabsContent>

        {/* PAYSLIPS HISTORY */}
        <TabsContent value="payslips" className="mt-4 space-y-4">
          <div className="flex items-center gap-3 flex-wrap">
            <Input type="month" value={period} onChange={(e)=>setPeriod(e.target.value)} className="h-10 w-56" data-testid="history-period" />
            <div className="text-sm text-slate-500 flex-1">{payslips.length} payslip(s) for {monthDisplay(period)}</div>
            <Button onClick={exportCsv} variant="outline" className="rounded-lg" data-testid="export-payslips-csv">
              <Download className="h-4 w-4 mr-1.5" strokeWidth={1.5} /> Export CSV
            </Button>
          </div>
          <PayslipTable payslips={payslips} onFinalize={finalizeOne} onMarkPaid={markPaidOne} onView={setViewing} canApprove={isSuperAdmin} />
        </TabsContent>
      </Tabs>

      <Dialog open={!!editing} onOpenChange={(o)=>{ if(!o) setEditing(null); }}>
        {editing && (
          <EditStructureDialog row={editing} onSaved={() => { setEditing(null); loadStructures(); loadSummary(); }} />
        )}
      </Dialog>
      <Dialog open={!!viewing} onOpenChange={(o)=>{ if(!o) setViewing(null); }}>
        {viewing && <PayslipDetailDialog ps={viewing} />}
      </Dialog>
    </div>
  );
}

function KpiCard({ label, value, icon: Icon, accent, hint }) {
  return (
    <div className="surface p-5 card-hover">
      <div className="flex items-start justify-between">
        <div>
          <div className="text-xs uppercase tracking-[0.05em] font-semibold text-slate-500">{label}</div>
          <div className="font-display text-2xl font-semibold text-slate-900 mt-2">{value}</div>
          {hint && <div className="text-xs text-slate-500 mt-1">{hint}</div>}
        </div>
        <div className={`h-9 w-9 rounded-lg ${accent} grid place-items-center`}><Icon className="h-4 w-4" strokeWidth={1.5} /></div>
      </div>
    </div>
  );
}

function PayslipTable({ payslips, onFinalize, onMarkPaid, onView, canApprove }) {
  return (
    <div className="surface overflow-hidden">
      <table className="w-full text-sm" data-testid="payslip-table">
        <thead>
          <tr className="bg-slate-50 text-slate-500 text-xs uppercase tracking-wide">
            <th className="text-left font-semibold px-5 py-3">Employee</th>
            <th className="text-left font-semibold px-5 py-3">Period</th>
            <th className="text-right font-semibold px-5 py-3">Gross</th>
            <th className="text-right font-semibold px-5 py-3">Deductions</th>
            <th className="text-right font-semibold px-5 py-3">Net</th>
            <th className="text-left font-semibold px-5 py-3">Status</th>
            <th className="text-right font-semibold px-5 py-3 w-48">Actions</th>
          </tr>
        </thead>
        <tbody>
          {payslips.length === 0 ? <tr><td colSpan="7" className="px-5 py-12 text-center text-slate-400">No payslips for this period. Run payroll to generate drafts.</td></tr> :
            payslips.map((p) => (
              <tr key={p.id} className="border-t border-slate-100 hover:bg-slate-50/60">
                <td className="px-5 py-3">
                  <div className="font-medium text-slate-900">{p.user_name}</div>
                  <div className="text-xs text-slate-500">{p.designation} · {p.employee_code}</div>
                </td>
                <td className="px-5 py-3 text-slate-700">{monthDisplay(p.period)}</td>
                <td className="px-5 py-3 text-right text-slate-700">{fmtMoney(p.components.gross, p.components.currency)}</td>
                <td className="px-5 py-3 text-right text-slate-700">−{fmtMoney(p.components.total_deductions, p.components.currency)}</td>
                <td className="px-5 py-3 text-right text-slate-900 font-medium">{fmtMoney(p.components.net, p.components.currency)}</td>
                <td className="px-5 py-3">
                  <span className={`inline-block px-2.5 py-0.5 rounded-full text-xs font-medium border ${STAGE_COLORS[p.status] || STAGE_COLORS.draft}`}>{p.status}</span>
                </td>
                <td className="px-5 py-3 text-right">
                  <div className="flex justify-end gap-1">
                    <button onClick={()=>onView(p)} className="text-xs font-medium text-slate-600 hover:text-slate-900 px-2 py-1 rounded-md border border-slate-200 hover:bg-slate-50" data-testid={`view-ps-${p.id}`}>View</button>
                    {canApprove && p.status === "draft" && (
                      <button onClick={()=>onFinalize(p)} className="text-xs font-medium text-emerald-700 px-2 py-1 rounded-md border border-emerald-200 hover:bg-emerald-50" data-testid={`finalize-ps-${p.id}`}>Finalize</button>
                    )}
                    {canApprove && p.status === "finalized" && (
                      <button onClick={()=>onMarkPaid(p)} className="text-xs font-medium text-blue-700 px-2 py-1 rounded-md border border-blue-200 hover:bg-blue-50" data-testid={`paid-ps-${p.id}`}>Mark paid</button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
        </tbody>
      </table>
    </div>
  );
}

function EditStructureDialog({ row, onSaved }) {
  const s = row.structure || {};
  const [form, setForm] = useState({
    base_salary: s.base_salary || 0,
    hra: s.allowances?.hra || 0,
    transport: s.allowances?.transport || 0,
    special: s.allowances?.special || 0,
    pf_pct: s.pf_pct ?? 6,
    tax_pct: s.tax_pct ?? 10,
    currency: s.currency || "USD",
  });
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true);
    try {
      await api.put(`/payroll/structures/${row.user_id}`, {
        user_id: row.user_id,
        base_salary: Number(form.base_salary),
        allowances: { hra: Number(form.hra), transport: Number(form.transport), special: Number(form.special) },
        pf_pct: Number(form.pf_pct),
        tax_pct: Number(form.tax_pct),
        currency: form.currency,
      });
      toast.success("Salary saved");
      onSaved();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };

  // live preview
  const gross = Number(form.base_salary) + Number(form.hra) + Number(form.transport) + Number(form.special);
  const pf = Number(form.base_salary) * Number(form.pf_pct) / 100;
  const tax = (gross - pf) * Number(form.tax_pct) / 100;
  const net = gross - pf - tax;

  return (
    <DialogContent className="rounded-2xl max-w-2xl" data-testid="edit-structure-dialog">
      <DialogHeader>
        <DialogTitle className="font-display">Salary · {row.name}</DialogTitle>
      </DialogHeader>
      <div className="grid grid-cols-2 gap-4">
        <div className="col-span-2 grid grid-cols-3 gap-3 p-3 bg-slate-50 rounded-lg border border-slate-100">
          <PreviewStat label="Gross" value={fmtMoney(gross, form.currency)} />
          <PreviewStat label="Deductions" value={`−${fmtMoney(pf + tax, form.currency)}`} />
          <PreviewStat label="Net" value={fmtMoney(net, form.currency)} bold />
        </div>
        <div><Label>Base salary (monthly)</Label><Input type="number" value={form.base_salary} onChange={(e)=>setForm({...form, base_salary: e.target.value})} className="mt-1.5" data-testid="es-base" /></div>
        <div>
          <Label>Currency</Label>
          <Select value={form.currency} onValueChange={(v)=>setForm({...form, currency: v})}>
            <SelectTrigger className="mt-1.5"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="USD">USD</SelectItem>
              <SelectItem value="EUR">EUR</SelectItem>
              <SelectItem value="GBP">GBP</SelectItem>
              <SelectItem value="INR">INR</SelectItem>
              <SelectItem value="AED">AED</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div><Label>HRA</Label><Input type="number" value={form.hra} onChange={(e)=>setForm({...form, hra: e.target.value})} className="mt-1.5" /></div>
        <div><Label>Transport</Label><Input type="number" value={form.transport} onChange={(e)=>setForm({...form, transport: e.target.value})} className="mt-1.5" /></div>
        <div><Label>Special allowance</Label><Input type="number" value={form.special} onChange={(e)=>setForm({...form, special: e.target.value})} className="mt-1.5" /></div>
        <div></div>
        <div><Label>PF / pension %</Label><Input type="number" step="0.5" value={form.pf_pct} onChange={(e)=>setForm({...form, pf_pct: e.target.value})} className="mt-1.5" /></div>
        <div><Label>Tax %</Label><Input type="number" step="0.5" value={form.tax_pct} onChange={(e)=>setForm({...form, tax_pct: e.target.value})} className="mt-1.5" /></div>
      </div>
      <DialogFooter>
        <Button onClick={submit} disabled={busy} className="bg-slate-900 hover:bg-slate-800 text-white" data-testid="es-save">
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : "Save"}
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}

function PreviewStat({ label, value, bold }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-widest font-semibold text-slate-400">{label}</div>
      <div className={`mt-0.5 ${bold ? "font-display text-xl font-semibold text-slate-900" : "text-sm font-medium text-slate-700"}`}>{value}</div>
    </div>
  );
}

export function PayslipDetailDialog({ ps }) {
  const c = ps.components;
  const printPayslip = () => {
    const w = window.open("", "_blank", "width=720,height=900");
    if (!w) { toast.error("Allow pop-ups to print the payslip"); return; }
    const html = `<!doctype html><html><head><meta charset="utf-8"/>
<title>Payslip · ${ps.user_name} · ${monthDisplay(ps.period)}</title>
<style>
  @page { size: A4; margin: 32mm 24mm; }
  body { font-family: -apple-system, system-ui, "Helvetica Neue", Arial, sans-serif; color: #111827; max-width: 720px; margin: 0 auto; padding: 32px; }
  h1 { font-size: 22px; margin: 0 0 4px 0; letter-spacing: -0.01em; }
  .muted { color: #6b7280; font-size: 12px; }
  .pillbar { display: flex; justify-content: space-between; align-items: center; margin: 24px 0 16px; padding-bottom: 16px; border-bottom: 1px solid #e5e7eb; }
  .net { font-size: 26px; font-weight: 700; color: #047857; letter-spacing: -0.01em; }
  table { width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 13px; }
  th, td { padding: 8px 4px; border-bottom: 1px solid #f1f5f9; }
  th { text-align: left; color: #6b7280; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; font-size: 10px; }
  td.amount { text-align: right; font-variant-numeric: tabular-nums; }
  .row-totals { background: #f8fafc; font-weight: 600; }
  .meta { color: #6b7280; font-size: 11px; margin-top: 24px; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: 600; border: 1px solid; text-transform: capitalize; }
  .b-finalized { background: #eff6ff; color: #1d4ed8; border-color: #bfdbfe; }
  .b-paid { background: #ecfdf5; color: #047857; border-color: #a7f3d0; }
  .b-draft { background: #f1f5f9; color: #475569; border-color: #cbd5e1; }
  .footer { margin-top: 32px; padding-top: 12px; border-top: 1px solid #e5e7eb; font-size: 11px; color: #9ca3af; text-align: center; }
  @media print {
    .no-print { display: none !important; }
  }
</style></head><body>
  <div style="display:flex;justify-content:space-between;align-items:flex-start;">
    <div>
      <h1>Payslip</h1>
      <div class="muted">For pay period <b>${monthDisplay(ps.period)}</b></div>
    </div>
    <div style="text-align:right;">
      <div class="muted">Status</div>
      <div class="badge b-${ps.status}">${ps.status}</div>
    </div>
  </div>
  <div class="pillbar">
    <div>
      <div class="muted">Employee</div>
      <div style="font-size:16px;font-weight:600;">${ps.user_name}</div>
      <div class="muted">${ps.designation || ""} · ${ps.employee_code || ""}</div>
    </div>
    <div style="text-align:right;">
      <div class="muted">Net pay</div>
      <div class="net">${fmtMoney(c.net, c.currency)}</div>
    </div>
  </div>
  <table>
    <thead><tr><th>Earnings</th><th class="amount">Amount</th></tr></thead>
    <tbody>
      <tr><td>Base salary</td><td class="amount">${fmtMoney(c.base_salary, c.currency)}</td></tr>
      <tr><td>House rent allowance</td><td class="amount">${fmtMoney(c.hra, c.currency)}</td></tr>
      <tr><td>Transport allowance</td><td class="amount">${fmtMoney(c.transport, c.currency)}</td></tr>
      <tr><td>Special allowance</td><td class="amount">${fmtMoney(c.special, c.currency)}</td></tr>
      <tr class="row-totals"><td>Gross earnings</td><td class="amount">${fmtMoney(c.gross, c.currency)}</td></tr>
    </tbody>
  </table>
  <table>
    <thead><tr><th>Deductions</th><th class="amount">Amount</th></tr></thead>
    <tbody>
      <tr><td>Provident fund (${c.pf_pct}% of base)</td><td class="amount">−${fmtMoney(c.pf_amount, c.currency)}</td></tr>
      <tr><td>Income tax (${c.tax_pct}%)</td><td class="amount">−${fmtMoney(c.tax_amount, c.currency)}</td></tr>
      <tr class="row-totals"><td>Total deductions</td><td class="amount">−${fmtMoney(c.total_deductions, c.currency)}</td></tr>
    </tbody>
  </table>
  <div class="meta">
    Generated ${new Date(ps.generated_at).toLocaleString()}
    ${ps.finalized_at ? ` · Approved ${new Date(ps.finalized_at).toLocaleString()}${ps.approved_by ? ` by ${ps.approved_by}` : ''}` : ''}
    ${ps.paid_at ? ` · Paid ${new Date(ps.paid_at).toLocaleString()}` : ''}
  </div>
  <div class="footer">This is a system-generated payslip. No signature required.</div>
  <div class="no-print" style="margin-top:32px;text-align:center;">
    <button onclick="window.print()" style="padding:10px 20px;background:#0f172a;color:#fff;border:0;border-radius:8px;font-weight:600;cursor:pointer;">Print / Save as PDF</button>
  </div>
  <script>setTimeout(function(){ window.print(); }, 400);</script>
</body></html>`;
    w.document.write(html);
    w.document.close();
  };

  return (
    <DialogContent className="rounded-2xl max-w-lg" data-testid="payslip-detail">
      <DialogHeader>
        <DialogTitle className="font-display">Payslip · {monthDisplay(ps.period)}</DialogTitle>
        <div className="text-sm text-slate-500">{ps.user_name} · {ps.designation} · {ps.employee_code}</div>
      </DialogHeader>
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <Row label="Base salary" value={fmtMoney(c.base_salary, c.currency)} />
          <Row label="HRA" value={fmtMoney(c.hra, c.currency)} />
          <Row label="Transport" value={fmtMoney(c.transport, c.currency)} />
          <Row label="Special" value={fmtMoney(c.special, c.currency)} />
        </div>
        <div className="border-t border-slate-100 pt-3 grid grid-cols-2 gap-3">
          <Row label="Gross" value={fmtMoney(c.gross, c.currency)} bold />
          <Row label={`PF (${c.pf_pct}%)`} value={`−${fmtMoney(c.pf_amount, c.currency)}`} />
          <Row label={`Tax (${c.tax_pct}%)`} value={`−${fmtMoney(c.tax_amount, c.currency)}`} />
          <Row label="Deductions" value={`−${fmtMoney(c.total_deductions, c.currency)}`} />
        </div>
        <div className="border-t border-slate-100 pt-3 flex items-center justify-between">
          <div className="text-xs uppercase tracking-widest font-semibold text-slate-400">Net pay</div>
          <div className="font-display text-3xl font-semibold text-emerald-700">{fmtMoney(c.net, c.currency)}</div>
        </div>
        <div className="text-xs text-slate-400">Status: <b className="text-slate-700 capitalize">{ps.status}</b> · Generated {new Date(ps.generated_at).toLocaleDateString()}{ps.finalized_at && ` · Approved ${new Date(ps.finalized_at).toLocaleDateString()}${ps.approved_by ? ` by ${ps.approved_by}` : ''}`}{ps.paid_at && ` · Paid ${new Date(ps.paid_at).toLocaleDateString()}`}</div>
      </div>
      <DialogFooter>
        <Button
          onClick={printPayslip}
          disabled={ps.status === "draft"}
          className="bg-slate-900 hover:bg-slate-800 text-white"
          data-testid="download-payslip-pdf"
        >
          <Printer className="h-4 w-4 mr-1.5" strokeWidth={1.5} />
          {ps.status === "draft" ? "Available after approval" : "Download PDF"}
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}

function Row({ label, value, bold }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-widest font-semibold text-slate-400">{label}</div>
      <div className={`mt-0.5 ${bold ? "font-display text-lg font-semibold text-slate-900" : "text-sm font-medium text-slate-800"}`}>{value}</div>
    </div>
  );
}
