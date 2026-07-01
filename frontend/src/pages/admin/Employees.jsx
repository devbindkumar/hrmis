import { useEffect, useState } from "react";
import api, { formatApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Search, Plus, Loader2, Mail, Pencil, KeyRound, Eye, EyeOff, Copy } from "lucide-react";
import { toast } from "sonner";
import StatusPill from "@/components/StatusPill";
import { useAuth } from "@/contexts/AuthContext";

const ROLE_LABELS = { super_admin: "Super Admin", hr: "HR", manager: "Manager", employee: "Employee" };

export default function Employees() {
  const { user } = useAuth();
  const [list, setList] = useState([]);
  const [q, setQ] = useState("");
  const [dept, setDept] = useState("all");
  const [status, setStatus] = useState("all");
  const [departments, setDepartments] = useState([]);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    const { data } = await api.get("/employees", { params: { q: q || undefined, department: dept, status } });
    setList(data);
    setLoading(false);
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [q, dept, status]);
  useEffect(() => { api.get("/departments").then((r) => setDepartments(r.data)); }, []);

  const canCreate = ["super_admin", "hr"].includes(user?.role);
  const canEdit = ["super_admin", "hr", "manager"].includes(user?.role);

  return (
    <div className="p-6 space-y-5 animate-fade-up" data-testid="employees-page">
      <div className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <h1 className="font-display text-3xl font-semibold tracking-tight text-slate-900">Employees</h1>
          <p className="text-sm text-slate-500 mt-1">{list.length} people · across {departments.length} departments</p>
        </div>
        {canCreate && (
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
              <Button className="bg-slate-900 hover:bg-slate-800 text-white rounded-lg" data-testid="add-employee-btn">
                <Plus className="h-4 w-4 mr-1.5" strokeWidth={1.5} /> Add employee
              </Button>
            </DialogTrigger>
            <NewEmployeeDialog departments={departments} onCreated={() => { setOpen(false); load(); }} />
          </Dialog>
        )}
      </div>

      {/* Filters */}
      <div className="surface p-4 flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[220px]">
          <Search className="h-4 w-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" strokeWidth={1.5} />
          <Input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search name, email or code…"
            className="pl-9 h-10 rounded-lg border-slate-200"
            data-testid="employee-search"
          />
        </div>
        <Select value={dept} onValueChange={setDept}>
          <SelectTrigger className="w-44 h-10 rounded-lg" data-testid="filter-dept"><SelectValue placeholder="Department" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All departments</SelectItem>
            {departments.map((d) => <SelectItem key={d.id} value={d.name}>{d.name}</SelectItem>)}
          </SelectContent>
        </Select>
        <Select value={status} onValueChange={setStatus}>
          <SelectTrigger className="w-36 h-10 rounded-lg" data-testid="filter-status"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All status</SelectItem>
            <SelectItem value="active">Active</SelectItem>
            <SelectItem value="inactive">Inactive</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* Table */}
      <div className="surface overflow-hidden" data-testid="employee-directory-table">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-slate-50 text-slate-500 text-xs uppercase tracking-wide">
              <th className="text-left font-semibold px-5 py-3">Person</th>
              <th className="text-left font-semibold px-5 py-3">Code</th>
              <th className="text-left font-semibold px-5 py-3">Department</th>
              <th className="text-left font-semibold px-5 py-3">Role</th>
              <th className="text-left font-semibold px-5 py-3">Reports to</th>
              <th className="text-left font-semibold px-5 py-3">Location</th>
              <th className="text-left font-semibold px-5 py-3">Status</th>
              <th className="text-right font-semibold px-5 py-3 w-24">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan="8" className="px-5 py-12 text-center text-slate-400"><Loader2 className="h-5 w-5 animate-spin inline" /></td></tr>
            ) : list.length === 0 ? (
              <tr><td colSpan="8" className="px-5 py-12 text-center text-slate-400">No people found.</td></tr>
            ) : list.map((e) => (
              <tr key={e.id} className="border-t border-slate-100 hover:bg-slate-50/60 transition-colors">
                <td className="px-5 py-3">
                  <div className="flex items-center gap-3">
                    <Avatar className="h-9 w-9">
                      <AvatarImage src={e.avatar_url} alt={e.name} />
                      <AvatarFallback className="text-xs bg-slate-100 text-slate-700">{e.name.split(" ").map(p=>p[0]).slice(0,2).join("")}</AvatarFallback>
                    </Avatar>
                    <div>
                      <div className="font-medium text-slate-900">{e.name}</div>
                      <div className="text-xs text-slate-500 flex items-center gap-1"><Mail className="h-3 w-3" />{e.email}</div>
                    </div>
                  </div>
                </td>
                <td className="px-5 py-3 text-slate-600 font-mono text-xs">{e.employee_code}</td>
                <td className="px-5 py-3">
                  <div className="text-slate-800">{e.department}</div>
                  <div className="text-xs text-slate-500">{e.designation}</div>
                </td>
                <td className="px-5 py-3"><span className="inline-block px-2 py-0.5 rounded-md text-xs bg-slate-100 text-slate-700 border border-slate-200">{ROLE_LABELS[e.role] || e.role}</span></td>
                <td className="px-5 py-3">
                  {e.manager_name ? (
                    <div>
                      <div className="text-sm text-slate-800 font-medium">{e.manager_name}</div>
                      <div className="text-xs text-slate-500">{e.manager_designation}</div>
                    </div>
                  ) : (
                    <span className="text-xs text-slate-400">—</span>
                  )}
                </td>
                <td className="px-5 py-3 text-slate-600">{e.location}</td>
                <td className="px-5 py-3"><StatusPill status={e.status === 'active' ? 'active' : 'absent'} label={e.status === 'active' ? 'Active' : 'Inactive'} /></td>
                <td className="px-5 py-3 text-right">
                  {canEdit && (
                    <button
                      onClick={()=>setEditing(e)}
                      className="text-slate-400 hover:text-slate-900 inline-flex items-center gap-1 text-xs font-medium px-2 py-1 rounded-md border border-slate-200 hover:bg-slate-50"
                      data-testid={`edit-emp-${e.id}`}
                    >
                      <Pencil className="h-3 w-3" strokeWidth={1.5} /> Edit
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Edit employee dialog */}
      <Dialog open={!!editing} onOpenChange={(o)=>{ if(!o) setEditing(null); }}>
        {editing && (
          <EditEmployeeDialog
            employee={editing}
            departments={departments}
            canChangeRole={["super_admin","hr"].includes(user?.role)}
            canResetPassword={user?.role === "super_admin"}
            onSaved={() => { setEditing(null); load(); }}
          />
        )}
      </Dialog>
    </div>
  );
}

function EditEmployeeDialog({ employee, departments, canChangeRole, canResetPassword, onSaved }) {
  const [form, setForm] = useState({
    name: employee.name || "",
    department: employee.department || "",
    designation: employee.designation || "",
    location: employee.location || "",
    phone: employee.phone || "",
    manager_id: employee.manager_id || "",
    status: employee.status || "active",
  });
  const [busy, setBusy] = useState(false);
  const [managers, setManagers] = useState([]);

  useEffect(() => {
    api.get("/employees/managers").then((r) => setManagers(r.data.filter((m) => m.id !== employee.id)));
  }, [employee.id]);

  const save = async () => {
    if (!form.name || !form.department || !form.designation) {
      toast.error("Name, department and designation are required"); return;
    }
    setBusy(true);
    try {
      const payload = { ...form, manager_id: form.manager_id || null };
      await api.patch(`/employees/${employee.id}`, payload);
      toast.success("Saved");
      onSaved();
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail));
    } finally { setBusy(false); }
  };

  return (
    <DialogContent className="rounded-2xl max-w-2xl" data-testid="edit-employee-dialog">
      <DialogHeader>
        <DialogTitle className="font-display">Edit {employee.name}</DialogTitle>
      </DialogHeader>
      <div className="grid grid-cols-2 gap-4 py-2">
        <div className="col-span-2">
          <Label>Full name</Label>
          <Input value={form.name} onChange={(e)=>setForm({...form, name: e.target.value})} className="mt-1.5" data-testid="ee-name" />
        </div>
        <div>
          <Label>Department</Label>
          <Select value={form.department} onValueChange={(v)=>setForm({...form, department: v})}>
            <SelectTrigger className="mt-1.5" data-testid="ee-dept"><SelectValue /></SelectTrigger>
            <SelectContent>
              {departments.map((d)=> <SelectItem key={d.id} value={d.name}>{d.name}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <div>
          <Label>Designation</Label>
          <Input value={form.designation} onChange={(e)=>setForm({...form, designation: e.target.value})} className="mt-1.5" data-testid="ee-desig" />
        </div>
        <div>
          <Label>Location</Label>
          <Input value={form.location} onChange={(e)=>setForm({...form, location: e.target.value})} className="mt-1.5" />
        </div>
        <div>
          <Label>Phone</Label>
          <Input value={form.phone} onChange={(e)=>setForm({...form, phone: e.target.value})} className="mt-1.5" />
        </div>
        <div className="col-span-2">
          <Label>Reports to</Label>
          <Select value={form.manager_id || "none"} onValueChange={(v)=>setForm({...form, manager_id: v === "none" ? "" : v})}>
            <SelectTrigger className="mt-1.5" data-testid="ee-manager"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="none">No manager (reports directly to leadership)</SelectItem>
              {managers.map((m)=> (
                <SelectItem key={m.id} value={m.id}>
                  <span className="flex items-center gap-2">
                    <span className="font-medium">{m.name}</span>
                    <span className="text-xs text-slate-500">· {m.designation}</span>
                  </span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        {canChangeRole && (
          <div className="col-span-2">
            <Label>Status</Label>
            <Select value={form.status} onValueChange={(v)=>setForm({...form, status: v})}>
              <SelectTrigger className="mt-1.5" data-testid="ee-status"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="active">Active</SelectItem>
                <SelectItem value="inactive">Inactive (revokes access)</SelectItem>
              </SelectContent>
            </Select>
          </div>
        )}
      </div>

      {canResetPassword && (
        <ResetPasswordSection employeeId={employee.id} employeeName={employee.name} />
      )}

      <DialogFooter>
        <Button onClick={save} disabled={busy} className="bg-slate-900 hover:bg-slate-800 text-white" data-testid="ee-save">
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : "Save changes"}
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}

function ResetPasswordSection({ employeeId, employeeName }) {
  const [open, setOpen] = useState(false);
  const [pwd, setPwd] = useState("");
  const [show, setShow] = useState(false);
  const [notify, setNotify] = useState(true);
  const [busy, setBusy] = useState(false);
  const [lastSent, setLastSent] = useState(null);

  const generate = () => {
    const upper = "ABCDEFGHJKLMNPQRSTUVWXYZ";
    const lower = "abcdefghijkmnpqrstuvwxyz";
    const digits = "23456789";
    const symbols = "!@#$%&*";
    const all = upper + lower + digits + symbols;
    const pick = (s) => s[Math.floor(Math.random() * s.length)];
    let out = pick(upper) + pick(lower) + pick(digits) + pick(symbols);
    for (let i = 0; i < 8; i++) out += pick(all);
    setPwd(out.split("").sort(() => Math.random() - 0.5).join(""));
    setShow(true);
  };

  const submit = async () => {
    if (pwd.length < 8) { toast.error("Password must be at least 8 characters"); return; }
    setBusy(true);
    try {
      const { data } = await api.post(`/employees/${employeeId}/reset-password`, {
        new_password: pwd,
        notify_employee: notify,
      });
      setLastSent(data);
      toast.success(notify ? `Password reset · email sent to ${data.email}` : "Password reset");
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail));
    } finally { setBusy(false); }
  };

  const copyPwd = () => {
    if (!pwd) return;
    navigator.clipboard.writeText(pwd);
    toast.success("Password copied to clipboard");
  };

  return (
    <div className="mt-2 rounded-xl border border-amber-200/70 bg-amber-50/40 p-4" data-testid="reset-password-section">
      <button
        type="button"
        className="w-full flex items-center justify-between gap-2 text-left"
        onClick={() => setOpen(!open)}
        data-testid="reset-password-toggle"
      >
        <div className="flex items-center gap-2">
          <div className="h-8 w-8 rounded-lg bg-amber-100 text-amber-700 grid place-items-center">
            <KeyRound className="h-4 w-4" strokeWidth={1.6} />
          </div>
          <div>
            <div className="text-sm font-semibold text-slate-900">Reset {employeeName?.split(" ")[0] || "employee"}&apos;s password</div>
            <div className="text-[11px] text-slate-500">For when the employee forgets their password. Generate a new one and (optionally) email it.</div>
          </div>
        </div>
        <span className="text-xs text-amber-700 font-medium">{open ? "Hide" : "Open"}</span>
      </button>

      {open && (
        <div className="mt-3 space-y-3">
          <div>
            <Label className="text-xs">New password</Label>
            <div className="mt-1.5 flex items-center gap-2">
              <div className="relative flex-1">
                <Input
                  type={show ? "text" : "password"}
                  value={pwd}
                  onChange={(e) => setPwd(e.target.value)}
                  placeholder="Enter or generate a new password"
                  className="pr-10 font-mono text-sm"
                  data-testid="reset-password-input"
                />
                <button
                  type="button"
                  onClick={() => setShow(!show)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-700"
                  aria-label={show ? "Hide password" : "Show password"}
                >
                  {show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
              <Button
                type="button"
                variant="outline"
                onClick={generate}
                className="shrink-0"
                data-testid="reset-password-generate"
              >
                Generate
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={copyPwd}
                disabled={!pwd}
                className="shrink-0"
                data-testid="reset-password-copy"
              >
                <Copy className="h-3.5 w-3.5" />
              </Button>
            </div>
            <p className="text-[11px] text-slate-500 mt-1">Minimum 8 characters. Share only through a secure channel.</p>
          </div>

          <label className="flex items-center gap-2 text-xs text-slate-700 cursor-pointer select-none">
            <input
              type="checkbox"
              className="h-4 w-4 rounded border-slate-300 text-slate-900 focus:ring-slate-900"
              checked={notify}
              onChange={(e) => setNotify(e.target.checked)}
              data-testid="reset-password-notify"
            />
            Email the new password to the employee automatically
          </label>

          <div className="flex items-center gap-2">
            <Button
              type="button"
              onClick={submit}
              disabled={busy || pwd.length < 8}
              className="bg-amber-600 hover:bg-amber-700 text-white"
              data-testid="reset-password-submit"
            >
              {busy ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : <KeyRound className="h-3.5 w-3.5 mr-1.5" />}
              Reset password
            </Button>
            {lastSent && (
              <span className="text-[11px] text-emerald-700 font-medium" data-testid="reset-password-last-sent">
                Reset done · {lastSent.notified ? "email sent" : "no email sent"}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function NewEmployeeDialog({ departments, onCreated }) {
  const [form, setForm] = useState({ name: "", email: "", department: "", designation: "", role: "employee", location: "HQ", password: "Demo@123", manager_id: "" });
  const [busy, setBusy] = useState(false);
  const [managers, setManagers] = useState([]);

  useEffect(() => {
    api.get("/employees/managers").then((r) => setManagers(r.data));
  }, []);

  const submit = async () => {
    if (!form.name || !form.email || !form.department || !form.designation) {
      toast.error("Fill all required fields"); return;
    }
    setBusy(true);
    try {
      const payload = { ...form };
      if (!payload.manager_id) delete payload.manager_id;
      await api.post("/employees", payload);
      toast.success("Employee added");
      onCreated();
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail));
    } finally { setBusy(false); }
  };

  return (
    <DialogContent className="rounded-2xl" data-testid="new-employee-dialog">
      <DialogHeader>
        <DialogTitle className="font-display">Add new employee</DialogTitle>
      </DialogHeader>
      <div className="grid grid-cols-2 gap-4 py-2">
        <div className="col-span-2">
          <Label>Full name</Label>
          <Input value={form.name} onChange={(e)=>setForm({...form, name: e.target.value})} className="mt-1.5" data-testid="ne-name" />
        </div>
        <div className="col-span-2">
          <Label>Work email</Label>
          <Input value={form.email} onChange={(e)=>setForm({...form, email: e.target.value})} className="mt-1.5" data-testid="ne-email" />
        </div>
        <div>
          <Label>Department</Label>
          <Select value={form.department} onValueChange={(v)=>setForm({...form, department: v})}>
            <SelectTrigger className="mt-1.5" data-testid="ne-dept"><SelectValue placeholder="Select" /></SelectTrigger>
            <SelectContent>
              {departments.map((d)=> <SelectItem key={d.id} value={d.name}>{d.name}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <div>
          <Label>Role</Label>
          <Select value={form.role} onValueChange={(v)=>setForm({...form, role: v})}>
            <SelectTrigger className="mt-1.5" data-testid="ne-role"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="employee">Employee</SelectItem>
              <SelectItem value="manager">Manager</SelectItem>
              <SelectItem value="hr">HR</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div>
          <Label>Designation</Label>
          <Input value={form.designation} onChange={(e)=>setForm({...form, designation: e.target.value})} className="mt-1.5" data-testid="ne-desig" />
        </div>
        <div>
          <Label>Location</Label>
          <Input value={form.location} onChange={(e)=>setForm({...form, location: e.target.value})} className="mt-1.5" />
        </div>
        <div className="col-span-2">
          <Label>Reports to</Label>
          <Select value={form.manager_id || "none"} onValueChange={(v)=>setForm({...form, manager_id: v === "none" ? "" : v})}>
            <SelectTrigger className="mt-1.5" data-testid="ne-manager"><SelectValue placeholder="Select a manager" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="none">No manager (reports directly to leadership)</SelectItem>
              {managers.map((m) => (
                <SelectItem key={m.id} value={m.id}>
                  <span className="flex items-center gap-2">
                    <span className="font-medium">{m.name}</span>
                    <span className="text-xs text-slate-500">· {m.designation}</span>
                    <span className="ml-1 text-[10px] uppercase tracking-widest px-1.5 py-0.5 rounded-md bg-slate-100 text-slate-600">{m.role === "super_admin" ? "Admin" : m.role}</span>
                  </span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className="text-xs text-slate-500 mt-1">The selected person will see this employee in their direct reports list and can approve their leave / WFH.</p>
        </div>
        <div className="col-span-2">
          <Label>Temporary password</Label>
          <Input value={form.password} onChange={(e)=>setForm({...form, password: e.target.value})} className="mt-1.5" />
          <p className="text-xs text-slate-500 mt-1">A welcome email with these credentials will be sent to the employee.</p>
        </div>
      </div>
      <DialogFooter>
        <Button onClick={submit} disabled={busy} className="bg-slate-900 hover:bg-slate-800 text-white" data-testid="ne-submit">
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : "Create"}
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}
