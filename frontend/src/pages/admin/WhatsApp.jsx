import { useEffect, useState } from "react";
import api, { formatApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { toast } from "sonner";
import {
  MessageCircle,
  Key,
  Send,
  Copy,
  CheckCircle2,
  AlertCircle,
  RefreshCw,
  History,
  ExternalLink,
} from "lucide-react";

const EVENT_LABELS = {
  status_update: "Status changes (Break / WFH / Meeting)",
  leave_request: "Leave requests",
  wfh_request: "WFH requests",
  meeting_scheduled: "Meeting scheduled",
  checkin_checkout: "Check-in / Check-out",
};

const STATUS_OPTIONS = [
  { value: "on_break", label: "On Break" },
  { value: "in_meeting", label: "In Meeting" },
  { value: "remote", label: "Working from Home" },
  { value: "wfh", label: "WFH (legacy)" },
  { value: "active", label: "Active" },
  { value: "offline", label: "Offline" },
];

export default function WhatsAppSettings() {
  const [cfg, setCfg] = useState(null);
  const [specs, setSpecs] = useState(null);
  const [outbox, setOutbox] = useState([]);
  const [saving, setSaving] = useState(false);
  const [testOpen, setTestOpen] = useState(false);
  const [testForm, setTestForm] = useState({ to: "", template_key: "status_update" });
  const [testing, setTesting] = useState(false);

  const load = async () => {
    try {
      const [c, t, o] = await Promise.all([
        api.get("/whatsapp/config"),
        api.get("/whatsapp/templates"),
        api.get("/whatsapp/outbox?limit=25").catch(() => ({ data: [] })),
      ]);
      setCfg(c.data);
      setSpecs(t.data);
      setOutbox(o.data || []);
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail));
    }
  };

  useEffect(() => { load(); }, []);

  if (!cfg || !specs) {
    return <div className="p-6 text-sm text-slate-500">Loading WhatsApp settings…</div>;
  }

  const save = async () => {
    setSaving(true);
    try {
      const payload = {
        enabled: cfg.enabled,
        phone_number_id: cfg.phone_number_id,
        business_account_id: cfg.business_account_id,
        default_country_code: cfg.default_country_code,
        api_base_url: cfg.api_base_url || "",
        events_enabled: cfg.events_enabled,
        status_filters: cfg.status_filters,
      };
      // Only send token if user typed a fresh one (not masked / not empty)
      if (cfg.access_token && !cfg.access_token.includes("•")) {
        payload.access_token = cfg.access_token;
      }
      const r = await api.put("/whatsapp/config", payload);
      setCfg(r.data);
      toast.success("WhatsApp settings saved");
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail));
    } finally {
      setSaving(false);
    }
  };

  const sendTest = async () => {
    setTesting(true);
    try {
      const r = await api.post("/whatsapp/test", testForm);
      toast.success(`Test sent · id ${r.data?.message_id || "—"}`);
      setTestOpen(false);
      const o = await api.get("/whatsapp/outbox?limit=25");
      setOutbox(o.data || []);
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail));
    } finally {
      setTesting(false);
    }
  };

  const copy = (text, what = "Copied") => {
    navigator.clipboard.writeText(text);
    toast.success(what);
  };

  const setEvent = (key, value) => {
    setCfg({ ...cfg, events_enabled: { ...cfg.events_enabled, [key]: value } });
  };

  const toggleStatusFilter = (value) => {
    const list = cfg.status_filters || [];
    const next = list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
    setCfg({ ...cfg, status_filters: next });
  };

  const tokenPlaceholder = cfg.access_token_masked || "EAAG... (paste your System User token)";

  return (
    <div className="p-6 space-y-6 animate-fade-up" data-testid="admin-whatsapp">
      {/* Header */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <div className="flex items-center gap-2">
            <div className="h-9 w-9 rounded-xl bg-emerald-50 text-emerald-700 flex items-center justify-center">
              <MessageCircle className="h-5 w-5" strokeWidth={1.6} />
            </div>
            <div>
              <h1 className="font-display text-3xl font-semibold tracking-tight text-slate-900">WhatsApp Integration</h1>
              <p className="text-sm text-slate-500 mt-0.5">Send template-based WhatsApp alerts to reporting managers in real-time.</p>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant={cfg.enabled ? "default" : "secondary"} className={cfg.enabled ? "bg-emerald-600" : ""} data-testid="wa-status-badge">
            {cfg.enabled ? "Active" : "Disabled"}
          </Badge>
          <Button
            variant="outline"
            className="rounded-lg"
            onClick={() => setTestOpen(true)}
            disabled={!cfg.enabled}
            data-testid="wa-test-open-btn"
          >
            <Send className="h-3.5 w-3.5 mr-1.5" />
            Send test
          </Button>
        </div>
      </div>

      <Tabs defaultValue="config" className="w-full">
        <TabsList className="bg-slate-100 rounded-lg p-1">
          <TabsTrigger value="config" data-testid="tab-config">Configuration</TabsTrigger>
          <TabsTrigger value="events" data-testid="tab-events">Event triggers</TabsTrigger>
          <TabsTrigger value="templates" data-testid="tab-templates">Templates for Meta approval</TabsTrigger>
          <TabsTrigger value="outbox" data-testid="tab-outbox">Outbox</TabsTrigger>
          <TabsTrigger value="setup" data-testid="tab-setup">Setup guide</TabsTrigger>
        </TabsList>

        {/* ───── CONFIGURATION ───── */}
        <TabsContent value="config" className="mt-5">
          <div className="surface p-6 space-y-5">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="font-display text-lg font-medium text-slate-900">Credentials</h3>
                <p className="text-xs text-slate-500 mt-0.5">Stored only for this company. Token is never returned in plain text.</p>
              </div>
              <div className="flex items-center gap-2">
                <Label htmlFor="enabled" className="text-sm">Enabled</Label>
                <Switch
                  id="enabled"
                  checked={!!cfg.enabled}
                  onCheckedChange={(v) => setCfg({ ...cfg, enabled: v })}
                  data-testid="wa-enabled-switch"
                />
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <Label className="flex items-center gap-1.5"><Key className="h-3.5 w-3.5" /> System User Access Token</Label>
                <Input
                  type="password"
                  className="mt-1.5 font-mono text-xs"
                  placeholder={tokenPlaceholder}
                  value={cfg.access_token || ""}
                  onChange={(e) => setCfg({ ...cfg, access_token: e.target.value })}
                  data-testid="wa-token-input"
                />
                {cfg.access_token_masked && (
                  <p className="text-[11px] text-slate-400 mt-1">Saved: <span className="font-mono">{cfg.access_token_masked}</span> — leave blank to keep.</p>
                )}
              </div>

              <div>
                <Label>Phone Number ID</Label>
                <Input
                  className="mt-1.5"
                  placeholder="e.g. 105954XXXXXXXX"
                  value={cfg.phone_number_id || ""}
                  onChange={(e) => setCfg({ ...cfg, phone_number_id: e.target.value })}
                  data-testid="wa-phone-id-input"
                />
              </div>

              <div>
                <Label>Business Account ID</Label>
                <Input
                  className="mt-1.5"
                  placeholder="e.g. 1234567890123456"
                  value={cfg.business_account_id || ""}
                  onChange={(e) => setCfg({ ...cfg, business_account_id: e.target.value })}
                  data-testid="wa-business-id-input"
                />
              </div>

              <div>
                <Label>Default country code</Label>
                <Input
                  className="mt-1.5"
                  placeholder="91"
                  value={cfg.default_country_code || ""}
                  onChange={(e) => setCfg({ ...cfg, default_country_code: e.target.value })}
                  data-testid="wa-country-code-input"
                />
                <p className="text-[11px] text-slate-400 mt-1">Prepended to phone numbers missing a country code.</p>
              </div>

              <div className="md:col-span-2">
                <Label>WhatsApp API Base URL <span className="text-slate-400 font-normal">(optional)</span></Label>
                <Input
                  className="mt-1.5 font-mono text-xs"
                  placeholder={cfg.default_api_base_url || "https://graph.facebook.com/v20.0"}
                  value={cfg.api_base_url || ""}
                  onChange={(e) => setCfg({ ...cfg, api_base_url: e.target.value })}
                  data-testid="wa-api-base-url-input"
                />
                <p className="text-[11px] text-slate-400 mt-1">
                  Leave blank to use Meta&apos;s default (<span className="font-mono">{cfg.default_api_base_url}</span>). Override only if you proxy the WhatsApp Cloud API or use an on-prem gateway. The path <span className="font-mono">{"/{phone_number_id}/messages"}</span> is appended automatically.
                </p>
              </div>
            </div>

            <div className="flex items-center justify-end pt-2">
              <Button onClick={save} disabled={saving} className="bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg" data-testid="wa-save-btn">
                {saving ? "Saving…" : "Save settings"}
              </Button>
            </div>
          </div>
        </TabsContent>

        {/* ───── EVENT TRIGGERS ───── */}
        <TabsContent value="events" className="mt-5">
          <div className="surface p-6 space-y-5">
            <div>
              <h3 className="font-display text-lg font-medium text-slate-900">Trigger events</h3>
              <p className="text-xs text-slate-500 mt-0.5">Choose which HR events trigger a WhatsApp message to the reporting manager.</p>
            </div>

            <div className="divide-y divide-slate-100 -mx-2">
              {Object.entries(EVENT_LABELS).map(([key, label]) => (
                <div key={key} className="flex items-center justify-between px-2 py-3.5">
                  <div>
                    <div className="text-sm font-medium text-slate-900">{label}</div>
                    <div className="text-[11px] text-slate-500 mt-0.5">Template: <span className="font-mono">{cfg.templates?.[key]}</span></div>
                  </div>
                  <Switch
                    checked={!!cfg.events_enabled?.[key]}
                    onCheckedChange={(v) => setEvent(key, v)}
                    data-testid={`wa-event-${key}-switch`}
                  />
                </div>
              ))}
            </div>

            <div className="mt-2">
              <Label>Which status changes should notify the manager?</Label>
              <p className="text-[11px] text-slate-500 mt-0.5 mb-2">Only changes to the selected statuses send WhatsApp. Recommended: skip &quot;Active&quot; and &quot;Offline&quot; to avoid noise.</p>
              <div className="flex flex-wrap gap-2">
                {STATUS_OPTIONS.map((opt) => {
                  const on = (cfg.status_filters || []).includes(opt.value);
                  return (
                    <button
                      key={opt.value}
                      onClick={() => toggleStatusFilter(opt.value)}
                      className={`px-3 py-1.5 rounded-full text-xs font-medium transition ${on ? "bg-emerald-600 text-white" : "bg-slate-100 text-slate-700 hover:bg-slate-200"}`}
                      data-testid={`wa-status-filter-${opt.value}`}
                    >
                      {opt.label}
                    </button>
                  );
                })}
              </div>
            </div>

            <div className="flex items-center justify-end pt-2">
              <Button onClick={save} disabled={saving} className="bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg" data-testid="wa-events-save-btn">
                {saving ? "Saving…" : "Save event settings"}
              </Button>
            </div>
          </div>
        </TabsContent>

        {/* ───── TEMPLATES ───── */}
        <TabsContent value="templates" className="mt-5">
          <div className="surface p-6 space-y-3">
            <div className="flex items-start justify-between gap-3 flex-wrap">
              <div>
                <h3 className="font-display text-lg font-medium text-slate-900">Templates to submit in Meta WhatsApp Manager</h3>
                <p className="text-xs text-slate-500 mt-0.5">Category: <b>UTILITY</b> · Language: <b>English ({specs.language})</b>. Copy each block <i>verbatim</i> into Meta WhatsApp Manager → Message Templates → Create Template.</p>
              </div>
              <a
                href="https://business.facebook.com/wa/manage/message-templates/"
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center text-xs text-emerald-700 hover:text-emerald-800 font-medium"
              >
                Open WhatsApp Manager
                <ExternalLink className="h-3 w-3 ml-1" />
              </a>
            </div>

            <div className="grid grid-cols-1 gap-4 mt-3">
              {specs.templates.map((t) => (
                <div key={t.key} className="rounded-xl border border-slate-200 p-4 bg-slate-50/40" data-testid={`wa-tpl-card-${t.key}`}>
                  <div className="flex items-center justify-between flex-wrap gap-2">
                    <div className="flex items-center gap-2">
                      <Badge className="bg-slate-900 text-white">{t.name}</Badge>
                      <span className="text-xs text-slate-500">{t.variables.length} variables · UTILITY</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <Button size="sm" variant="outline" onClick={() => copy(t.name, "Template name copied")} data-testid={`wa-tpl-copy-name-${t.key}`}>
                        <Copy className="h-3 w-3 mr-1" /> Name
                      </Button>
                      <Button size="sm" variant="outline" onClick={() => copy(t.body, "Template body copied")} data-testid={`wa-tpl-copy-body-${t.key}`}>
                        <Copy className="h-3 w-3 mr-1" /> Body
                      </Button>
                    </div>
                  </div>

                  <pre className="mt-3 whitespace-pre-wrap text-sm bg-white border border-slate-200 rounded-lg p-3 font-mono text-slate-800 leading-relaxed">{t.body}</pre>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-3">
                    <div>
                      <div className="text-[11px] uppercase tracking-wider text-slate-500 font-semibold mb-1">Variables (in order)</div>
                      <ol className="text-xs text-slate-700 list-decimal pl-5 space-y-0.5">
                        {t.variables.map((v, i) => (<li key={i}>{v}</li>))}
                      </ol>
                    </div>
                    <div>
                      <div className="text-[11px] uppercase tracking-wider text-slate-500 font-semibold mb-1">Sample (for Meta preview)</div>
                      <div className="text-xs text-slate-700 font-mono bg-white border border-slate-200 rounded-lg p-2">{(t.example?.body_text?.[0] || []).join(" · ")}</div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </TabsContent>

        {/* ───── OUTBOX ───── */}
        <TabsContent value="outbox" className="mt-5">
          <div className="surface p-6">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="font-display text-lg font-medium text-slate-900 flex items-center gap-2">
                  <History className="h-4 w-4" /> Recent sends
                </h3>
                <p className="text-xs text-slate-500 mt-0.5">Last 25 attempts. Useful when debugging template approvals.</p>
              </div>
              <Button size="sm" variant="outline" onClick={load} data-testid="wa-outbox-refresh">
                <RefreshCw className="h-3 w-3 mr-1" /> Refresh
              </Button>
            </div>

            <div className="mt-4 divide-y divide-slate-100">
              {outbox.length === 0 && (
                <div className="text-sm text-slate-500 py-6 text-center">No messages sent yet.</div>
              )}
              {outbox.map((o) => (
                <div key={o.id} className="py-3 flex items-start justify-between gap-3" data-testid={`wa-outbox-row-${o.id}`}>
                  <div className="flex items-start gap-3">
                    {o.status === "sent" ? (
                      <CheckCircle2 className="h-4 w-4 text-emerald-600 mt-0.5" />
                    ) : (
                      <AlertCircle className="h-4 w-4 text-rose-600 mt-0.5" />
                    )}
                    <div>
                      <div className="text-sm text-slate-900">
                        <span className="font-mono text-xs text-slate-500">{o.template}</span> → <span className="font-medium">{o.to}</span>
                      </div>
                      <div className="text-[11px] text-slate-500 mt-0.5">{o.created_at} {o.detail && <span>· {String(o.detail).slice(0, 140)}</span>}</div>
                    </div>
                  </div>
                  <Badge variant={o.status === "sent" ? "default" : "destructive"} className={o.status === "sent" ? "bg-emerald-600" : ""}>
                    {o.status}
                  </Badge>
                </div>
              ))}
            </div>
          </div>
        </TabsContent>

        {/* ───── SETUP GUIDE ───── */}
        <TabsContent value="setup" className="mt-5">
          <div className="surface p-6 space-y-4 text-sm text-slate-700 leading-relaxed">
            <h3 className="font-display text-lg font-medium text-slate-900">How to wire WhatsApp Cloud API (one-time setup)</h3>
            <ol className="list-decimal pl-5 space-y-2.5">
              <li>
                Go to <a className="text-emerald-700 underline" href="https://developers.facebook.com/" target="_blank" rel="noreferrer">developers.facebook.com</a> and create an App (type: <b>Business</b>).
              </li>
              <li>Inside the app, add the <b>WhatsApp</b> product. Open <b>WhatsApp → API Setup</b>.</li>
              <li>
                Copy the <b>Phone Number ID</b> and <b>WhatsApp Business Account ID</b> from that screen and paste them into the Configuration tab here.
              </li>
              <li>
                In <b>Business Settings → System Users</b>, create a <b>System User</b>, assign your WhatsApp Business Account, and generate a <b>permanent access token</b> with the <code className="text-xs bg-slate-100 px-1 rounded">whatsapp_business_messaging</code> permission. Paste it into the Access Token field. (The temporary 24h token from API Setup also works for early testing.)
              </li>
              <li>
                In the <b>Templates</b> tab here, click <i>Copy Body</i> for each of the five templates and create them inside Meta WhatsApp Manager → <b>Message Templates</b>. Use Category <b>UTILITY</b>, language <b>English (en_US)</b>, and name them <i>exactly</i> as shown. Submit for approval (usually approved within minutes).
              </li>
              <li>
                While templates are pending, add any test recipient phone numbers under <b>WhatsApp → API Setup → To</b> so they can receive messages in sandbox mode.
              </li>
              <li>Toggle <b>Enabled</b> in Configuration, save, then use <b>Send test</b> to verify delivery.</li>
              <li>Make sure every employee profile has the manager&apos;s <b>phone number</b> filled in (international format, e.g. <code className="text-xs bg-slate-100 px-1 rounded">919876543210</code>). Without it, the manager won&apos;t receive WhatsApp.</li>
            </ol>
            <div className="rounded-lg bg-amber-50 border border-amber-200 p-3 text-amber-900 text-xs">
              <b>Important:</b> WhatsApp will only deliver the template-shaped message. The body you submit to Meta must match exactly — same number of <code>{"{{1}}"}</code> placeholders, same wording (whitespace is OK). If a template hasn&apos;t been approved yet, sends will fail with a clear error in the Outbox tab.
            </div>
          </div>
        </TabsContent>
      </Tabs>

      {/* ─── TEST DIALOG ─── */}
      <Dialog open={testOpen} onOpenChange={setTestOpen}>
        <DialogContent className="rounded-2xl">
          <DialogHeader><DialogTitle className="font-display">Send a test WhatsApp</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div>
              <Label>Recipient phone (international, digits only)</Label>
              <Input
                placeholder="e.g. 919876543210"
                value={testForm.to}
                onChange={(e) => setTestForm({ ...testForm, to: e.target.value })}
                className="mt-1.5"
                data-testid="wa-test-to-input"
              />
              <p className="text-[11px] text-slate-500 mt-1">Must be added under Meta API Setup → &quot;To&quot; if your number is still in sandbox.</p>
            </div>
            <div>
              <Label>Template to test</Label>
              <Select
                value={testForm.template_key}
                onValueChange={(v) => setTestForm({ ...testForm, template_key: v })}
              >
                <SelectTrigger className="mt-1.5" data-testid="wa-test-tpl-select"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {Object.keys(EVENT_LABELS).map((k) => (
                    <SelectItem key={k} value={k}>{EVENT_LABELS[k]}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setTestOpen(false)}>Cancel</Button>
            <Button onClick={sendTest} disabled={testing || !testForm.to} className="bg-emerald-600 hover:bg-emerald-700 text-white" data-testid="wa-test-send-btn">
              {testing ? "Sending…" : "Send test"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
