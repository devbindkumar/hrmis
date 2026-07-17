// MeetingRoomsPanel — Super Admin & HR manage bookable rooms in Settings.

import { useEffect, useState } from "react";
import api, { formatApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { MapPin, Users, Plus, Trash2, Pencil, Tv, PenSquare, MonitorSmartphone, Wifi, Phone, Presentation } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "@/contexts/AuthContext";

const FEATURES = [
  { key: "tv", label: "TV", icon: Tv },
  { key: "whiteboard", label: "Whiteboard", icon: PenSquare },
  { key: "video_conference", label: "Video conf", icon: MonitorSmartphone },
  { key: "projector", label: "Projector", icon: Presentation },
  { key: "phone", label: "Conference phone", icon: Phone },
  { key: "wifi", label: "Wi-Fi", icon: Wifi },
];

export default function MeetingRoomsPanel() {
  const { user } = useAuth();
  const canManage = ["super_admin", "hr"].includes(user?.role);
  const [rooms, setRooms] = useState([]);
  const [editing, setEditing] = useState(null); // null | 'new' | roomObject
  const [showInactive, setShowInactive] = useState(false);

  const load = async () => {
    const { data } = await api.get("/rooms", { params: { include_inactive: true } });
    setRooms(data);
  };
  useEffect(() => { load(); }, []);

  const removeRoom = async (r) => {
    if (!window.confirm(`Deactivate ${r.name}? Existing bookings stay but no new ones can be made.`)) return;
    try { await api.delete(`/rooms/${r.id}`); toast.success("Room deactivated"); load(); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  if (!canManage) return null;
  const visible = rooms.filter((r) => showInactive || r.active);

  return (
    <div className="surface p-6" data-testid="rooms-panel">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-2">
          <MapPin className="h-4 w-4 text-slate-500" strokeWidth={1.5} />
          <h3 className="font-display text-lg font-medium text-slate-900">Meeting rooms</h3>
        </div>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 text-xs text-slate-500">
            <Switch checked={showInactive} onCheckedChange={setShowInactive} data-testid="show-inactive-toggle" />
            Show deactivated
          </label>
          <Dialog open={editing === "new"} onOpenChange={(v) => setEditing(v ? "new" : null)}>
            <DialogTrigger asChild>
              <Button variant="outline" size="sm" className="rounded-lg" data-testid="add-room-btn">
                <Plus className="h-3.5 w-3.5 mr-1" /> Add room
              </Button>
            </DialogTrigger>
            <RoomDialog onDone={() => { setEditing(null); load(); }} />
          </Dialog>
        </div>
      </div>
      <p className="text-xs text-slate-500 mt-1">
        Rooms can be booked when scheduling meetings. Bookings longer than 2 hours or recurring meetings require HR approval.
      </p>

      <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-3">
        {visible.length === 0 ? (
          <div className="col-span-2 rounded-lg border border-dashed border-slate-300 bg-slate-50/50 p-6 text-center text-sm text-slate-500">
            No rooms yet. Click "Add room" to create one.
          </div>
        ) : visible.map((r) => (
          <div key={r.id} className={`rounded-xl border p-4 ${r.active ? "border-slate-200 bg-white" : "border-slate-200 bg-slate-50/60"}`} data-testid={`room-row-${r.id}`}>
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <div className="font-medium text-slate-900">{r.name}</div>
                  {!r.active && <Badge variant="outline" className="text-[10px] rounded-full bg-slate-100 text-slate-500 border-slate-200">Deactivated</Badge>}
                </div>
                <div className="mt-1 flex items-center gap-3 text-xs text-slate-500">
                  <span className="flex items-center gap-1"><Users className="h-3 w-3" /> {r.capacity} seats</span>
                  {r.location && <span className="flex items-center gap-1"><MapPin className="h-3 w-3" /> {r.location}</span>}
                </div>
              </div>
              {r.active && (
                <div className="flex items-center gap-1 shrink-0">
                  <Dialog open={editing?.id === r.id} onOpenChange={(v) => setEditing(v ? r : null)}>
                    <DialogTrigger asChild>
                      <button className="text-slate-400 hover:text-slate-900 p-1" data-testid={`edit-room-${r.id}`}>
                        <Pencil className="h-4 w-4" />
                      </button>
                    </DialogTrigger>
                    <RoomDialog room={r} onDone={() => { setEditing(null); load(); }} />
                  </Dialog>
                  <button onClick={() => removeRoom(r)} className="text-slate-400 hover:text-rose-600 p-1" data-testid={`delete-room-${r.id}`}>
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              )}
            </div>
            <div className="mt-3 flex flex-wrap gap-1.5">
              {r.features.length === 0
                ? <span className="text-[11px] text-slate-400">No features listed</span>
                : r.features.map((f) => {
                    const F = FEATURES.find((x) => x.key === f);
                    const Icon = F?.icon;
                    return (
                      <Badge key={f} variant="outline" className="rounded-full text-[10px] bg-slate-50 text-slate-600 border-slate-200">
                        {Icon && <Icon className="h-2.5 w-2.5 mr-1" strokeWidth={1.8} />}
                        {F?.label || f}
                      </Badge>
                    );
                  })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function RoomDialog({ room, onDone }) {
  const isEdit = !!room;
  const [form, setForm] = useState({
    name: room?.name || "",
    capacity: room?.capacity || 6,
    location: room?.location || "",
    features: room?.features || [],
  });
  const [busy, setBusy] = useState(false);

  const toggle = (k) => setForm({
    ...form,
    features: form.features.includes(k)
      ? form.features.filter((x) => x !== k)
      : [...form.features, k],
  });

  const submit = async () => {
    if (!form.name.trim()) { toast.error("Name is required"); return; }
    if (!(form.capacity > 0)) { toast.error("Capacity must be greater than 0"); return; }
    setBusy(true);
    try {
      const payload = {
        name: form.name.trim(),
        capacity: Number(form.capacity),
        features: form.features,
        location: form.location.trim(),
      };
      if (isEdit) await api.patch(`/rooms/${room.id}`, payload);
      else await api.post(`/rooms`, payload);
      toast.success(isEdit ? "Room updated" : "Room created");
      onDone();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };

  return (
    <DialogContent className="rounded-2xl" data-testid={isEdit ? `room-edit-dialog-${room.id}` : "room-new-dialog"}>
      <DialogHeader><DialogTitle className="font-display">{isEdit ? `Edit ${room.name}` : "New meeting room"}</DialogTitle></DialogHeader>
      <div className="space-y-3">
        <div>
          <Label>Name</Label>
          <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="mt-1.5" placeholder="Conference Room A" data-testid="room-name-input" />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label>Capacity</Label>
            <Input type="number" min={1} max={500} value={form.capacity} onChange={(e) => setForm({ ...form, capacity: e.target.value })} className="mt-1.5" data-testid="room-capacity-input" />
          </div>
          <div>
            <Label>Location (optional)</Label>
            <Input value={form.location} onChange={(e) => setForm({ ...form, location: e.target.value })} className="mt-1.5" placeholder="1st floor" data-testid="room-location-input" />
          </div>
        </div>
        <div>
          <Label>Features</Label>
          <div className="mt-1.5 grid grid-cols-2 gap-1.5">
            {FEATURES.map((f) => (
              <label key={f.key} className="flex items-center gap-2 px-2.5 py-2 rounded-lg border border-slate-200 hover:border-slate-300 hover:bg-slate-50 cursor-pointer" data-testid={`feature-${f.key}`}>
                <Checkbox checked={form.features.includes(f.key)} onCheckedChange={() => toggle(f.key)} />
                <f.icon className="h-3.5 w-3.5 text-slate-500" strokeWidth={1.75} />
                <span className="text-sm text-slate-700">{f.label}</span>
              </label>
            ))}
          </div>
        </div>
      </div>
      <DialogFooter>
        <Button onClick={submit} disabled={busy} className="bg-slate-900 hover:bg-slate-800 text-white" data-testid="room-submit">
          {isEdit ? "Save" : "Create"}
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}
