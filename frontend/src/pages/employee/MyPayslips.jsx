import { useEffect, useState } from "react";
import api from "@/lib/api";
import { Dialog } from "@/components/ui/dialog";
import { Banknote, Loader2, Wallet, FileText, Eye } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PayslipDetailDialog } from "@/pages/admin/Payroll";

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

const STATUS_COLORS = {
  finalized: "bg-blue-50 text-blue-700 border-blue-200",
  paid: "bg-emerald-50 text-emerald-700 border-emerald-200",
};

export default function MyPayslips() {
  const [structure, setStructure] = useState(null);
  const [payslips, setPayslips] = useState([]);
  const [loading, setLoading] = useState(true);
  const [viewing, setViewing] = useState(null);

  useEffect(() => {
    Promise.all([
      api.get("/payroll/structures/me").then((r) => setStructure(r.data)).catch(() => setStructure(null)),
      api.get("/payroll/payslips/mine").then((r) => setPayslips(r.data)).catch(() => setPayslips([])),
    ]).finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="surface p-12 text-center text-slate-400"><Loader2 className="h-5 w-5 animate-spin inline" /></div>;

  return (
    <div className="space-y-6 animate-fade-up" data-testid="my-payslips">
      <div>
        <h1 className="font-display text-3xl font-semibold tracking-tight text-slate-900">Payslips</h1>
        <p className="text-sm text-slate-500 mt-1">Your salary structure and monthly payslips.</p>
      </div>

      {structure ? (
        <div className="surface p-6 relative overflow-hidden">
          <div className="absolute inset-0 grid-bg opacity-40" />
          <div className="relative grid grid-cols-1 sm:grid-cols-4 gap-6">
            <div>
              <div className="text-xs uppercase tracking-widest font-semibold text-slate-400 flex items-center gap-1.5"><Wallet className="h-3.5 w-3.5" strokeWidth={1.5} />Monthly net</div>
              <div className="font-display text-3xl font-semibold text-emerald-700 mt-2">{fmtMoney(structure.calc.net, structure.calc.currency)}</div>
            </div>
            <div>
              <div className="text-xs uppercase tracking-widest font-semibold text-slate-400">Gross</div>
              <div className="font-display text-xl font-semibold text-slate-900 mt-2">{fmtMoney(structure.calc.gross, structure.calc.currency)}</div>
              <div className="text-xs text-slate-500 mt-1">Base + allowances</div>
            </div>
            <div>
              <div className="text-xs uppercase tracking-widest font-semibold text-slate-400">Tax ({structure.tax_pct}%)</div>
              <div className="font-display text-xl font-semibold text-slate-700 mt-2">−{fmtMoney(structure.calc.tax_amount, structure.calc.currency)}</div>
            </div>
            <div>
              <div className="text-xs uppercase tracking-widest font-semibold text-slate-400">PF ({structure.pf_pct}%)</div>
              <div className="font-display text-xl font-semibold text-slate-700 mt-2">−{fmtMoney(structure.calc.pf_amount, structure.calc.currency)}</div>
            </div>
          </div>
        </div>
      ) : (
        <div className="surface p-8 text-center" data-testid="no-structure">
          <div className="h-12 w-12 rounded-full bg-slate-100 grid place-items-center mx-auto"><Banknote className="h-6 w-6 text-slate-500" strokeWidth={1.5} /></div>
          <h3 className="font-display text-lg font-medium text-slate-900 mt-4">Salary not configured yet</h3>
          <p className="text-sm text-slate-500 mt-1">Your HR team hasn't set up your salary structure. Reach out to them.</p>
        </div>
      )}

      <div className="surface overflow-hidden">
        <div className="px-5 py-3 border-b border-slate-100 flex items-center justify-between">
          <h3 className="font-display text-base font-medium text-slate-900">Monthly payslips</h3>
          <div className="text-xs text-slate-500">{payslips.length} payslip(s)</div>
        </div>
        <table className="w-full text-sm" data-testid="my-payslip-table">
          <thead>
            <tr className="bg-slate-50 text-slate-500 text-xs uppercase tracking-wide">
              <th className="text-left font-semibold px-5 py-3">Period</th>
              <th className="text-right font-semibold px-5 py-3">Gross</th>
              <th className="text-right font-semibold px-5 py-3">Deductions</th>
              <th className="text-right font-semibold px-5 py-3">Net pay</th>
              <th className="text-left font-semibold px-5 py-3">Status</th>
              <th className="text-right font-semibold px-5 py-3 w-24"></th>
            </tr>
          </thead>
          <tbody>
            {payslips.length === 0 ? <tr><td colSpan="6" className="px-5 py-12 text-center text-slate-400">No finalized payslips yet.</td></tr> :
              payslips.map((p) => (
                <tr key={p.id} className="border-t border-slate-100 hover:bg-slate-50/60">
                  <td className="px-5 py-3 font-medium text-slate-900 flex items-center gap-2"><FileText className="h-4 w-4 text-slate-400" strokeWidth={1.5} /> {monthDisplay(p.period)}</td>
                  <td className="px-5 py-3 text-right text-slate-700">{fmtMoney(p.components.gross, p.components.currency)}</td>
                  <td className="px-5 py-3 text-right text-slate-700">−{fmtMoney(p.components.total_deductions, p.components.currency)}</td>
                  <td className="px-5 py-3 text-right text-emerald-700 font-semibold">{fmtMoney(p.components.net, p.components.currency)}</td>
                  <td className="px-5 py-3">
                    <span className={`inline-block px-2.5 py-0.5 rounded-full text-xs font-medium border ${STATUS_COLORS[p.status] || STATUS_COLORS.finalized}`}>{p.status}</span>
                  </td>
                  <td className="px-5 py-3 text-right">
                    <Button size="sm" variant="outline" className="h-8 rounded-md" onClick={()=>setViewing(p)} data-testid={`view-ps-${p.id}`}>
                      <Eye className="h-3.5 w-3.5 mr-1" /> View
                    </Button>
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>

      <Dialog open={!!viewing} onOpenChange={(o)=>{ if(!o) setViewing(null); }}>
        {viewing && <PayslipDetailDialog ps={viewing} />}
      </Dialog>
    </div>
  );
}
