// FaceEnroll — admin-side webcam capture that takes 3 samples of an employee's face
// and posts them to POST /api/employees/{id}/face. Used inside the Employees
// edit dialog and the onboarding flow.

import { useEffect, useState } from "react";
import api, { formatApiError } from "@/lib/api";
import useFaceCapture from "@/lib/useFaceCapture";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";
import { Camera, CheckCircle2, AlertTriangle, Trash2, ShieldCheck, ShieldAlert, Loader2 } from "lucide-react";

const REQUIRED = 3;
const MIN_LIVE = 0.6;
const MIN_REAL = 0.6;
const MIN_DETECT_SCORE = 0.7;

export default function FaceEnroll({ employeeId, employeeName, onChanged }) {
  const [samples, setSamples] = useState([]);          // [{embedding, photoB64}]
  const [status, setStatus] = useState(null);          // server status
  const [busy, setBusy] = useState(false);
  const [scanActive, setScanActive] = useState(false);

  const { videoRef, ready, loadingModels, error, state, captureJpeg } =
    useFaceCapture({ enabled: scanActive });

  const loadStatus = async () => {
    try {
      const { data } = await api.get(`/employees/${employeeId}/face`);
      setStatus(data);
    } catch (e) {
      // ignore
    }
  };
  useEffect(() => { loadStatus(); }, [employeeId]);

  const goodLighting = state.detected && state.score >= MIN_DETECT_SCORE;
  const isReal = state.real >= MIN_REAL;
  const isLive = state.live >= MIN_LIVE;
  const canSample = goodLighting && isReal && isLive;

  const takeSample = () => {
    if (!canSample || !state.embedding) return;
    const photo = captureJpeg();
    setSamples((s) => [...s, { embedding: state.embedding, photoB64: photo }]);
    toast.success(`Sample ${samples.length + 1}/${REQUIRED} captured`);
  };

  const submit = async () => {
    if (samples.length < REQUIRED) return;
    setBusy(true);
    try {
      await api.post(`/employees/${employeeId}/face`, {
        embeddings: samples.map((s) => s.embedding),
        photos: samples.map((s) => s.photoB64).filter(Boolean),
      });
      toast.success("Face enrolled");
      setSamples([]);
      setScanActive(false);
      await loadStatus();
      if (onChanged) onChanged();
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail));
    } finally { setBusy(false); }
  };

  const remove = async () => {
    if (!window.confirm(`Remove face enrollment for ${employeeName}?`)) return;
    setBusy(true);
    try {
      await api.delete(`/employees/${employeeId}/face`);
      toast.success("Face enrollment removed");
      setStatus({ enrolled: false, sample_count: 0 });
      if (onChanged) onChanged();
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail));
    } finally { setBusy(false); }
  };

  return (
    <div className="mt-2 rounded-xl border border-indigo-200/70 bg-indigo-50/40 p-4" data-testid="face-enroll-section">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <div className="h-8 w-8 rounded-lg bg-indigo-100 text-indigo-700 grid place-items-center">
              <Camera className="h-4 w-4" />
            </div>
            <div>
              <div className="text-sm font-semibold text-slate-900">Face-recognition enrollment</div>
              <div className="text-[11px] text-slate-500">
                {status?.enrolled
                  ? `Enrolled · ${status.sample_count} sample${status.sample_count > 1 ? "s" : ""}${status.has_photos ? " · photos on file" : ""}`
                  : "Not enrolled. Capture 3 samples so the kiosk can recognise this employee."}
              </div>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {status?.enrolled && !scanActive && (
            <Button size="sm" variant="outline" onClick={remove} disabled={busy} data-testid="face-remove-btn">
              <Trash2 className="h-3.5 w-3.5 mr-1" /> Remove
            </Button>
          )}
          {!scanActive && (
            <Button
              size="sm"
              onClick={() => setScanActive(true)}
              className="bg-indigo-600 hover:bg-indigo-700 text-white"
              data-testid="face-start-btn"
            >
              <Camera className="h-3.5 w-3.5 mr-1" /> {status?.enrolled ? "Re-enroll" : "Enroll"}
            </Button>
          )}
        </div>
      </div>

      {scanActive && (
        <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="relative rounded-lg overflow-hidden bg-slate-900 aspect-video" data-testid="face-video-wrap">
            <video ref={videoRef} playsInline muted className="w-full h-full object-cover" />
            {loadingModels && (
              <div className="absolute inset-0 grid place-items-center text-white bg-slate-900/80">
                <div className="text-center">
                  <Loader2 className="h-6 w-6 animate-spin mx-auto mb-2" />
                  <div className="text-xs">Loading recognition models…</div>
                  <div className="text-[10px] opacity-70 mt-0.5">~ 15 MB, cached after first load</div>
                </div>
              </div>
            )}
            {error && !loadingModels && (
              <div className="absolute inset-0 grid place-items-center text-rose-100 bg-rose-900/80 text-sm p-4 text-center">
                <div><AlertTriangle className="h-6 w-6 mx-auto mb-2" />{error}</div>
              </div>
            )}
            {ready && !error && !loadingModels && (
              <div className="absolute inset-x-0 bottom-0 p-2 flex flex-wrap items-center gap-1.5 justify-center bg-gradient-to-t from-black/70 to-transparent">
                <Badge variant={goodLighting ? "default" : "secondary"} className={goodLighting ? "bg-emerald-600" : ""}>
                  {state.detected ? `Face detected · ${(state.score * 100).toFixed(0)}%` : "No face"}
                </Badge>
                <Badge variant={isReal ? "default" : "destructive"} className={isReal ? "bg-emerald-600" : ""}>
                  {isReal ? <ShieldCheck className="h-3 w-3 mr-0.5" /> : <ShieldAlert className="h-3 w-3 mr-0.5" />}
                  Real {(state.real * 100).toFixed(0)}%
                </Badge>
                <Badge variant={isLive ? "default" : "destructive"} className={isLive ? "bg-emerald-600" : ""}>
                  Live {(state.live * 100).toFixed(0)}%
                </Badge>
              </div>
            )}
          </div>

          <div className="space-y-3">
            <div className="text-xs text-slate-600">
              Ask the employee to look at the camera, keep still, and blink once. Capture <b>{REQUIRED}</b> samples with slight head movement between each for best accuracy.
            </div>
            <div className="grid grid-cols-3 gap-2">
              {[0, 1, 2].map((i) => {
                const taken = i < samples.length;
                return (
                  <div
                    key={i}
                    className={`aspect-square rounded-lg border-2 grid place-items-center text-xs ${
                      taken ? "border-emerald-500 bg-emerald-50 text-emerald-700" : "border-dashed border-slate-300 text-slate-400"
                    }`}
                    data-testid={`face-sample-slot-${i}`}
                  >
                    {taken ? <CheckCircle2 className="h-6 w-6" /> : `Sample ${i + 1}`}
                  </div>
                );
              })}
            </div>
            <div className="flex items-center gap-2 pt-1">
              <Button
                type="button"
                onClick={takeSample}
                disabled={!canSample || samples.length >= REQUIRED}
                className="bg-slate-900 hover:bg-slate-800 text-white flex-1"
                data-testid="face-capture-sample"
              >
                <Camera className="h-3.5 w-3.5 mr-1" /> Capture sample ({samples.length}/{REQUIRED})
              </Button>
              <Button
                type="button"
                onClick={submit}
                disabled={busy || samples.length < REQUIRED}
                className="bg-indigo-600 hover:bg-indigo-700 text-white"
                data-testid="face-submit"
              >
                {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : "Save"}
              </Button>
              <Button type="button" variant="outline" onClick={() => { setScanActive(false); setSamples([]); }}>
                Cancel
              </Button>
            </div>
            <p className="text-[10px] text-slate-500">
              Anti-spoof + liveness must be ≥ 60% to enable capture. If those bars stay red, ask the employee to look directly at the camera in a well-lit area (not through glasses reflections or a photo).
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
