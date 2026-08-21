// Telephone extension directory — company-wide phone book.
//
// • Super-admin / HR see Add / Edit / Delete controls.
// • Everyone else gets a read-only searchable table.

import { useEffect, useMemo, useState } from "react";
import api, { formatApiError } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Phone, Plus, Pencil, Trash2, Search, PhoneCall, Smartphone, Building2 } from "lucide-react";
import { toast } from "sonner";

export default function TelephoneExtensions() {
  const { user } = useAuth();
  const canEdit = user?.role === "super_admin" || user?.role === "hr";
  const [rows, setRows] = useState([]);
  const [employees, setEmployees] = useState([]);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState("");
  const [dept, setDept] = useState("all");
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/extensions");
      setRows(data || []);
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);
  useEffect(() => {
    if (!canEdit) return;
    api
      .get("/employees", { params: { status: "active" } })
      .then((r) => setEmployees(r.data || []))
      .catch(() => setEmployees([]));
  }, [canEdit]);

  const departments = useMemo(() => {
    const set = new Set(rows.map((r) => r.department).filter(Boolean));
    return Array.from(set).sort();
  }, [rows]);

  const filtered = useMemo(() => {
    const query = q.trim().toLowerCase();
    return rows.filter((r) => {
      if (dept !== "all" && r.department !== dept) return false;
      if (!query) return true;
      return [r.employee_name, r.department, r.extension, r.direct_dial, r.mobile, r.email]
        .filter(Boolean)
        .some((v) => String(v).toLowerCase().includes(query));
    });
  }, [rows, q, dept]);

  const remove = async (id, name) => {
    if (!window.confirm(`Remove extension for ${name}?`)) return;
    try {
      await api.delete(`/extensions/${id}`);
      toast.success("Extension removed");
      load();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  return (
    <div className="p-6 space-y-6 animate-fade-up" data-testid="extensions-page">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="font-display text-3xl font-semibold tracking-tight text-slate-900">Telephone extensions</h1>
          <p className="text-sm text-slate-500 mt-1">
            Company phone book — search by name, department or number.
          </p>
        </div>
        {canEdit && (
          <Dialog
            open={open || !!editing}
            onOpenChange={(v) => { if (!v) { setOpen(false); setEditing(null); } }}
          >
            <DialogTrigger asChild>
              <Button
                className="bg-slate-900 hover:bg-slate-800 text-white rounded-lg"
                onClick={() => { setEditing(null); setOpen(true); }}
                data-testid="add-extension-btn"
              >
                <Plus className="h-4 w-4 mr-1.5" /> Add extension
              </Button>
            </DialogTrigger>
            <ExtensionDialog
              employees={employees}
              initial={editing}
              onSaved={() => { setOpen(false); setEditing(null); load(); }}
            />
          </Dialog>
        )}
      </div>

      <div className="surface p-4 flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[240px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
          <Input
            placeholder="Search name, extension, department, mobile…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            className="pl-9"
            data-testid="extension-search"
          />
        </div>
        <Select value={dept} onValueChange={setDept}>
          <SelectTrigger className="w-52" data-testid="extension-dept-filter">
            <SelectValue placeholder="All departments" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All departments</SelectItem>
            {departments.map((d) => (
              <SelectItem key={d} value={d}>{d}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <div className="text-xs text-slate-500 ml-auto whitespace-nowrap">
          {filtered.length} of {rows.length} entries
        </div>
      </div>

      <div className="surface overflow-hidden">
        {loading ? (
          <div className="p-10 text-center text-sm text-slate-500">Loading directory…</div>
        ) : filtered.length === 0 ? (
          <div className="p-10 text-center">
            <Phone className="h-8 w-8 mx-auto text-slate-300" strokeWidth={1.25} />
            <div className="mt-2 text-sm text-slate-500">
              {rows.length === 0 ? "No extensions have been added yet." : "No matches for your filters."}
            </div>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-slate-50 text-slate-500 text-xs uppercase tracking-wide">
                <th className="text-left font-semibold px-5 py-3">Employee</th>
                <th className="text-left font-semibold px-5 py-3">Department</th>
                <th className="text-left font-semibold px-5 py-3">Extension</th>
                <th className="text-left font-semibold px-5 py-3">Direct dial</th>
                <th className="text-left font-semibold px-5 py-3">Mobile</th>
                {canEdit && <th className="px-5 py-3"></th>}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {filtered.map((r) => (
                <tr key={r.id} data-testid={`extension-row-${r.id}`}>
                  <td className="px-5 py-3">
                    <div className="flex items-center gap-3">
                      <div className="h-8 w-8 rounded-full bg-slate-100 grid place-items-center overflow-hidden shrink-0">
                        {r.avatar_url ? (
                          <img src={r.avatar_url} alt="" className="h-full w-full object-cover" />
                        ) : (
                          <span className="text-xs font-medium text-slate-500">
                            {(r.employee_name || "?").split(" ").map((p) => p[0]).slice(0, 2).join("")}
                          </span>
                        )}
                      </div>
                      <div className="min-w-0">
                        <div className="text-slate-900 font-medium truncate">{r.employee_name || "—"}</div>
                        {r.designation && <div className="text-[11px] text-slate-500 truncate">{r.designation}</div>}
                      </div>
                    </div>
                  </td>
                  <td className="px-5 py-3">
                    {r.department ? (
                      <Badge variant="outline" className="rounded-full text-slate-600 border-slate-200">
                        <Building2 className="h-3 w-3 mr-1" /> {r.department}
                      </Badge>
                    ) : <span className="text-slate-400">—</span>}
                  </td>
                  <td className="px-5 py-3">
                    <a
                      href={`tel:${r.extension}`}
                      className="inline-flex items-center gap-1.5 text-slate-900 font-medium font-mono hover:text-blue-600"
                      data-testid={`extension-number-${r.id}`}
                    >
                      <PhoneCall className="h-3.5 w-3.5 text-slate-400" />
                      {r.extension}
                    </a>
                  </td>
                  <td className="px-5 py-3 text-slate-700 font-mono whitespace-nowrap">
                    {r.direct_dial ? (
                      <a href={`tel:${r.direct_dial}`} className="hover:text-blue-600">{r.direct_dial}</a>
                    ) : <span className="text-slate-400">—</span>}
                  </td>
                  <td className="px-5 py-3 text-slate-700 font-mono whitespace-nowrap">
                    {r.mobile ? (
                      <a href={`tel:${r.mobile}`} className="inline-flex items-center gap-1 hover:text-blue-600">
                        <Smartphone className="h-3.5 w-3.5 text-slate-400" />
                        {r.mobile}
                      </a>
                    ) : <span className="text-slate-400">—</span>}
                  </td>
                  {canEdit && (
                    <td className="px-5 py-3 text-right whitespace-nowrap">
                      <button
                        className="text-slate-400 hover:text-slate-900 p-1.5 rounded-md hover:bg-slate-100"
                        onClick={() => setEditing(r)}
                        title="Edit"
                        data-testid={`edit-extension-${r.id}`}
                      >
                        <Pencil className="h-4 w-4" />
                      </button>
                      <button
                        className="text-slate-400 hover:text-rose-600 p-1.5 rounded-md hover:bg-rose-50 ml-1"
                        onClick={() => remove(r.id, r.employee_name)}
                        title="Delete"
                        data-testid={`delete-extension-${r.id}`}
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function ExtensionDialog({ employees, initial, onSaved }) {
  const isEdit = !!initial;
  const [form, setForm] = useState({
    employee_id: initial?.employee_id || "",
    extension: initial?.extension || "",
    direct_dial: initial?.direct_dial || "",
    mobile: initial?.mobile || "",
  });
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!form.employee_id) { toast.error("Select an employee"); return; }
    if (!form.extension.trim()) { toast.error("Extension is required"); return; }
    setBusy(true);
    try {
      if (isEdit) {
        await api.patch(`/extensions/${initial.id}`, {
          employee_id: form.employee_id,
          extension: form.extension.trim(),
          direct_dial: form.direct_dial.trim() || null,
          mobile: form.mobile.trim() || null,
        });
        toast.success("Extension updated");
      } else {
        await api.post("/extensions", {
          employee_id: form.employee_id,
          extension: form.extension.trim(),
          direct_dial: form.direct_dial.trim() || null,
          mobile: form.mobile.trim() || null,
        });
        toast.success("Extension added");
      }
      onSaved();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };

  return (
    <DialogContent className="rounded-2xl" data-testid="extension-dialog">
      <DialogHeader>
        <DialogTitle className="font-display">{isEdit ? "Edit extension" : "Add extension"}</DialogTitle>
      </DialogHeader>
      <div className="space-y-3">
        <div>
          <Label>Employee</Label>
          <Select
            value={form.employee_id || undefined}
            onValueChange={(v) => setForm({ ...form, employee_id: v })}
            disabled={isEdit}
          >
            <SelectTrigger className="mt-1.5" data-testid="ext-employee-select">
              <SelectValue placeholder="Select an employee…" />
            </SelectTrigger>
            <SelectContent>
              {(employees || []).map((e) => (
                <SelectItem key={e.id} value={e.id}>
                  {e.name}{e.department ? ` · ${e.department}` : ""}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {isEdit && (
            <p className="text-[11px] text-slate-400 mt-1">
              Delete and re-create the record if you need to reassign to a different employee.
            </p>
          )}
        </div>
        <div>
          <Label>Extension number</Label>
          <Input
            value={form.extension}
            onChange={(e) => setForm({ ...form, extension: e.target.value })}
            placeholder="e.g. 1042"
            className="mt-1.5 font-mono"
            data-testid="ext-number"
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label>Direct dial <span className="text-slate-400 text-xs">(optional)</span></Label>
            <Input
              value={form.direct_dial}
              onChange={(e) => setForm({ ...form, direct_dial: e.target.value })}
              placeholder="+91 22 4000 1042"
              className="mt-1.5 font-mono"
              data-testid="ext-direct"
            />
          </div>
          <div>
            <Label>Mobile <span className="text-slate-400 text-xs">(optional)</span></Label>
            <Input
              value={form.mobile}
              onChange={(e) => setForm({ ...form, mobile: e.target.value })}
              placeholder="+91 98 7654 3210"
              className="mt-1.5 font-mono"
              data-testid="ext-mobile"
            />
          </div>
        </div>
      </div>
      <DialogFooter>
        <Button
          onClick={submit}
          disabled={busy}
          className="bg-slate-900 hover:bg-slate-800 text-white"
          data-testid="ext-submit"
        >
          {busy ? "Saving…" : (isEdit ? "Save changes" : "Add extension")}
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}
