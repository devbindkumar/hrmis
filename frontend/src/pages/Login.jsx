import { useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useNavigate } from "react-router-dom";
import { ArrowRight, Loader2, Briefcase } from "lucide-react";
import { toast } from "sonner";

export default function Login() {
  const { login, error } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);

  const handle = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      const u = await login(email, password);
      toast.success(`Welcome back, ${u.name.split(" ")[0]}`);
      const isAdmin = ["super_admin", "hr", "manager"].includes(u.role);
      navigate(isAdmin ? "/admin" : "/employee", { replace: true });
    } catch (e) {
      toast.error(e.message || "Sign in failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen grid lg:grid-cols-2" data-testid="login-page">
      {/* Left art panel — full-bleed office photo with overlay + centered badge */}
      <div
        className="relative hidden lg:flex items-center justify-center overflow-hidden"
        style={{
          backgroundImage: "url(/login-bg.jpg)",
          backgroundSize: "cover",
          backgroundPosition: "center",
        }}
      >
        {/* Decent light-dark overlay for legibility */}
        <div className="absolute inset-0 bg-gradient-to-br from-slate-950/45 via-slate-900/30 to-slate-900/55" />
        {/* Centered HRMIS workspace badge */}
        <div
          className="relative z-10 inline-flex items-center gap-2 px-4 py-2 rounded-full border border-white/30 bg-white/10 backdrop-blur-md text-xs uppercase tracking-[0.2em] font-semibold text-white"
          data-testid="hrmis-badge"
        >
          <Briefcase className="h-3.5 w-3.5" strokeWidth={1.5} />
          HRMIS workspace
        </div>
      </div>

      {/* Right form */}
      <div className="flex items-center justify-center px-6 py-12 bg-white">
        <div className="w-full max-w-md">
          <div className="mb-10">
            <img
              src="/imd-logo.png"
              alt="Inbox Matters Digital"
              className="h-16 w-auto object-contain"
              data-testid="login-company-logo"
            />
            <h2 className="font-display text-3xl mt-8 font-semibold tracking-tight text-slate-900">Sign in</h2>
            <p className="mt-2 text-slate-500 text-sm">Use your work email and password to continue.</p>
          </div>

          <form onSubmit={handle} className="space-y-5" data-testid="login-form">
            <div>
              <Label htmlFor="email" className="text-xs font-semibold uppercase tracking-[0.05em] text-slate-500">Email</Label>
              <Input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@inboxmattersdigital.com"
                className="mt-2 h-11 rounded-lg border-slate-200 focus-visible:ring-slate-900"
                required
                data-testid="login-email-input"
              />
            </div>
            <div>
              <Label htmlFor="password" className="text-xs font-semibold uppercase tracking-[0.05em] text-slate-500">Password</Label>
              <Input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                className="mt-2 h-11 rounded-lg border-slate-200 focus-visible:ring-slate-900"
                required
                data-testid="login-password-input"
              />
            </div>

            {error && (
              <div className="rounded-lg bg-rose-50 border border-rose-200 px-3 py-2 text-sm text-rose-700" data-testid="login-error">
                {error}
              </div>
            )}

            <Button
              type="submit"
              disabled={busy}
              className="w-full h-11 rounded-lg bg-slate-900 hover:bg-slate-800 text-white font-medium"
              data-testid="login-submit-button"
            >
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : (
                <>Sign in <ArrowRight className="h-4 w-4 ml-2" strokeWidth={1.5} /></>
              )}
            </Button>
          </form>
        </div>
      </div>
    </div>
  );
}
