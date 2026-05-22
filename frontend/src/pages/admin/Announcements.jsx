import { useEffect, useState } from "react";
import api, { formatApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Megaphone, Plus, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Switch } from "@/components/ui/switch";

export default function AdminAnnouncements() {
  const [list, setList] = useState([]);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ title: "", body: "", notify_email: false });
  const [busy, setBusy] = useState(false);

  const load = () => api.get("/announcements").then((r) => setList(r.data));
  useEffect(() => { load(); }, []);

  const submit = async () => {
    if (!form.title || !form.body) { toast.error("Title and body required"); return; }
    setBusy(true);
    try {
      await api.post("/announcements", form);
      toast.success("Announcement posted");
      setForm({ title: "", body: "", notify_email: false });
      setOpen(false);
      load();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };

  return (
    <div className="p-6 space-y-5 animate-fade-up" data-testid="admin-announcements">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="font-display text-3xl font-semibold tracking-tight text-slate-900">Announcements</h1>
          <p className="text-sm text-slate-500 mt-1">Broadcast company-wide messages.</p>
        </div>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button className="bg-slate-900 hover:bg-slate-800 text-white" data-testid="new-announcement-btn"><Plus className="h-4 w-4 mr-1.5" /> New announcement</Button>
          </DialogTrigger>
          <DialogContent className="rounded-2xl">
            <DialogHeader><DialogTitle className="font-display">New announcement</DialogTitle></DialogHeader>
            <div className="space-y-3">
              <div>
                <Label>Title</Label>
                <Input value={form.title} onChange={(e)=>setForm({...form, title: e.target.value})} className="mt-1.5" data-testid="ann-title" />
              </div>
              <div>
                <Label>Body</Label>
                <Textarea value={form.body} onChange={(e)=>setForm({...form, body: e.target.value})} className="mt-1.5 min-h-[120px]" data-testid="ann-body" />
              </div>
              <div className="flex items-center gap-3 p-3 rounded-lg bg-slate-50 border border-slate-100">
                <Switch checked={form.notify_email} onCheckedChange={(v)=>setForm({...form, notify_email: v})} data-testid="ann-email-toggle" />
                <div>
                  <div className="text-sm font-medium text-slate-900">Also send via email</div>
                  <div className="text-xs text-slate-500">Sends a copy to every active employee.</div>
                </div>
              </div>
            </div>
            <DialogFooter>
              <Button onClick={submit} disabled={busy} className="bg-slate-900 hover:bg-slate-800 text-white" data-testid="ann-submit">
                {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : "Post"}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      <div className="space-y-4">
        {list.length === 0 ? <div className="surface p-12 text-center text-slate-400">No announcements yet.</div> : list.map((a) => (
          <div key={a.id} className="surface p-6">
            <div className="flex items-start gap-3">
              <div className="h-9 w-9 rounded-lg bg-amber-50 text-amber-600 grid place-items-center border border-amber-100"><Megaphone className="h-4 w-4" strokeWidth={1.5} /></div>
              <div className="flex-1">
                <div className="flex items-center justify-between">
                  <h3 className="font-display text-lg font-medium text-slate-900">{a.title}</h3>
                  <span className="text-xs text-slate-400">{new Date(a.created_at).toLocaleString()}</span>
                </div>
                <p className="text-sm text-slate-700 mt-1.5 leading-relaxed whitespace-pre-line">{a.body}</p>
                <div className="text-xs text-slate-400 mt-3">— {a.author_name}</div>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
