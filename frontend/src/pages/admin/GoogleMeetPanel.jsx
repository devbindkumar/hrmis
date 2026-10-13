import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import api, { formatApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import { Video, Link2, Unlink, Copy, KeyRound, Trash2 } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";

export default function GoogleMeetPanel() {
  const { user } = useAuth();
  const [status, setStatus] = useState(null);
  const [busy, setBusy] = useState(false);
  const [params, setParams] = useSearchParams();

  const [creds, setCreds] = useState({ client_id: "", client_secret: "" });

  const apply = (data) => {
    setStatus(data);
    setCreds({ client_id: data.client_id || "", client_secret: "" });
  };
  const load = () => api.get("/google/status").then((r) => apply(r.data)).catch(() => setStatus(null));

  const saveCreds = async () => {
    setBusy(true);
    try {
      const { data } = await api.put("/google/credentials", {
        client_id: creds.client_id,
        client_secret: creds.client_secret || null,
      });
      apply(data);
      toast.success("Google credentials saved — now click Connect Google");
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    setBusy(false);
  };

  const clearCreds = async () => {
    if (!window.confirm("Remove the saved Client ID & Secret? This also disconnects Google.")) return;
    setBusy(true);
    try {
      const { data } = await api.delete("/google/credentials");
      apply(data);
      toast.success("Google credentials removed");
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    setBusy(false);
  };

  useEffect(() => {
    load();
    const g = params.get("google");
    if (g === "connected") toast.success("Google account connected — Meet links are now available");
    if (g === "error") toast.error(`Google connection failed (${params.get("reason") || "unknown"})`);
    if (g) { params.delete("google"); params.delete("reason"); setParams(params, { replace: true }); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (user?.role !== "super_admin" || !status) return null;

  const connect = async () => {
    setBusy(true);
    try {
      const { data } = await api.get("/google/oauth/start");
      window.location.href = data.authorization_url;
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail));
      setBusy(false);
    }
  };

  const disconnect = async () => {
    if (!window.confirm("Disconnect Google? New meetings won't get Meet links until you reconnect.")) return;
    setBusy(true);
    try {
      await api.delete("/google/disconnect");
      toast.success("Google disconnected");
      load();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    setBusy(false);
  };

  return (
    <div className="surface p-6" data-testid="google-meet-panel">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <Video className="h-4 w-4 text-emerald-600" strokeWidth={1.5} />
          <h3 className="font-display text-lg font-medium text-slate-900">Google Meet & Calendar</h3>
          {status.connected
            ? <Badge className="bg-emerald-50 text-emerald-700 border border-emerald-200" data-testid="google-status-badge">Connected</Badge>
            : <Badge className="bg-slate-100 text-slate-600 border border-slate-200" data-testid="google-status-badge">{status.configured ? "Not connected" : "Credentials missing"}</Badge>}
        </div>
        {status.connected ? (
          <Button variant="outline" size="sm" onClick={disconnect} disabled={busy} className="rounded-lg" data-testid="google-disconnect-btn">
            <Unlink className="h-3.5 w-3.5 mr-1" /> Disconnect
          </Button>
        ) : (
          <Button size="sm" onClick={connect} disabled={busy || !status.configured} className="rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white" data-testid="google-connect-btn">
            <Link2 className="h-3.5 w-3.5 mr-1" /> Connect Google
          </Button>
        )}
      </div>
      <p className="text-sm text-slate-500 mt-2">
        {status.connected
          ? <>Meetings with "Add Google Meet" ticked are created on <b data-testid="google-connected-email">{status.email}</b>. Google emails calendar invites, updates and cancellations to every participant.</>
          : status.configured
          ? "Connect your company Google account (e.g. hr@yourcompany.com) once. All HRMS meetings with a Meet link will be created under it."
          : "Paste your Google OAuth Client ID and Client Secret below, save, then connect your company Google account."}
      </p>
      <div className="mt-4 rounded-xl border border-slate-200 p-4 space-y-3" data-testid="google-creds-form">
        <div className="flex items-center gap-2 text-sm font-medium text-slate-900">
          <KeyRound className="h-3.5 w-3.5 text-slate-500" /> OAuth credentials
          {status.creds_source === "env" && (
            <span className="text-[11px] font-normal text-slate-500">(currently using server defaults)</span>
          )}
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div>
            <Label>Client ID</Label>
            <Input
              value={creds.client_id}
              onChange={(e) => setCreds({ ...creds, client_id: e.target.value })}
              placeholder="xxxxxxxx.apps.googleusercontent.com"
              className="mt-1.5 font-mono text-xs"
              data-testid="google-client-id-input"
            />
          </div>
          <div>
            <Label>Client Secret</Label>
            <Input
              type="password"
              value={creds.client_secret}
              onChange={(e) => setCreds({ ...creds, client_secret: e.target.value })}
              placeholder={status.client_secret_masked ? `Saved ${status.client_secret_masked} — type to replace` : "GOCSPX-…"}
              className="mt-1.5 font-mono text-xs"
              autoComplete="new-password"
              data-testid="google-client-secret-input"
            />
          </div>
        </div>
        <div className="flex items-center justify-end gap-2 flex-wrap">
          {status.creds_source === "settings" && (
            <Button variant="outline" size="sm" onClick={clearCreds} disabled={busy} className="rounded-lg text-rose-600" data-testid="google-clear-creds-btn">
              <Trash2 className="h-3.5 w-3.5 mr-1" /> Remove keys
            </Button>
          )}
          <Button
            size="sm"
            onClick={saveCreds}
            disabled={busy || !creds.client_id.trim() || (!creds.client_secret.trim() && status.creds_source !== "settings")}
            className="rounded-lg bg-slate-900 hover:bg-slate-800 text-white"
            data-testid="google-save-creds-btn"
          >
            Save credentials
          </Button>
        </div>
        {status.connected && (
          <p className="text-[11px] text-amber-700">Changing the Client ID will disconnect the current Google account.</p>
        )}
      </div>

      {status.redirect_uri && !status.connected && (
        <div className="mt-3 text-xs text-slate-600">
          Authorized redirect URI to add in Google Cloud:
          <div className="mt-1 flex items-center gap-2">
            <code className="bg-slate-50 border border-slate-200 rounded px-2 py-1 break-all" data-testid="google-redirect-uri">{status.redirect_uri}</code>
            <button
              onClick={() => { navigator.clipboard.writeText(status.redirect_uri); toast.success("Copied"); }}
              className="text-slate-400 hover:text-slate-900 p-1"
              data-testid="google-copy-redirect-btn"
            >
              <Copy className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
