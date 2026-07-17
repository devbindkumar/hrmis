// RoomAvailability — compact day-of grid: rooms as rows, hours as columns.
// Booked slots render as blocks; clicking an empty area opens the Schedule
// Meeting dialog pre-filled with that room + 30-min slot.

import { useEffect, useMemo, useState, useRef } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import api, { formatApiError } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";
import {
  ChevronLeft, ChevronRight, CalendarClock, Users, MapPin, Clock3, Repeat,
  Tv, PenSquare, MonitorSmartphone, Wifi, Phone, Presentation,
} from "lucide-react";

const START_HOUR = 8;      // grid starts at 08:00 local
const END_HOUR = 20;       // grid ends at 20:00 local
const SLOT_MINUTES = 30;   // clickable slot granularity
const ROW_HEIGHT = 44;     // px

const FEATURE_ICONS = {
  tv: Tv, whiteboard: PenSquare, video_conference: MonitorSmartphone,
  projector: Presentation, phone: Phone, wifi: Wifi,
};

function toLocalDate(iso) {
  return new Date(iso);
}
function ymd(d) {
  return d.toISOString().slice(0, 10);
}
function shiftDay(dateStr, delta) {
  const d = new Date(dateStr + "T12:00:00");
  d.setDate(d.getDate() + delta);
  return ymd(d);
}
function fmtTime(d) {
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export default function RoomAvailability() {
  const nav = useNavigate();
  const { user } = useAuth();
  const meetingsBase = user?.role === "employee" ? "/employee/meetings" : "/admin/meetings";
  const [params, setParams] = useSearchParams();
  const paramDate = params.get("date");
  const [date, setDate] = useState(paramDate || ymd(new Date()));
  const [data, setData] = useState({ rooms: [] });
  const [hoverSlot, setHoverSlot] = useState(null); // {roomId, minute}
  const containerRef = useRef(null);

  useEffect(() => {
    setParams((p) => { p.set("date", date); return p; }, { replace: true });
    api.get("/rooms/day-schedule", { params: { date } })
      .then((r) => setData(r.data))
      .catch((e) => toast.error(formatApiError(e.response?.data?.detail)));
  }, [date]); // eslint-disable-line

  const hours = useMemo(() => {
    const arr = [];
    for (let h = START_HOUR; h <= END_HOUR; h++) arr.push(h);
    return arr;
  }, []);
  const totalMinutes = (END_HOUR - START_HOUR) * 60;

  // Compute now-line position (only when viewing today)
  const [nowMin, setNowMin] = useState(null);
  useEffect(() => {
    const compute = () => {
      const today = ymd(new Date());
      if (date !== today) { setNowMin(null); return; }
      const d = new Date();
      const m = d.getHours() * 60 + d.getMinutes() - START_HOUR * 60;
      setNowMin(m >= 0 && m <= totalMinutes ? m : null);
    };
    compute();
    const t = setInterval(compute, 60000);
    return () => clearInterval(t);
  }, [date, totalMinutes]);

  const bookingToBlock = (b) => {
    const s = toLocalDate(b.starts_at);
    const e = toLocalDate(b.ends_at);
    const startMin = s.getHours() * 60 + s.getMinutes() - START_HOUR * 60;
    const endMin = e.getHours() * 60 + e.getMinutes() - START_HOUR * 60;
    const left = Math.max(0, startMin) / totalMinutes * 100;
    const width = Math.min(totalMinutes, endMin - Math.max(0, startMin)) / totalMinutes * 100;
    return { left, width, startMin, endMin, s, e };
  };

  const openBooking = (roomId, minute) => {
    // Pre-fill Meetings dialog by passing query params
    const d = new Date(date + "T00:00:00");
    d.setMinutes(START_HOUR * 60 + minute);
    const startISO = new Date(d).toISOString();
    const endD = new Date(d); endD.setMinutes(endD.getMinutes() + 30);
    const endISO = new Date(endD).toISOString();
    nav(`${meetingsBase}?new=1&room_id=${roomId}&start=${encodeURIComponent(startISO)}&end=${encodeURIComponent(endISO)}`);
  };

  const goto = (delta) => setDate(shiftDay(date, delta));
  const parsedDate = new Date(date + "T12:00:00");
  const isToday = date === ymd(new Date());
  const isWeekend = [0, 6].includes(parsedDate.getDay());

  return (
    <div className="p-6 space-y-5 animate-fade-up" data-testid="room-availability">
      {/* Header */}
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="font-display text-3xl font-semibold tracking-tight text-slate-900">Room availability</h1>
          <p className="text-sm text-slate-500 mt-1">
            Click any empty slot to book a 30-minute meeting.{" "}
            {isWeekend && <span className="text-amber-700">Weekend</span>}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="icon" className="rounded-lg" onClick={() => goto(-1)} data-testid="prev-day">
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <div className="flex items-center gap-2 h-10 rounded-lg border border-slate-200 px-3">
            <CalendarClock className="h-4 w-4 text-slate-400" strokeWidth={1.5} />
            <Input type="date" value={date} onChange={(e) => setDate(e.target.value)}
                   className="h-8 border-0 shadow-none focus-visible:ring-0 px-0 w-40" data-testid="date-picker" />
          </div>
          <Button variant="outline" size="icon" className="rounded-lg" onClick={() => goto(1)} data-testid="next-day">
            <ChevronRight className="h-4 w-4" />
          </Button>
          <Button variant="outline" onClick={() => setDate(ymd(new Date()))}
                  className="rounded-lg text-slate-600" disabled={isToday} data-testid="today-btn">
            Today
          </Button>
        </div>
      </div>

      {/* Human-readable date banner */}
      <div className="text-lg font-display text-slate-700">
        {parsedDate.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric", year: "numeric" })}
      </div>

      {/* Grid */}
      <div ref={containerRef} className="surface p-0 overflow-hidden" data-testid="room-grid">
        {/* Hour axis */}
        <div className="flex border-b border-slate-100 sticky top-0 bg-white z-10">
          <div className="w-48 shrink-0 px-4 py-2 border-r border-slate-100 text-xs uppercase tracking-widest text-slate-400 font-semibold">
            Room
          </div>
          <div className="relative flex-1">
            <div className="flex">
              {hours.map((h) => (
                <div key={h} className="flex-1 border-l border-slate-100 py-2 pl-1">
                  <span className="text-[11px] text-slate-500 tabular-nums">
                    {String(h).padStart(2, "0")}:00
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {data.rooms.length === 0 ? (
          <div className="p-10 text-center text-sm text-slate-500">No active meeting rooms.</div>
        ) : data.rooms.map((r) => (
          <div key={r.id} className="flex border-b border-slate-100 last:border-b-0" data-testid={`grid-row-${r.id}`}>
            {/* Room label */}
            <div className="w-48 shrink-0 px-4 py-3 border-r border-slate-100 flex flex-col gap-1">
              <div className="font-medium text-slate-900 text-sm truncate">{r.name}</div>
              <div className="flex items-center gap-1.5 text-[11px] text-slate-500">
                <Users className="h-3 w-3" />
                <span>{r.capacity}</span>
                {r.location && <><MapPin className="h-3 w-3 ml-1" /><span className="truncate">{r.location}</span></>}
              </div>
              <div className="flex flex-wrap gap-1">
                {r.features.slice(0, 3).map((f) => {
                  const Icon = FEATURE_ICONS[f];
                  return Icon ? <Icon key={f} className="h-3 w-3 text-slate-400" strokeWidth={1.75} /> : null;
                })}
              </div>
            </div>

            {/* Timeline */}
            <div
              className="relative flex-1"
              style={{ height: ROW_HEIGHT }}
              data-testid={`grid-timeline-${r.id}`}
            >
              {/* Faint hour dividers */}
              {hours.slice(1).map((h, i) => (
                <div key={h} className="absolute top-0 bottom-0 w-px bg-slate-100"
                     style={{ left: `${((i + 1) / (hours.length - 1)) * 100}%` }} />
              ))}
              {/* Half-hour ticks */}
              {Array.from({ length: totalMinutes / SLOT_MINUTES }).map((_, i) => {
                const min = i * SLOT_MINUTES;
                const left = (min / totalMinutes) * 100;
                return (
                  <button
                    key={i}
                    type="button"
                    onMouseEnter={() => setHoverSlot({ roomId: r.id, minute: min })}
                    onMouseLeave={() => setHoverSlot(null)}
                    onClick={() => openBooking(r.id, min)}
                    className="absolute top-0 bottom-0 hover:bg-slate-100/60 focus:outline-none focus:bg-slate-100"
                    style={{ left: `${left}%`, width: `${(SLOT_MINUTES / totalMinutes) * 100}%` }}
                    data-testid={`slot-${r.id}-${min}`}
                    title={`Book ${String(Math.floor((START_HOUR * 60 + min) / 60)).padStart(2, "0")}:${String((min % 60)).padStart(2, "0")}`}
                  />
                );
              })}

              {/* Now line */}
              {nowMin !== null && (
                <div className="absolute top-0 bottom-0 w-px bg-rose-500 pointer-events-none z-10"
                     style={{ left: `${(nowMin / totalMinutes) * 100}%` }}
                     data-testid={`now-line-${r.id}`}>
                  <div className="absolute -top-1.5 -translate-x-1/2 h-3 w-3 rounded-full bg-rose-500 border-2 border-white" />
                </div>
              )}

              {/* Booking blocks */}
              {r.bookings.map((b) => {
                const { left, width, s, e } = bookingToBlock(b);
                if (width <= 0) return null;
                const pending = b.approval_status === "pending";
                return (
                  <div
                    key={b.id}
                    className={`absolute top-1 bottom-1 rounded-md px-2 py-1 text-[11px] leading-tight overflow-hidden shadow-sm z-[1] cursor-default ${
                      pending
                        ? "bg-amber-50 text-amber-800 border border-amber-200"
                        : "bg-indigo-50 text-indigo-800 border border-indigo-200"
                    }`}
                    style={{ left: `${left}%`, width: `${width}%` }}
                    title={`${b.title} · ${fmtTime(s)}–${fmtTime(e)} · ${b.created_by_name}${pending ? " · pending approval" : ""}`}
                    data-testid={`booking-block-${b.id}`}
                  >
                    <div className="font-medium truncate">{b.title}</div>
                    <div className="text-[10px] opacity-80 truncate">{fmtTime(s)}–{fmtTime(e)} · {b.created_by_name}</div>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      {/* Legend */}
      <div className="flex items-center flex-wrap gap-4 text-xs text-slate-500">
        <span className="flex items-center gap-1.5"><span className="h-3 w-3 rounded bg-indigo-100 border border-indigo-200" /> Confirmed</span>
        <span className="flex items-center gap-1.5"><span className="h-3 w-3 rounded bg-amber-100 border border-amber-200" /> Pending HR approval</span>
        <span className="flex items-center gap-1.5"><span className="h-3 w-3 rounded bg-rose-500" /> Now</span>
        <span className="flex items-center gap-1.5"><Clock3 className="h-3 w-3" /> Click a slot to book</span>
        <span className="flex items-center gap-1.5"><Repeat className="h-3 w-3" /> Recurring meetings need HR approval</span>
      </div>
    </div>
  );
}
