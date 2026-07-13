// KioskLinkCard — prominent shortcut on the Admin dashboard so super-admins
// can grab the standalone Kiosk URL (and QR code) without hunting through
// Settings. Displays a scannable QR that a receptionist can point at with a
// tablet to boot straight into the face-attendance scanner.

import { useEffect, useState } from "react";
import api, { formatApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { toast } from "sonner";
import { QRCodeSVG } from "qrcode.react";
import { Camera, Copy, ExternalLink, RefreshCw, ShieldCheck, ShieldAlert, QrCode } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";

export default function KioskLinkCard() {
  const { user } = useAuth();
  const isSuperAdmin = user?.role === "super_admin";
  const [company, setCompany] = useState(null);
  const [kiosk, setKiosk] = useState(null);
  const [rotating, setRotating] = useState(false);
  const [toggling, setToggling] = useState(false);

  const load = async () => {
    try {
      const c = await api.get("/companies/mine");
      setCompany(c.data);
      if (isSuperAdmin) {
        const k = await api.get(`/companies/${c.data.id}/kiosk-token`);
        setKiosk(k.data);
      }
    } catch (e) { /* ignore */ }
  };
  useEffect(() => { load(); }, []);

  if (!isSuperAdmin || !company) return null;

  const kioskUrl = kiosk?.kiosk_token
    ? `${window.location.origin}/kiosk/scan?token=${kiosk.kiosk_token}`
    : null;
  const enabled = !!kiosk?.kiosk_enabled;

  const copy = () => {
    if (!kioskUrl) return;
    navigator.clipboard.writeText(kioskUrl);
    toast.success("Kiosk URL copied — paste it into a browser on your reception device");
  };

  const rotate = async () => {
    if (kiosk?.kiosk_token && !window.confirm("Rotate the kiosk token? Any device holding the old URL will stop working.")) return;
    setRotating(true);
    try {
      const { data } = await api.post(`/companies/${company.id}/kiosk-token/rotate`);
      setKiosk((k) => ({ ...(k || {}), kiosk_token: data.kiosk_token, kiosk_enabled: true, has_token: true }));
      toast.success("New kiosk URL generated");
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setRotating(false); }
  };

  const toggle = async (v) => {
    setToggling(true);
    try {
      await api.patch(`/companies/${company.id}`, { kiosk_enabled: v });
      setKiosk((k) => ({ ...(k || {}), kiosk_enabled: v }));
      toast.success(v ? "Kiosk enabled" : "Kiosk disabled");
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setToggling(false); }
  };

  return (
    <div className="surface p-5 card-hover" data-testid="kiosk-link-card">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <div className="h-9 w-9 rounded-lg bg-indigo-50 text-indigo-700 grid place-items-center">
            <Camera className="h-4 w-4" strokeWidth={1.75} />
          </div>
          <div>
            <div className="font-display text-lg font-medium text-slate-900">Attendance kiosk</div>
            <div className="text-xs text-slate-500 mt-0.5">Face-recognition sign-in for a reception tablet</div>
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className={`text-[10px] uppercase tracking-widest font-semibold ${enabled ? "text-emerald-700" : "text-slate-400"}`}>
            {enabled ? "Live" : "Off"}
          </span>
          <Switch
            checked={enabled}
            onCheckedChange={toggle}
            disabled={toggling || !kiosk?.kiosk_token}
            data-testid="kiosk-card-toggle"
          />
        </div>
      </div>

      {kioskUrl ? (
        <div className="mt-4 grid grid-cols-1 sm:grid-cols-[auto_1fr] gap-4 items-center">
          <div className="rounded-xl bg-white border border-slate-200 p-2 grid place-items-center shrink-0" data-testid="kiosk-qr">
            <QRCodeSVG
              value={kioskUrl}
              size={112}
              level="M"
              includeMargin={false}
              bgColor="#ffffff"
              fgColor="#0f172a"
            />
          </div>
          <div className="min-w-0">
            <div className="text-[10px] uppercase tracking-widest text-slate-400 font-semibold">Standalone kiosk URL</div>
            <div
              className="mt-1 font-mono text-[11px] text-slate-700 bg-slate-50 border border-slate-100 rounded-md px-2 py-1.5 break-all"
              data-testid="kiosk-card-url"
            >
              {kioskUrl}
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <Button size="sm" variant="outline" onClick={copy} className="rounded-lg" data-testid="kiosk-card-copy">
                <Copy className="h-3.5 w-3.5 mr-1.5" /> Copy link
              </Button>
              <a href={kioskUrl} target="_blank" rel="noreferrer">
                <Button size="sm" variant="outline" className="rounded-lg" data-testid="kiosk-card-open">
                  <ExternalLink className="h-3.5 w-3.5 mr-1.5" /> Open now
                </Button>
              </a>
              <Button
                size="sm"
                variant="ghost"
                onClick={rotate}
                disabled={rotating}
                className="rounded-lg text-slate-500 hover:text-slate-900"
                data-testid="kiosk-card-rotate"
              >
                <RefreshCw className={`h-3.5 w-3.5 mr-1 ${rotating ? "animate-spin" : ""}`} /> Rotate
              </Button>
            </div>
            <div className="mt-2 text-[11px] text-slate-500 flex items-start gap-1.5">
              {enabled ? (
                <ShieldCheck className="h-3.5 w-3.5 text-emerald-600 shrink-0 mt-0.5" />
              ) : (
                <ShieldAlert className="h-3.5 w-3.5 text-amber-500 shrink-0 mt-0.5" />
              )}
              <span>
                Scan the QR from a tablet to open the kiosk full-screen. Enrol faces in
                <b> Employees → Edit → Face-recognition</b>.
              </span>
            </div>
          </div>
        </div>
      ) : (
        <div className="mt-4 rounded-lg border border-dashed border-slate-300 bg-slate-50/60 p-6 text-center">
          <QrCode className="h-8 w-8 mx-auto text-slate-400" strokeWidth={1.25} />
          <div className="mt-2 text-sm text-slate-600">No kiosk link yet.</div>
          <div className="text-xs text-slate-500 mt-1">Generate one to get a shareable URL + QR code.</div>
          <Button
            size="sm"
            onClick={rotate}
            disabled={rotating}
            className="mt-3 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg"
            data-testid="kiosk-card-generate"
          >
            <RefreshCw className={`h-3.5 w-3.5 mr-1.5 ${rotating ? "animate-spin" : ""}`} />
            Generate kiosk link
          </Button>
        </div>
      )}
    </div>
  );
}
