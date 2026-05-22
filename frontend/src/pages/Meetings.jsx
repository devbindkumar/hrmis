import { useEffect, useState } from "react";
import api, { formatApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Calendar as CalIcon, Plus, Video, MapPin, Users, Trash2 } from "lucide-react";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { toast } from "sonner";
import { Checkbox } from "@/components/ui/checkbox";
import { useAuth } from "@/contexts/AuthContext";

export default function Meetings() {
  const { user } = useAuth();
  const [list, setList] = useState([]);
  const [employees, setEmployees] = useState([]);
  const [open, setOpen] = useState(false);

  const load = () => api.get("/meetings", { params: { scope: "mine" } }).then((r)=>setList(r.data));
  useEffect(() => {
    load();
    api.get("/employees").then((r)=>setEmployees(r.data));
  }, []);

  const remove = async (id) => {
    if (!window.confirm("Cancel this meeting?")) return;
    try { await api.delete(`/meetings/${id}`); toast.success("Meeting cancelled"); load(); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  const upcoming = list.filter((m) => m.status === "scheduled" && new Date(m.ends_at) >= new Date());
  const past = list.filter((m) => m.status !== "scheduled" || new Date(m.ends_at) < new Date());

  return (
    <div className="p-6 space-y-5 animate-fade-up" data-testid="meetings-page">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="font-display text-3xl font-semibold tracking-tight text-slate-900">Meetings</h1>
          <p className="text-sm text-slate-500 mt-1">Your invites, your own meetings, and what's next.</p>
        </div>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button className="bg-slate-900 hover:bg-slate-800 text-white rounded-lg" data-testid="new-meeting-btn"><Plus className="h-4 w-4 mr-1.5" /> Schedule meeting</Button>
          </DialogTrigger>
          <NewMeetingDialog employees={employees.filter((e) => e.user_id !== user?.id)} onCreated={() => { setOpen(false); load(); }} />
        </Dialog>
      </div>

      <section>
        <h2 className="text-xs uppercase tracking-widest text-slate-400 font-semibold mb-3">Upcoming</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {upcoming.length === 0 ? <div className="surface p-8 text-center text-slate-400 text-sm md:col-span-3">No upcoming meetings.</div> :
            upcoming.map((m) => <MeetingCard key={m.id} m={m} canCancel={m.created_by === user?.id || ['super_admin','hr'].includes(user?.role)} onCancel={()=>remove(m.id)} employees={employees} />)}
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
    </div>
  );
}

function MeetingCard({ m, canCancel, onCancel, past, employees }) {
  const start = new Date(m.starts_at);
  const end = new Date(m.ends_at);
  const attendees = employees.filter((e) => m.attendee_user_ids?.includes(e.user_id));
  return (
    <div className={`surface p-5 card-hover ${past ? 'opacity-70' : ''}`}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-xs uppercase tracking-widest font-semibold text-blue-600">
            <CalIcon className="h-3.5 w-3.5" strokeWidth={1.5} />
            {start.toLocaleDateString(undefined, { month: 'short', day: 'numeric', weekday: 'short' })}
          </div>
          <h3 className="font-display text-lg font-medium text-slate-900 mt-2 leading-snug">{m.title}</h3>
          <div className="text-xs text-slate-500 mt-1">
            {start.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} → {end.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
          </div>
          {m.description && <p className="text-sm text-slate-600 mt-2 line-clamp-3">{m.description}</p>}
        </div>
        {canCancel && (
          <button onClick={onCancel} className="text-slate-400 hover:text-rose-600" data-testid={`cancel-meeting-${m.id}`}>
            <Trash2 className="h-4 w-4" />
          </button>
        )}
      </div>
      <div className="mt-4 flex items-center justify-between border-t border-slate-100 pt-3">
        <div className="flex items-center gap-1.5 text-xs text-slate-500">
          {m.location?.toLowerCase() === 'online' ? <Video className="h-3.5 w-3.5" /> : <MapPin className="h-3.5 w-3.5" />}
          {m.location}
        </div>
        <div className="flex items-center gap-1">
          {attendees.slice(0, 4).map((a) => (
            <Avatar key={a.id} className="h-6 w-6 ring-2 ring-white -ml-1.5">
              <AvatarImage src={a.avatar_url} />
              <AvatarFallback className="text-[10px] bg-slate-100">{a.name.split(" ").map(p=>p[0]).slice(0,2).join("")}</AvatarFallback>
            </Avatar>
          ))}
          {attendees.length > 4 && <span className="text-xs text-slate-500 ml-1">+{attendees.length - 4}</span>}
          {attendees.length === 0 && <span className="text-xs text-slate-400 flex items-center gap-1"><Users className="h-3 w-3" /> just you</span>}
        </div>
      </div>
    </div>
  );
}

function NewMeetingDialog({ employees, onCreated }) {
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
    attendee_user_ids: [],
  });

  const submit = async () => {
    if (!form.title) { toast.error("Add a title"); return; }
    try {
      await api.post("/meetings", {
        ...form,
        starts_at: new Date(form.starts_at).toISOString(),
        ends_at: new Date(form.ends_at).toISOString(),
      });
      toast.success("Meeting scheduled & invites sent");
      onCreated();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  const toggle = (uid) => setForm({
    ...form,
    attendee_user_ids: form.attendee_user_ids.includes(uid)
      ? form.attendee_user_ids.filter((x) => x !== uid)
      : [...form.attendee_user_ids, uid],
  });

  return (
    <DialogContent className="rounded-2xl max-w-xl">
      <DialogHeader><DialogTitle className="font-display">Schedule meeting</DialogTitle></DialogHeader>
      <div className="space-y-3">
        <div>
          <Label>Title</Label>
          <Input value={form.title} onChange={(e)=>setForm({...form, title: e.target.value})} className="mt-1.5" data-testid="meeting-title" />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div><Label>Starts</Label><Input type="datetime-local" value={form.starts_at} onChange={(e)=>setForm({...form, starts_at: e.target.value})} className="mt-1.5" data-testid="meeting-start" /></div>
          <div><Label>Ends</Label><Input type="datetime-local" value={form.ends_at} onChange={(e)=>setForm({...form, ends_at: e.target.value})} className="mt-1.5" data-testid="meeting-end" /></div>
        </div>
        <div>
          <Label>Location</Label>
          <Input value={form.location} onChange={(e)=>setForm({...form, location: e.target.value})} className="mt-1.5" placeholder="Online, Conference Room A…" />
        </div>
        <div>
          <Label>Description (optional)</Label>
          <Textarea value={form.description} onChange={(e)=>setForm({...form, description: e.target.value})} className="mt-1.5 min-h-[70px]" />
        </div>
        <div>
          <Label>Invite teammates</Label>
          <div className="mt-1.5 max-h-44 overflow-y-auto rounded-lg border border-slate-200 divide-y divide-slate-50" data-testid="invitee-list">
            {employees.map((e) => (
              <label key={e.user_id} className="flex items-center gap-3 px-3 py-2 hover:bg-slate-50 cursor-pointer">
                <Checkbox checked={form.attendee_user_ids.includes(e.user_id)} onCheckedChange={()=>toggle(e.user_id)} />
                <Avatar className="h-6 w-6"><AvatarImage src={e.avatar_url} /><AvatarFallback className="text-[10px]">{e.name.split(" ").map(p=>p[0]).slice(0,2).join("")}</AvatarFallback></Avatar>
                <div className="text-sm">
                  <div className="text-slate-900">{e.name}</div>
                  <div className="text-xs text-slate-500">{e.designation}</div>
                </div>
              </label>
            ))}
          </div>
        </div>
      </div>
      <DialogFooter><Button onClick={submit} className="bg-slate-900 hover:bg-slate-800 text-white" data-testid="meeting-submit">Schedule</Button></DialogFooter>
    </DialogContent>
  );
}
