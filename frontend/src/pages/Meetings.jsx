import { useEffect, useState } from "react";
import api, { formatApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import {
  Calendar as CalIcon, Plus, Video, MapPin, Users, Trash2, Repeat,
  AlertTriangle, ShieldCheck, Clock3, Tv, PenSquare, MonitorSmartphone, Wifi, Phone, Presentation, Check, X,
} from "lucide-react";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { toast } from "sonner";
import { Checkbox } from "@/components/ui/checkbox";
import { useAuth } from "@/contexts/AuthContext";

const FEATURE_ICONS = {
  tv: Tv, whiteboard: PenSquare, video_conference: MonitorSmartphone,
  projector: Presentation, phone: Phone, wifi: Wifi,
};
const FEATURE_LABELS = {
  tv: "TV", whiteboard: "Whiteboard", video_conference: "Video conf",
  projector: "Projector", phone: "Phone", wifi: "Wi-Fi",
};

export default function Meetings() {
  const { user } = useAuth();
  const canApprove = ["super_admin", "hr"].includes(user?.role);
  const [tab, setTab] = useState("mine");
  const [list, setList] = useState([]);
  const [pending, setPending] = useState([]);
  const [employees, setEmployees] = useState([]);
  const [rooms, setRooms] = useState([]);
  const [open, setOpen] = useState(false);

  const load = async () => {
    const [m, e, r] = await Promise.all([
      api.get("/meetings", { params: { scope: "mine" } }),
      api.get("/employees"),
      api.get("/rooms"),
    ]);
    setList(m.data);
    setEmployees(e.data);
    setRooms(r.data);
    if (canApprove) {
      try {
        const p = await api.get("/meetings/pending-approval");
        setPending(p.data);
      } catch { /* noop */ }
    }
  };
  useEffect(() => { load(); }, []); // eslint-disable-line

  const remove = async (id) => {
    if (!window.confirm("Cancel this meeting?")) return;
    try { await api.delete(`/meetings/${id}`); toast.success("Meeting cancelled"); load(); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  const upcoming = list.filter((m) => m.status === "scheduled"
    && m.approval_status !== "rejected"
    && new Date(m.ends_at) >= new Date());
  const past = list.filter((m) => m.status !== "scheduled"
    || m.approval_status === "rejected"
    || new Date(m.ends_at) < new Date());

  return (
    <div className="p-6 space-y-5 animate-fade-up" data-testid="meetings-page">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="font-display text-3xl font-semibold tracking-tight text-slate-900">Meetings</h1>
          <p className="text-sm text-slate-500 mt-1">Book a room, invite the team, HR handles the exceptions.</p>
        </div>
        <div className="flex items-center gap-2">
          {canApprove && (
            <Tabs value={tab} onValueChange={setTab}>
              <TabsList>
                <TabsTrigger value="mine" data-testid="tab-mine">My meetings</TabsTrigger>
                <TabsTrigger value="approvals" data-testid="tab-approvals">
                  Pending approval {pending.length > 0 && <Badge className="ml-1.5 bg-amber-500 text-white rounded-full h-5 min-w-5 px-1.5">{pending.length}</Badge>}
                </TabsTrigger>
              </TabsList>
            </Tabs>
          )}
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
              <Button className="bg-slate-900 hover:bg-slate-800 text-white rounded-lg" data-testid="new-meeting-btn">
                <Plus className="h-4 w-4 mr-1.5" /> Schedule meeting
              </Button>
            </DialogTrigger>
            <NewMeetingDialog
              employees={employees.filter((e) => e.user_id !== user?.id)}
              rooms={rooms}
              onCreated={() => { setOpen(false); load(); }}
            />
          </Dialog>
        </div>
      </div>

      {tab === "approvals" && canApprove ? (
        <ApprovalsQueue items={pending} onDecide={load} />
      ) : (
        <>
          <section>
            <h2 className="text-xs uppercase tracking-widest text-slate-400 font-semibold mb-3">Upcoming</h2>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {upcoming.length === 0
                ? <div className="surface p-8 text-center text-slate-400 text-sm md:col-span-3">No upcoming meetings.</div>
                : upcoming.map((m) => (
                    <MeetingCard key={m.id} m={m} canCancel={m.created_by === user?.id || canApprove} onCancel={() => remove(m.id)} employees={employees} />
                  ))}
            </div>
          </section>

          {past.length > 0 && (
            <section>
              <h2 className="text-xs uppercase tracking-widest text-slate-400 font-semibold mb-3">Past</h2>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {past.map((m) => <MeetingCard key={m.id} m={m} past employees={employees} />)}
              </div>
            </section>
          )}
        </>
      )}
    </div>
  );
}

function statusBadge(m) {
  if (m.status === "cancelled") return { label: "Cancelled", cls: "bg-slate-100 text-slate-500 border-slate-200" };
  const s = m.approval_status;
  if (s === "pending") return { label: "Pending HR approval", cls: "bg-amber-50 text-amber-700 border-amber-200" };
  if (s === "approved") return { label: "Approved", cls: "bg-emerald-50 text-emerald-700 border-emerald-200" };
  if (s === "rejected") return { label: "Rejected", cls: "bg-rose-50 text-rose-700 border-rose-200" };
  return null;
}

function MeetingCard({ m, canCancel, onCancel, past, employees }) {
  const start = new Date(m.starts_at);
  const end = new Date(m.ends_at);
  const attendees = employees.filter((e) => m.attendee_user_ids?.includes(e.user_id));
  const badge = statusBadge(m);
  return (
    <div className={`surface p-5 card-hover ${past ? "opacity-70" : ""}`} data-testid={`meeting-card-${m.id}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 text-xs uppercase tracking-widest font-semibold text-blue-600">
            <CalIcon className="h-3.5 w-3.5" strokeWidth={1.5} />
            {start.toLocaleDateString(undefined, { month: "short", day: "numeric", weekday: "short" })}
          </div>
          <div className="flex items-start justify-between gap-2 mt-2">
            <h3 className="font-display text-lg font-medium text-slate-900 leading-snug break-words">{m.title}</h3>
          </div>
          <div className="text-xs text-slate-500 mt-1">
            {start.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} → {end.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
            {typeof m.duration_minutes === "number" && <> · {m.duration_minutes}m</>}
          </div>
          {m.description && <p className="text-sm text-slate-600 mt-2 line-clamp-3">{m.description}</p>}
          <div className="mt-3 flex flex-wrap items-center gap-1.5">
            {badge && (
              <Badge variant="outline" className={`rounded-full font-medium text-[10px] ${badge.cls}`}>{badge.label}</Badge>
            )}
            {m.is_recurring && (
              <Badge variant="outline" className="rounded-full font-medium text-[10px] bg-indigo-50 text-indigo-700 border-indigo-200">
                <Repeat className="h-2.5 w-2.5 mr-1" /> Recurring
              </Badge>
            )}
          </div>
        </div>
        {canCancel && (
          <button onClick={onCancel} className="text-slate-400 hover:text-rose-600 shrink-0" data-testid={`cancel-meeting-${m.id}`}>
            <Trash2 className="h-4 w-4" />
          </button>
        )}
      </div>
      <div className="mt-4 flex items-center justify-between border-t border-slate-100 pt-3">
        <div className="flex items-center gap-1.5 text-xs text-slate-500 min-w-0">
          {m.room_name ? (
            <><MapPin className="h-3.5 w-3.5 shrink-0" /> <span className="truncate">{m.room_name}</span></>
          ) : m.location?.toLowerCase() === "online" ? (
            <><Video className="h-3.5 w-3.5" /> Online</>
          ) : (
            <><MapPin className="h-3.5 w-3.5" /> {m.location}</>
          )}
        </div>
        <div className="flex items-center gap-1">
          {attendees.slice(0, 4).map((a) => (
            <Avatar key={a.id} className="h-6 w-6 ring-2 ring-white -ml-1.5">
              <AvatarImage src={a.avatar_url} />
              <AvatarFallback className="text-[10px] bg-slate-100">{a.name.split(" ").map(p => p[0]).slice(0, 2).join("")}</AvatarFallback>
            </Avatar>
          ))}
          {attendees.length > 4 && <span className="text-xs text-slate-500 ml-1">+{attendees.length - 4}</span>}
          {attendees.length === 0 && <span className="text-xs text-slate-400 flex items-center gap-1"><Users className="h-3 w-3" /> just you</span>}
        </div>
      </div>
    </div>
  );
}

function ApprovalsQueue({ items, onDecide }) {
  const [decision, setDecision] = useState(null); // { id, action, title }
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!decision) return;
    setBusy(true);
    try {
      await api.post(`/meetings/${decision.id}/${decision.action}`, { note });
      toast.success(decision.action === "approve" ? "Meeting approved & invites sent" : "Meeting rejected");
      setDecision(null); setNote(""); onDecide();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };

  return (
    <>
      <div className="surface p-0 overflow-hidden" data-testid="approvals-queue">
        {items.length === 0 ? (
          <div className="p-10 text-center">
            <ShieldCheck className="h-8 w-8 mx-auto text-slate-300" strokeWidth={1.25} />
            <div className="mt-2 text-sm text-slate-500">No meetings awaiting approval.</div>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-slate-50 text-slate-500 text-xs uppercase tracking-wide">
                <th className="text-left font-semibold px-5 py-3">Meeting</th>
                <th className="text-left font-semibold px-5 py-3">Requested by</th>
                <th className="text-left font-semibold px-5 py-3">Room</th>
                <th className="text-left font-semibold px-5 py-3">When</th>
                <th className="text-left font-semibold px-5 py-3">Reason</th>
                <th className="px-5 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {items.map((m) => (
                <tr key={m.id} data-testid={`pending-row-${m.id}`}>
                  <td className="px-5 py-3 text-slate-900 font-medium">{m.title}</td>
                  <td className="px-5 py-3 text-slate-600">{m.created_by_name}</td>
                  <td className="px-5 py-3 text-slate-600">{m.room_name || "—"}</td>
                  <td className="px-5 py-3 text-slate-600 whitespace-nowrap">
                    <div>{new Date(m.starts_at).toLocaleDateString(undefined, { month: "short", day: "numeric" })}</div>
                    <div className="text-xs text-slate-500">
                      {new Date(m.starts_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} → {new Date(m.ends_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} ({m.duration_minutes}m)
                    </div>
                  </td>
                  <td className="px-5 py-3">
                    {m.is_recurring
                      ? <Badge variant="outline" className="text-[10px] rounded-full bg-indigo-50 text-indigo-700 border-indigo-200"><Repeat className="h-2.5 w-2.5 mr-1" /> Recurring</Badge>
                      : <Badge variant="outline" className="text-[10px] rounded-full bg-amber-50 text-amber-700 border-amber-200"><Clock3 className="h-2.5 w-2.5 mr-1" /> {m.duration_minutes}m {'>'} 2h</Badge>}
                  </td>
                  <td className="px-5 py-3 text-right whitespace-nowrap">
                    <Button size="sm" variant="outline" className="text-emerald-700 border-emerald-200 hover:bg-emerald-50 mr-1.5"
                            onClick={() => { setDecision({ id: m.id, action: "approve", title: m.title }); setNote(""); }}
                            data-testid={`approve-meeting-${m.id}`}>
                      <Check className="h-3.5 w-3.5 mr-1" /> Approve
                    </Button>
                    <Button size="sm" variant="outline" className="text-rose-700 border-rose-200 hover:bg-rose-50"
                            onClick={() => { setDecision({ id: m.id, action: "reject", title: m.title }); setNote(""); }}
                            data-testid={`reject-meeting-${m.id}`}>
                      <X className="h-3.5 w-3.5 mr-1" /> Reject
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <Dialog open={!!decision} onOpenChange={(v) => !v && setDecision(null)}>
        <DialogContent className="rounded-2xl" data-testid="meeting-decision-dialog">
          <DialogHeader>
            <DialogTitle className="font-display">
              {decision?.action === "approve" ? "Approve meeting" : "Reject meeting"}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div className="text-sm text-slate-700">"{decision?.title}"</div>
            <div>
              <Label>Note {decision?.action === "reject" ? "(shown to the requester)" : "(optional)"}</Label>
              <Textarea value={note} onChange={(e) => setNote(e.target.value)} rows={3} className="mt-1.5" data-testid="decision-note-input" />
            </div>
          </div>
          <DialogFooter>
            <Button onClick={submit} disabled={busy}
                    className={decision?.action === "approve" ? "bg-emerald-600 hover:bg-emerald-700 text-white" : "bg-rose-600 hover:bg-rose-700 text-white"}
                    data-testid="decision-submit">
              {decision?.action === "approve" ? "Approve & notify" : "Reject"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

function NewMeetingDialog({ employees, rooms, onCreated }) {
  const initStart = new Date();
  initStart.setMinutes(0, 0, 0);
  initStart.setHours(initStart.getHours() + 1);
  const initEnd = new Date(initStart);
  initEnd.setMinutes(30);

  const toLocal = (d) => {
    const off = d.getTimezoneOffset() * 60000;
    return new Date(d.getTime() - off).toISOString().slice(0, 16);
  };
  const [form, setForm] = useState({
    title: "",
    description: "",
    starts_at: toLocal(initStart),
    ends_at: toLocal(initEnd),
    location: "Online",
    room_id: "",
    is_recurring: false,
    recurrence: { frequency: "weekly", count: 4 },
    attendee_user_ids: [],
  });
  const [conflict, setConflict] = useState(null);
  const [checking, setChecking] = useState(false);

  // duration in minutes (frontend guard so the banner matches server)
  const durationMinutes = (() => {
    try {
      const ms = new Date(form.ends_at).getTime() - new Date(form.starts_at).getTime();
      return Math.max(0, Math.floor(ms / 60000));
    } catch { return 0; }
  })();
  const needsApproval = durationMinutes > 120 || form.is_recurring;
  const selectedRoom = rooms.find((r) => r.id === form.room_id);

  // Live conflict check whenever room + times change
  useEffect(() => {
    if (!form.room_id || !form.starts_at || !form.ends_at) { setConflict(null); return; }
    if (new Date(form.ends_at) <= new Date(form.starts_at)) { setConflict(null); return; }
    let cancelled = false;
    setChecking(true);
    const t = setTimeout(async () => {
      try {
        const { data } = await api.post("/rooms/check-conflict", {
          room_id: form.room_id,
          starts_at: new Date(form.starts_at).toISOString(),
          ends_at: new Date(form.ends_at).toISOString(),
        });
        if (!cancelled) setConflict(data.available ? null : data.conflict);
      } catch { /* noop */ }
      finally { if (!cancelled) setChecking(false); }
    }, 350);
    return () => { cancelled = true; clearTimeout(t); };
  }, [form.room_id, form.starts_at, form.ends_at]);

  const submit = async () => {
    if (!form.title) { toast.error("Add a title"); return; }
    if (new Date(form.ends_at) <= new Date(form.starts_at)) { toast.error("End must be after start"); return; }
    if (conflict) { toast.error("Room conflict — pick a different slot or room"); return; }
    if (selectedRoom && form.attendee_user_ids.length + 1 > selectedRoom.capacity) {
      toast.error(`${selectedRoom.name} seats ${selectedRoom.capacity} — you've invited ${form.attendee_user_ids.length + 1}`);
      return;
    }
    try {
      const payload = {
        title: form.title,
        description: form.description,
        starts_at: new Date(form.starts_at).toISOString(),
        ends_at: new Date(form.ends_at).toISOString(),
        location: form.location || (selectedRoom ? selectedRoom.name : "Online"),
        room_id: form.room_id || null,
        attendee_user_ids: form.attendee_user_ids,
        is_recurring: form.is_recurring,
        recurrence: form.is_recurring ? form.recurrence : null,
      };
      const { data } = await api.post("/meetings", payload);
      if (data.approval_status === "pending") {
        toast.success("Meeting submitted — HR will review it shortly.");
      } else {
        toast.success("Meeting scheduled & invites sent");
      }
      onCreated();
    } catch (e) {
      const detail = e.response?.data?.detail;
      if (e.response?.status === 409 && detail?.message) toast.error(detail.message);
      else toast.error(formatApiError(detail));
    }
  };

  const toggle = (uid) => setForm({
    ...form,
    attendee_user_ids: form.attendee_user_ids.includes(uid)
      ? form.attendee_user_ids.filter((x) => x !== uid)
      : [...form.attendee_user_ids, uid],
  });

  return (
    <DialogContent className="rounded-2xl max-w-2xl" data-testid="new-meeting-dialog">
      <DialogHeader><DialogTitle className="font-display">Schedule meeting</DialogTitle></DialogHeader>
      <div className="space-y-3 max-h-[70vh] overflow-y-auto pr-1">
        <div>
          <Label>Title</Label>
          <Input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} className="mt-1.5" data-testid="meeting-title" />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div><Label>Starts</Label><Input type="datetime-local" value={form.starts_at} onChange={(e) => setForm({ ...form, starts_at: e.target.value })} className="mt-1.5" data-testid="meeting-start" /></div>
          <div><Label>Ends</Label><Input type="datetime-local" value={form.ends_at} onChange={(e) => setForm({ ...form, ends_at: e.target.value })} className="mt-1.5" data-testid="meeting-end" /></div>
        </div>

        <div>
          <Label>Meeting room</Label>
          <Select value={form.room_id || "__none__"} onValueChange={(v) => setForm({ ...form, room_id: v === "__none__" ? "" : v })}>
            <SelectTrigger className="mt-1.5" data-testid="meeting-room-select"><SelectValue placeholder="No room (online / anywhere)" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="__none__">
                <div className="flex items-center gap-2 text-slate-500"><Video className="h-3.5 w-3.5" /> Online / no room</div>
              </SelectItem>
              {rooms.map((r) => (
                <SelectItem key={r.id} value={r.id}>
                  <div className="flex items-center gap-2">
                    <MapPin className="h-3.5 w-3.5 text-slate-500" />
                    <span>{r.name}</span>
                    <span className="text-xs text-slate-400">· {r.capacity} seats</span>
                  </div>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {selectedRoom && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {selectedRoom.features.map((f) => {
                const Icon = FEATURE_ICONS[f];
                return (
                  <Badge key={f} variant="outline" className="text-[10px] rounded-full bg-slate-50 text-slate-600 border-slate-200">
                    {Icon && <Icon className="h-2.5 w-2.5 mr-1" strokeWidth={1.8} />}
                    {FEATURE_LABELS[f] || f}
                  </Badge>
                );
              })}
              {selectedRoom.location && <Badge variant="outline" className="text-[10px] rounded-full bg-slate-50 text-slate-600 border-slate-200">{selectedRoom.location}</Badge>}
            </div>
          )}
          {conflict && (
            <div className="mt-2 rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs text-rose-800 flex items-start gap-2" data-testid="room-conflict-banner">
              <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
              <div>
                <b>Room already booked</b> — {conflict.title} by {conflict.created_by_name} from
                {" "}{new Date(conflict.starts_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} to {" "}
                {new Date(conflict.ends_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}.
                Pick a different slot or room.
              </div>
            </div>
          )}
          {!conflict && selectedRoom && !checking && form.room_id && (
            <div className="mt-2 text-[11px] text-emerald-700 flex items-center gap-1" data-testid="room-available-hint">
              <ShieldCheck className="h-3.5 w-3.5" /> {selectedRoom.name} is available for this slot
            </div>
          )}
        </div>

        <div>
          <label className="flex items-center gap-2 cursor-pointer text-sm text-slate-700">
            <Checkbox checked={form.is_recurring} onCheckedChange={(v) => setForm({ ...form, is_recurring: !!v })} data-testid="meeting-recurring" />
            <Repeat className="h-3.5 w-3.5 text-slate-500" />
            Repeat this meeting
          </label>
          {form.is_recurring && (
            <div className="mt-2 grid grid-cols-2 gap-3">
              <Select value={form.recurrence.frequency} onValueChange={(v) => setForm({ ...form, recurrence: { ...form.recurrence, frequency: v } })}>
                <SelectTrigger data-testid="recurrence-frequency"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="daily">Every weekday</SelectItem>
                  <SelectItem value="weekly">Weekly</SelectItem>
                  <SelectItem value="biweekly">Every 2 weeks</SelectItem>
                  <SelectItem value="monthly">Monthly</SelectItem>
                </SelectContent>
              </Select>
              <div className="flex items-center gap-2">
                <Input type="number" min={1} max={52}
                       value={form.recurrence.count}
                       onChange={(e) => setForm({ ...form, recurrence: { ...form.recurrence, count: Number(e.target.value) } })}
                       data-testid="recurrence-count" />
                <span className="text-xs text-slate-500">occurrences</span>
              </div>
            </div>
          )}
        </div>

        {needsApproval && (
          <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800 flex items-start gap-2" data-testid="approval-banner">
            <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
            <div>
              <b>HR approval required</b> — {form.is_recurring ? "recurring meetings" : `bookings longer than 2 hours (${durationMinutes}m)`} need
              HR sign-off. Invites will be sent once HR approves.
            </div>
          </div>
        )}

        <div>
          <Label>Description (optional)</Label>
          <Textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} className="mt-1.5 min-h-[70px]" data-testid="meeting-description" />
        </div>
        <div>
          <Label>Invite teammates</Label>
          <div className="mt-1.5 max-h-44 overflow-y-auto rounded-lg border border-slate-200 divide-y divide-slate-50" data-testid="invitee-list">
            {employees.map((e) => (
              <label key={e.user_id} className="flex items-center gap-3 px-3 py-2 hover:bg-slate-50 cursor-pointer">
                <Checkbox checked={form.attendee_user_ids.includes(e.user_id)} onCheckedChange={() => toggle(e.user_id)} />
                <Avatar className="h-6 w-6"><AvatarImage src={e.avatar_url} /><AvatarFallback className="text-[10px]">{e.name.split(" ").map(p => p[0]).slice(0, 2).join("")}</AvatarFallback></Avatar>
                <div className="text-sm">
                  <div className="text-slate-900">{e.name}</div>
                  <div className="text-xs text-slate-500">{e.designation}</div>
                </div>
              </label>
            ))}
          </div>
          {selectedRoom && form.attendee_user_ids.length + 1 > selectedRoom.capacity && (
            <div className="mt-2 text-[11px] text-amber-700">
              {selectedRoom.name} seats {selectedRoom.capacity} — you've invited {form.attendee_user_ids.length + 1} people.
            </div>
          )}
        </div>
      </div>
      <DialogFooter>
        <Button onClick={submit}
                disabled={!!conflict}
                className="bg-slate-900 hover:bg-slate-800 text-white disabled:opacity-50"
                data-testid="meeting-submit">
          {needsApproval ? "Submit for approval" : "Schedule"}
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}
