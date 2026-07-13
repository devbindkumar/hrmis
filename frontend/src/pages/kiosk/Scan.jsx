// Kiosk face-scanner page — public, loads via /kiosk/scan?token=<company_kiosk_token>.
// Meant for a full-screen browser on a tablet / mini-PC pointed at the office door.
// Flow:
//   1. Verify token → fetch company info
//   2. Start camera + models
//   3. On stable face detection (real + live + enough score), match against backend
//   4. Show matched employee, offer Check-in / Check-out buttons
//   5. On tap → POST /api/kiosk/check-in|out → success screen → auto-reset to scan

import { useEffect, useMemo, useState, useRef } from "react";
import { useSearchParams } from "react-router-dom";
import axios from "axios";
import useFaceCapture from "@/lib/useFaceCapture";
import { Loader2, LogIn, LogOut, ShieldAlert, CheckCircle2, AlertTriangle } from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

// Sample cadence — try to match every ~1.5s while a stable face is present.
const MATCH_INTERVAL_MS = 1500;
// After a successful check-in/out, freeze the success screen this long.
const SUCCESS_HOLD_MS = 3500;

export default function KioskScan() {
  const [params] = useSearchParams();
  const token = params.get("token") || "";
  const [session, setSession] = useState(null);
  const [initError, setInitError] = useState(null);
  const [match, setMatch] = useState(null);        // matched employee state
  const [confirmed, setConfirmed] = useState(null); // { action: 'in'|'out', name, is_late }
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const lastMatchAt = useRef(0);
  const lastAttemptedEmbedding = useRef(null);

  // Bootstrap kiosk session
  useEffect(() => {
    if (!token) { setInitError("Missing kiosk token in URL. Ask your admin for the kiosk link."); return; }
    axios.get(`${API}/kiosk/session`, { params: { token } })
      .then((r) => setSession(r.data))
      .catch((e) => setInitError(e.response?.data?.detail || "Invalid or disabled kiosk token"));
  }, [token]);

  const { videoRef, ready, loadingModels, error, state, retry } = useFaceCapture({
    enabled: !!session && !confirmed,
  });

  const thresholds = session?.thresholds || { min_liveness: 0.6, min_antispoof: 0.6 };

  // Live "stability" indicator
  const isLive = state.live >= thresholds.min_liveness;
  const isReal = state.real >= thresholds.min_antispoof;
  const isStable = state.detected && state.score >= 0.75 && isLive && isReal;

  // Match loop — throttled
  useEffect(() => {
    if (!isStable || !state.embedding || confirmed || match) return;
    const now = Date.now();
    if (now - lastMatchAt.current < MATCH_INTERVAL_MS) return;
    lastMatchAt.current = now;
    lastAttemptedEmbedding.current = state.embedding;
    setMessage("Recognising…");
    axios.post(`${API}/kiosk/match`, {
      token,
      embedding: state.embedding,
      liveness_score: state.live,
      antispoof_score: state.real,
    })
      .then((r) => {
        if (r.data.matched) {
          setMatch(r.data);
          setMessage("");
        } else {
          setMessage("Face not recognised. Please ask an admin to enroll.");
        }
      })
      .catch((e) => {
        const d = e.response?.data?.detail;
        if (d?.code === "SPOOF_DETECTED") setMessage("Please look directly at the camera (spoof detected).");
        else if (d?.code === "LIVENESS_FAIL") setMessage("Please blink or move slightly for liveness.");
        else setMessage(typeof d === "string" ? d : "Match error, try again.");
      });
  }, [isStable, state.embedding, match, confirmed, token, state.live, state.real]);

  const doAction = async (action) => {
    if (!match?.employee?.id) return;
    setBusy(true);
    try {
      const path = action === "in" ? "check-in" : "check-out";
      const { data } = await axios.post(`${API}/kiosk/${path}`, {
        token, employee_id: match.employee.id,
      });
      setConfirmed({
        action,
        name: data.employee_name || match.employee.name,
        is_late: data.is_late,
      });
      setTimeout(() => {
        setConfirmed(null);
        setMatch(null);
        setMessage("");
      }, SUCCESS_HOLD_MS);
    } catch (e) {
      setMessage(e.response?.data?.detail || "Action failed");
    } finally { setBusy(false); }
  };

  const reset = () => { setMatch(null); setMessage(""); };

  const accent = session?.company?.accent_color || "#0f172a";
  const companyName = session?.company?.name || "Workspace";
  const logoUrl = session?.company?.has_logo
    ? `${process.env.REACT_APP_BACKEND_URL}/api/companies/${session.company.id}/logo`
    : null;

  const now = useLiveClock();

  if (initError) {
    return (
      <div className="min-h-screen grid place-items-center bg-slate-950 text-slate-100 p-6" data-testid="kiosk-error">
        <div className="text-center max-w-md">
          <ShieldAlert className="h-12 w-12 mx-auto mb-4 text-rose-400" />
          <h1 className="font-display text-2xl font-semibold mb-2">Kiosk unavailable</h1>
          <p className="text-sm text-slate-400">{initError}</p>
        </div>
      </div>
    );
  }
  if (!session) {
    return (
      <div className="min-h-screen grid place-items-center bg-slate-950 text-slate-100">
        <Loader2 className="h-10 w-10 animate-spin" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-950 text-white flex flex-col" data-testid="kiosk-page">
      {/* Header */}
      <header className="px-8 py-6 flex items-center justify-between border-b border-white/5">
        <div className="flex items-center gap-3">
          {logoUrl ? (
            <div className="h-11 w-11 rounded-lg bg-white p-1.5 grid place-items-center">
              <img src={logoUrl} alt={companyName} className="max-h-full max-w-full object-contain" />
            </div>
          ) : (
            <div className="h-11 w-11 rounded-lg grid place-items-center" style={{ background: accent }}>
              <span className="font-display text-lg font-semibold">{companyName[0]}</span>
            </div>
          )}
          <div>
            <div className="font-display text-xl font-semibold">{companyName}</div>
            <div className="text-[10px] uppercase tracking-widest text-slate-400">Attendance kiosk</div>
          </div>
        </div>
        <div className="text-right">
          <div className="font-display text-2xl font-semibold tabular-nums" data-testid="kiosk-clock">{now}</div>
          <div className="text-[10px] uppercase tracking-widest text-slate-400">{new Date().toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "short" })}</div>
        </div>
      </header>

      {/* Body */}
      <main className="flex-1 grid lg:grid-cols-2 gap-8 p-8">
        {/* Camera panel */}
        <section className="relative rounded-2xl overflow-hidden bg-black aspect-video shadow-2xl" data-testid="kiosk-video-wrap">
          <video ref={videoRef} playsInline muted className="w-full h-full object-cover" />
          {loadingModels && (
            <div className="absolute inset-0 grid place-items-center bg-slate-950/90">
              <div className="text-center">
                <Loader2 className="h-10 w-10 animate-spin mx-auto mb-3" />
                <div className="text-sm">Loading recognition models…</div>
                <div className="text-[11px] text-slate-400 mt-0.5">≈ 15 MB · cached after first load</div>
              </div>
            </div>
          )}
          {error && !loadingModels && (
            <div className="absolute inset-0 grid place-items-center bg-rose-950/90 p-6 text-center">
              <div>
                <AlertTriangle className="h-10 w-10 mx-auto mb-2 text-rose-300" />
                <div className="text-sm">{error}</div>
                <button
                  onClick={retry}
                  className="mt-4 px-4 py-2 rounded-lg bg-white/10 hover:bg-white/20 text-sm font-medium"
                  data-testid="kiosk-retry"
                >
                  Try again
                </button>
              </div>
            </div>
          )}
          {ready && !error && !loadingModels && (
            <div className="absolute inset-x-0 bottom-0 p-3 flex gap-1.5 justify-center bg-gradient-to-t from-black/70">
              <StatusChip label="Face" ok={state.detected} value={state.score} />
              <StatusChip label="Real" ok={isReal} value={state.real} />
              <StatusChip label="Live" ok={isLive} value={state.live} />
            </div>
          )}
        </section>

        {/* Prompt panel */}
        <section className="flex flex-col justify-center">
          {confirmed ? (
            <div className="text-center" data-testid="kiosk-confirmed">
              <div className={`h-24 w-24 rounded-full mx-auto grid place-items-center ${confirmed.is_late ? "bg-amber-500/20" : "bg-emerald-500/20"}`}>
                <CheckCircle2 className={`h-12 w-12 ${confirmed.is_late ? "text-amber-400" : "text-emerald-400"}`} />
              </div>
              <div className="mt-6 font-display text-4xl font-semibold">Have a great day, {confirmed.name.split(" ")[0]}!</div>
              <div className="mt-2 text-slate-400">
                {confirmed.action === "in" ? "Checked in" : "Checked out"}
                {confirmed.is_late && confirmed.action === "in" && <span className="ml-2 text-amber-400 font-medium">· Late</span>}
              </div>
            </div>
          ) : match ? (
            <div className="text-center" data-testid="kiosk-match">
              <div className="text-slate-400 text-sm uppercase tracking-widest">Hello,</div>
              <div className="mt-1 font-display text-5xl font-semibold">{match.employee.name}</div>
              <div className="mt-2 text-slate-400 text-sm">Confidence {(match.confidence * 100).toFixed(0)}%</div>

              <div className="mt-10 grid grid-cols-2 gap-4 max-w-md mx-auto">
                <button
                  onClick={() => doAction("in")}
                  disabled={busy || match.attendance?.checked_in}
                  className="h-24 rounded-2xl bg-emerald-500/90 hover:bg-emerald-500 text-white font-display text-xl disabled:opacity-40"
                  data-testid="kiosk-check-in-btn"
                >
                  <LogIn className="h-6 w-6 mx-auto mb-1" /> Check in
                </button>
                <button
                  onClick={() => doAction("out")}
                  disabled={busy || !match.attendance?.checked_in || match.attendance?.checked_out}
                  className="h-24 rounded-2xl bg-rose-500/90 hover:bg-rose-500 text-white font-display text-xl disabled:opacity-40"
                  data-testid="kiosk-check-out-btn"
                >
                  <LogOut className="h-6 w-6 mx-auto mb-1" /> Check out
                </button>
              </div>

              {match.attendance?.check_in && (
                <div className="mt-4 text-slate-400 text-xs">
                  {match.attendance.check_out
                    ? `Already checked out at ${new Date(match.attendance.check_out).toLocaleTimeString()}`
                    : `Checked in at ${new Date(match.attendance.check_in).toLocaleTimeString()}`}
                </div>
              )}

              <button onClick={reset} className="mt-6 text-xs text-slate-400 hover:text-slate-200 underline">
                Not you? Scan again
              </button>
            </div>
          ) : (
            <div className="text-center" data-testid="kiosk-prompt">
              <div className="font-display text-5xl font-semibold">Look at the camera</div>
              <p className="mt-3 text-slate-400 max-w-md mx-auto">
                Position your face inside the frame. The scanner will recognise you automatically.
              </p>
              <div className="mt-8 text-sm text-slate-400 min-h-[1.5em]" data-testid="kiosk-message">{message}</div>
            </div>
          )}
        </section>
      </main>

      <footer className="px-8 py-4 border-t border-white/5 text-[10px] uppercase tracking-widest text-slate-500 text-center">
        HRMIS · Face-recognition attendance · Powered by @vladmandic/human
      </footer>
    </div>
  );
}

function StatusChip({ label, ok, value = 0 }) {
  return (
    <span className={`px-2.5 py-1 rounded-full text-[11px] font-medium ${ok ? "bg-emerald-500/25 text-emerald-100" : "bg-white/10 text-slate-300"}`}>
      {label} {(value * 100).toFixed(0)}%
    </span>
  );
}

function useLiveClock() {
  const [t, setT] = useState(() => new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }));
  useEffect(() => {
    const i = setInterval(() => setT(new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })), 1000);
    return () => clearInterval(i);
  }, []);
  return t;
}
