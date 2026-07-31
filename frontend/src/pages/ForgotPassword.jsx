// 3-step Forgot Password flow — email → WhatsApp OTP → new password.
// Anti-enumeration: step 1 always advances even when the email is unknown.

import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import axios from "axios";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import {
  ArrowLeft, ArrowRight, Loader2, Briefcase, MessageCircle,
  ShieldCheck, KeyRound, RotateCcw, CheckCircle2, Eye, EyeOff,
} from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL;
const OTP_LEN = 6;

function extractError(detail) {
  if (!detail) return "Something went wrong. Please try again.";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((d) => d?.msg || String(d)).join(" ");
  if (detail?.msg) return detail.msg;
  return "Something went wrong. Please try again.";
}

export default function ForgotPassword() {
  const navigate = useNavigate();
  const [step, setStep] = useState(1);  // 1=email, 2=otp, 3=new password
  const [email, setEmail] = useState("");
  const [phoneHint, setPhoneHint] = useState("");
  const [otp, setOtp] = useState(Array(OTP_LEN).fill(""));
  const [resetToken, setResetToken] = useState("");
  const [newPass, setNewPass] = useState("");
  const [confirmPass, setConfirmPass] = useState("");
  const [showPass, setShowPass] = useState(false);
  const [busy, setBusy] = useState(false);
  const [cooldown, setCooldown] = useState(0);

  // Countdown ticker for the resend cooldown
  useEffect(() => {
    if (cooldown <= 0) return;
    const t = setInterval(() => setCooldown((c) => Math.max(0, c - 1)), 1000);
    return () => clearInterval(t);
  }, [cooldown]);

  const requestOtp = async (isResend = false) => {
    if (!email) return;
    setBusy(true);
    try {
      const { data } = await axios.post(`${API}/api/auth/forgot-password`, { email });
      setPhoneHint(data.phone_hint || "");
      if (!isResend) setStep(2);
      setCooldown(45);
      // Reset OTP input on resend
      if (isResend) setOtp(Array(OTP_LEN).fill(""));
      toast.success(
        data.phone_hint
          ? `We sent a code on WhatsApp to ${data.phone_hint}`
          : "If that email is registered, a code has been sent."
      );
    } catch (e) {
      toast.error(extractError(e.response?.data?.detail));
    } finally { setBusy(false); }
  };

  const verifyOtp = async (providedCode) => {
    if (busy) return;
    const code = providedCode || otp.join("");
    if (code.length !== OTP_LEN) { toast.error("Enter all 6 digits"); return; }
    setBusy(true);
    try {
      const { data } = await axios.post(`${API}/api/auth/verify-otp`, { email, otp: code });
      setResetToken(data.reset_token);
      setStep(3);
    } catch (e) {
      toast.error(extractError(e.response?.data?.detail));
      // shake + clear on wrong OTP
      setOtp(Array(OTP_LEN).fill(""));
      document.querySelector('[data-testid="otp-input-0"]')?.focus();
    } finally { setBusy(false); }
  };

  const resetPassword = async () => {
    if (newPass.length < 6) { toast.error("Password must be at least 6 characters"); return; }
    if (newPass !== confirmPass) { toast.error("Passwords don't match"); return; }
    setBusy(true);
    try {
      await axios.post(`${API}/api/auth/reset-password`, {
        reset_token: resetToken, new_password: newPass,
      });
      toast.success("Password updated — please sign in with your new password.");
      navigate("/login", { replace: true });
    } catch (e) {
      toast.error(extractError(e.response?.data?.detail));
    } finally { setBusy(false); }
  };

  return (
    <div className="min-h-screen grid lg:grid-cols-2" data-testid="forgot-password-page">
      {/* Left art panel */}
      <div
        className="relative hidden lg:flex items-center justify-center overflow-hidden"
        style={{
          backgroundImage: "url(/login-bg.jpg)",
          backgroundSize: "cover", backgroundPosition: "center",
        }}
      >
        <div className="absolute inset-0 bg-gradient-to-br from-slate-950/45 via-slate-900/30 to-slate-900/55" />
        <div className="relative z-10 inline-flex items-center gap-2 px-4 py-2 rounded-full border border-white/30 bg-white/10 backdrop-blur-md text-xs uppercase tracking-[0.2em] font-semibold text-white">
          <Briefcase className="h-3.5 w-3.5" strokeWidth={1.5} />
          HRMIS workspace
        </div>
      </div>

      {/* Right form */}
      <div className="flex items-center justify-center px-6 py-12 bg-white">
        <div className="w-full max-w-md">
          <div className="mb-8">
            <img src="/imd-logo.png" alt="Logo" className="h-16 w-auto object-contain" />
            <h2 className="font-display text-3xl mt-8 font-semibold tracking-tight text-slate-900">
              {step === 1 && "Forgot your password?"}
              {step === 2 && "Check your WhatsApp"}
              {step === 3 && "Set a new password"}
            </h2>
            <p className="mt-2 text-slate-500 text-sm">
              {step === 1 && "We'll send a 6-digit code to your registered WhatsApp number."}
              {step === 2 && (phoneHint ? <>Code sent to <b>{phoneHint}</b>. It expires in 10 minutes.</> : "If your account exists, a code has been sent. Otherwise, contact HR.")}
              {step === 3 && "Choose a strong password of at least 6 characters."}
            </p>
          </div>

          {/* Step indicator */}
          <div className="flex items-center gap-2 mb-6" data-testid="step-indicator">
            {[1, 2, 3].map((s) => (
              <div key={s} className="flex items-center gap-2 flex-1">
                <div className={`h-7 w-7 rounded-full grid place-items-center text-[11px] font-semibold shrink-0 border-2 ${
                  step > s ? "bg-emerald-600 border-emerald-600 text-white"
                    : step === s ? "bg-slate-900 border-slate-900 text-white"
                    : "bg-white border-slate-200 text-slate-400"
                }`}>
                  {step > s ? <CheckCircle2 className="h-3.5 w-3.5" /> : s}
                </div>
                {s < 3 && <div className={`h-px flex-1 ${step > s ? "bg-emerald-600" : "bg-slate-200"}`} />}
              </div>
            ))}
          </div>

          {step === 1 && (
            <form onSubmit={(e) => { e.preventDefault(); requestOtp(false); }} className="space-y-5" data-testid="forgot-step-email">
              <div>
                <Label className="text-xs font-semibold uppercase tracking-[0.05em] text-slate-500">Work email</Label>
                <Input type="email" required value={email} onChange={(e) => setEmail(e.target.value)}
                       className="mt-2 h-11 rounded-lg border-slate-200"
                       placeholder="you@inboxmattersdigital.com"
                       data-testid="forgot-email-input" autoFocus />
              </div>
              <Button type="submit" disabled={busy || !email}
                      className="w-full h-11 rounded-lg bg-slate-900 hover:bg-slate-800 text-white font-medium"
                      data-testid="forgot-send-otp-button">
                {busy ? <Loader2 className="h-4 w-4 animate-spin" />
                  : (<><MessageCircle className="h-4 w-4 mr-2" strokeWidth={1.5} /> Send code on WhatsApp</>)}
              </Button>
              <Link to="/login" className="flex items-center justify-center gap-1.5 text-sm text-slate-500 hover:text-slate-900" data-testid="back-to-login">
                <ArrowLeft className="h-3.5 w-3.5" /> Back to sign in
              </Link>
            </form>
          )}

          {step === 2 && (
            <div className="space-y-5" data-testid="forgot-step-otp">
              <OtpBoxes otp={otp} setOtp={setOtp} onComplete={verifyOtp} />
              <Button onClick={verifyOtp} disabled={busy || otp.join("").length !== OTP_LEN}
                      className="w-full h-11 rounded-lg bg-slate-900 hover:bg-slate-800 text-white font-medium"
                      data-testid="forgot-verify-otp-button">
                {busy ? <Loader2 className="h-4 w-4 animate-spin" />
                  : (<><ShieldCheck className="h-4 w-4 mr-2" strokeWidth={1.5} /> Verify code</>)}
              </Button>
              <div className="flex items-center justify-between text-sm">
                <button
                  type="button"
                  onClick={() => requestOtp(true)}
                  disabled={cooldown > 0 || busy}
                  className="text-slate-600 hover:text-slate-900 disabled:text-slate-300 disabled:cursor-not-allowed flex items-center gap-1.5"
                  data-testid="forgot-resend-button"
                >
                  <RotateCcw className="h-3.5 w-3.5" />
                  {cooldown > 0 ? `Resend in ${cooldown}s` : "Resend code"}
                </button>
                <button
                  type="button"
                  onClick={() => { setStep(1); setOtp(Array(OTP_LEN).fill("")); }}
                  className="text-slate-500 hover:text-slate-900 flex items-center gap-1.5"
                  data-testid="forgot-change-email-button"
                >
                  <ArrowLeft className="h-3.5 w-3.5" /> Change email
                </button>
              </div>
            </div>
          )}

          {step === 3 && (
            <form onSubmit={(e) => { e.preventDefault(); resetPassword(); }} className="space-y-5" data-testid="forgot-step-reset">
              <div>
                <Label className="text-xs font-semibold uppercase tracking-[0.05em] text-slate-500">New password</Label>
                <div className="relative mt-2">
                  <Input type={showPass ? "text" : "password"} value={newPass}
                         onChange={(e) => setNewPass(e.target.value)}
                         className="h-11 rounded-lg border-slate-200 pr-10"
                         data-testid="new-password-input" autoFocus required minLength={6} />
                  <button type="button" onClick={() => setShowPass(!showPass)}
                          className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-700"
                          data-testid="toggle-password-visibility">
                    {showPass ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                </div>
              </div>
              <div>
                <Label className="text-xs font-semibold uppercase tracking-[0.05em] text-slate-500">Confirm password</Label>
                <Input type={showPass ? "text" : "password"} value={confirmPass}
                       onChange={(e) => setConfirmPass(e.target.value)}
                       className="mt-2 h-11 rounded-lg border-slate-200"
                       data-testid="confirm-password-input" required minLength={6} />
              </div>
              <Button type="submit" disabled={busy || !newPass || newPass !== confirmPass}
                      className="w-full h-11 rounded-lg bg-slate-900 hover:bg-slate-800 text-white font-medium"
                      data-testid="forgot-reset-button">
                {busy ? <Loader2 className="h-4 w-4 animate-spin" />
                  : (<><KeyRound className="h-4 w-4 mr-2" strokeWidth={1.5} /> Reset password <ArrowRight className="h-4 w-4 ml-2" /></>)}
              </Button>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}

function OtpBoxes({ otp, setOtp, onComplete }) {
  const refs = useRef([]);

  const set = (i, v) => {
    const digit = v.replace(/\D/g, "").slice(-1);
    setOtp((prev) => {
      const next = [...prev];
      next[i] = digit;
      // move focus + auto-verify from the *fresh* next[] value, not the stale outer `otp`
      if (digit && i < OTP_LEN - 1) refs.current[i + 1]?.focus();
      if (digit && next.every((d) => d.length === 1)) {
        setTimeout(() => onComplete(next.join("")), 60);
      }
      return next;
    });
  };
  const back = (i, e) => {
    if (e.key === "Backspace" && !otp[i] && i > 0) refs.current[i - 1]?.focus();
    if (e.key === "ArrowLeft" && i > 0) refs.current[i - 1]?.focus();
    if (e.key === "ArrowRight" && i < OTP_LEN - 1) refs.current[i + 1]?.focus();
  };
  const paste = (e) => {
    const clip = (e.clipboardData || window.clipboardData).getData("text");
    const digits = clip.replace(/\D/g, "").slice(0, OTP_LEN);
    if (digits.length === 0) return;
    e.preventDefault();
    const next = digits.padEnd(OTP_LEN, "").split("");
    setOtp(next);
    const lastIdx = Math.min(digits.length, OTP_LEN) - 1;
    refs.current[lastIdx]?.focus();
    if (digits.length === OTP_LEN) setTimeout(() => onComplete(digits), 60);
  };

  return (
    <div className="flex justify-between gap-2 max-w-sm" onPaste={paste} data-testid="otp-boxes">
      {otp.map((d, i) => (
        <input
          key={i}
          ref={(el) => (refs.current[i] = el)}
          value={d}
          onChange={(e) => set(i, e.target.value)}
          onKeyDown={(e) => back(i, e)}
          inputMode="numeric"
          maxLength={1}
          autoFocus={i === 0}
          className="w-12 h-14 rounded-lg border border-slate-200 bg-white text-center text-2xl font-semibold tabular-nums text-slate-900 focus:outline-none focus:border-slate-900 focus:ring-4 focus:ring-slate-900/10"
          data-testid={`otp-input-${i}`}
        />
      ))}
    </div>
  );
}
