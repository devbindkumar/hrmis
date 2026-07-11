// KioskActivity — recent face-scanner attendance events shown on the admin
// Overview. Fetches GET /api/kiosk/activity and refreshes every 30s.
import { useEffect, useState } from "react";
import api from "@/lib/api";
import { Link } from "react-router-dom";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Camera, LogIn, LogOut, ArrowUpRight, ScanFace } from "lucide-react";

function fmtRelative(iso) {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  const diff = Math.max(0, Date.now() - then);
  const min = Math.floor(diff / 60000);
  if (min < 1) return "just now";
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  return new Date(iso).toLocaleDateString();
}

function initials(name) {
  return (name || "?")
    .trim()
    .split(/\s+/)
    .map((p) => p[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

export default function KioskActivity({ limit = 8 }) {
  const [events, setEvents] = useState(null);
  const [err, setErr] = useState(null);

  const load = async () => {
    try {
      const { data } = await api.get(`/kiosk/activity?limit=${limit}`);
      setEvents(data.events || []);
      setErr(null);
    } catch (e) {
      setErr(e.response?.data?.detail || "Could not load kiosk activity");
    }
  };
  useEffect(() => { load(); const t = setInterval(load, 30000); return () => clearInterval(t); }, []);

  return (
    <div className="surface p-5" data-testid="kiosk-activity">
      <div className="flex items-center justify-between gap-3 mb-3">
        <div className="flex items-center gap-2">
          <div className="h-8 w-8 rounded-lg bg-indigo-50 text-indigo-700 grid place-items-center">
            <ScanFace className="h-4 w-4" strokeWidth={1.6} />
          </div>
          <div>
            <div className="font-display text-base font-semibold text-slate-900">Kiosk activity</div>
            <div className="text-[11px] text-slate-500">Recent face-scanner check-ins & check-outs</div>
          </div>
        </div>
        <Link to="/admin/attendance" className="text-xs text-slate-500 hover:text-slate-900 flex items-center gap-1" data-testid="kiosk-activity-see-all">
          Full attendance <ArrowUpRight className="h-3 w-3" />
        </Link>
      </div>

      {events === null && !err && (
        <div className="space-y-2">
          {[0, 1, 2].map((i) => <Skeleton key={i} className="h-11 w-full" />)}
        </div>
      )}

      {err && (
        <div className="text-sm text-rose-600" data-testid="kiosk-activity-error">{err}</div>
      )}

      {events && events.length === 0 && (
        <div className="text-sm text-slate-500 py-6 text-center flex flex-col items-center gap-2" data-testid="kiosk-activity-empty">
          <Camera className="h-5 w-5 text-slate-400" strokeWidth={1.6} />
          <div>No kiosk scans yet.</div>
          <Link to="/admin/settings" className="text-xs text-emerald-700 hover:text-emerald-800 font-medium">
            Set up the kiosk →
          </Link>
        </div>
      )}

      {events && events.length > 0 && (
        <ul className="divide-y divide-slate-100 -mx-1" data-testid="kiosk-activity-list">
          {events.map((e, i) => (
            <li key={`${e.employee_user_id}-${e.action}-${e.at}-${i}`} className="flex items-center gap-3 px-1 py-2.5" data-testid="kiosk-activity-row">
              <Avatar className="h-8 w-8">
                {e.avatar_url && <AvatarImage src={e.avatar_url} />}
                <AvatarFallback className="text-[10px]">{initials(e.employee_name)}</AvatarFallback>
              </Avatar>
              <div className="min-w-0 flex-1">
                <div className="text-sm text-slate-900 truncate">{e.employee_name}</div>
                <div className="text-[11px] text-slate-500 truncate">
                  {e.action === "check_in" ? "Checked in" : "Checked out"} · {fmtRelative(e.at)}
                </div>
              </div>
              {e.action === "check_in" ? (
                <div className="flex items-center gap-1.5 shrink-0">
                  {e.is_late && (
                    <Badge variant="secondary" className="bg-amber-100 text-amber-700 border-amber-200 h-5 px-1.5 text-[10px] font-medium">
                      Late
                    </Badge>
                  )}
                  <span className="h-7 w-7 rounded-lg bg-emerald-50 text-emerald-700 grid place-items-center">
                    <LogIn className="h-3.5 w-3.5" strokeWidth={1.6} />
                  </span>
                </div>
              ) : (
                <span className="h-7 w-7 rounded-lg bg-rose-50 text-rose-700 grid place-items-center shrink-0">
                  <LogOut className="h-3.5 w-3.5" strokeWidth={1.6} />
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
