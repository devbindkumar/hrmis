import { useEffect, useState } from "react";
import api, { formatApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Activity, Coffee, House, LogIn, LogOut, Video } from "lucide-react";
import { toast } from "sonner";
import StatusPill from "@/components/StatusPill";

const STATUS_OPTIONS = [
  { v: "active", label: "Active", icon: Activity },
  { v: "in_meeting", label: "In meeting", icon: Video },
  { v: "on_break", label: "On break", icon: Coffee },
  { v: "wfh", label: "Working from home", icon: House },
];

function fmtDur(seconds) {
  if (!seconds || seconds < 0) return "0h 0m";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `${h}h ${m}m`;
}
function liveDuration(startIso) {
  if (!startIso) return 0;
  return Math.floor((Date.now() - new Date(startIso).getTime()) / 1000);
}

/**
 * A compact check-in / check-out widget usable from any role's dashboard.
 * `variant="compact"` renders a single-row band suited to admin/HR/manager
 * overviews. `variant="hero"` renders the big presentation used on the
 * employee Today page.
 */
export default function CheckInWidget({ variant = "compact", testid = "checkin-widget" }) {
  const [today, setToday] = useState(null);
  const [, setTick] = useState(0);

  const load = async () => {
    try {
      const { data } = await api.get("/attendance/today");
      setToday(data);
    } catch (e) {
      // ignore — will retry on next action
    }
  };

  useEffect(() => { load(); }, []);
  useEffect(() => { const t = setInterval(() => setTick((x) => x + 1), 30000); return () => clearInterval(t); }, []);

  const checkIn = async () => {
    try { await api.post("/attendance/check-in"); toast.success("Checked in. Have a great day!"); load(); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };
  const checkOut = async () => {
    try { await api.post("/attendance/check-out"); toast.success("Checked out. See you tomorrow!"); load(); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };
  const setStatus = async (s) => {
    try { await api.post("/attendance/status", { status: s }); toast.success("Status updated"); load(); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  if (!today) {
    return <Skeleton className={variant === "compact" ? "h-20 w-full" : "h-48 w-full"} data-testid={`${testid}-skel`} />;
  }

  const checked = !!today.check_in && !today.check_out;
  const done = !!today.check_out;
  const duration = checked ? liveDuration(today.check_in) : (today.duration_seconds || 0);

  const inTime = today.check_in && new Date(today.check_in).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const outTime = today.check_out && new Date(today.check_out).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  return (
    <div className="surface p-5 flex items-center gap-4 flex-wrap" data-testid={testid}>
      <div className="flex items-center gap-4 flex-1 min-w-0">
        <div
          className={`h-11 w-11 rounded-xl grid place-items-center shrink-0 ${
            done ? "bg-slate-100 text-slate-500" : checked ? "bg-emerald-50 text-emerald-700" : "bg-slate-900 text-white"
          }`}
        >
          <Activity className="h-5 w-5" strokeWidth={1.6} />
        </div>
        <div className="min-w-0">
          <div className="text-[10px] uppercase tracking-widest font-semibold text-slate-400">
            {done ? "Day complete" : checked ? "Currently working" : "Not checked in"}
          </div>
          <div className="flex items-baseline gap-3 mt-0.5">
            <div className="font-display text-2xl font-semibold tabular-nums text-slate-900">{fmtDur(duration)}</div>
            {checked && <StatusPill status={today.current_status || "active"} />}
          </div>
          <div className="text-xs text-slate-500 mt-0.5">
            {inTime && <>In at <b className="text-slate-700">{inTime}</b>{today.is_late && <span className="ml-1.5 text-rose-600 text-[10px] font-medium uppercase tracking-wide">Late</span>}</>}
            {outTime && <> · Out at <b className="text-slate-700">{outTime}</b></>}
            {!inTime && "Tap the button to start your day."}
          </div>
        </div>
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        {!checked && !done ? (
          <Button onClick={checkIn} className="h-11 rounded-xl px-5 bg-slate-900 hover:bg-slate-800 text-white font-medium" data-testid={`${testid}-check-in-button`}>
            <LogIn className="h-4 w-4 mr-2" strokeWidth={1.6} /> Check in
          </Button>
        ) : checked ? (
          <>
            <Select value={today.current_status || "active"} onValueChange={setStatus}>
              <SelectTrigger className="h-11 w-48 rounded-xl border-slate-200" data-testid={`${testid}-status-select`}>
                <SelectValue placeholder="Set status" />
              </SelectTrigger>
              <SelectContent>
                {STATUS_OPTIONS.map((s) => (
                  <SelectItem key={s.v} value={s.v}>
                    <div className="flex items-center gap-2">
                      <s.icon className="h-3.5 w-3.5" strokeWidth={1.6} /> {s.label}
                    </div>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button onClick={checkOut} className="h-11 rounded-xl px-5 bg-rose-600 hover:bg-rose-700 text-white font-medium" data-testid={`${testid}-check-out-button`}>
              <LogOut className="h-4 w-4 mr-2" strokeWidth={1.6} /> Check out
            </Button>
          </>
        ) : (
          <div className="px-4 py-2.5 rounded-xl bg-slate-100 text-slate-600 text-sm">Wrapped up at {outTime}.</div>
        )}
      </div>
    </div>
  );
}
