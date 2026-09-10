import { useEffect, useState } from "react";
import { ArrowRight, CheckCircle2, Loader2, Mail, ShieldCheck, X } from "lucide-react";
import { ApiError, NetworkError, getCurrentUser, login } from "@/lib/api";
import "/src/platform.css";

const demoProfile = { name: "User", email: "user@sentrix.local", role: "Lead investigator", initials: "US" };

export default function Login() {
  const [busy, setBusy] = useState(false);
  // Credentials are checked server-side against app/db/users_store.py. The demo
  // identities are usernames -- admin / investigator1 / analyst1 -- not email
  // addresses, which is why this field is no longer labelled or typed as email.
  const [username, setUsername] = useState(() => localStorage.getItem("sentrix-login-username") || "");
  const [password, setPassword] = useState("");
  const [loginError, setLoginError] = useState("");
  const [forgotOpen, setForgotOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [rememberMe, setRememberMe] = useState(() => localStorage.getItem("sentrix-remember-me") === "true");
  const [emailError, setEmailError] = useState("");
  const [sent, setSent] = useState(false);
  const [returning, setReturning] = useState(() => sessionStorage.getItem("sentrix-logo-transition") === "platform-to-login");
  useEffect(() => { if (!returning) return; sessionStorage.removeItem("sentrix-logo-transition"); const timer = window.setTimeout(() => setReturning(false), 850); return () => window.clearTimeout(timer); }, [returning]);
  const enter = async () => {
    const name = username.trim();
    if (!name || !password) { setLoginError("Enter both a username and a password."); return; }
    setLoginError("");
    setBusy(true);
    try {
      // login() stores the JWT under "sentrix_token" itself (see lib/api.ts).
      await login(name, password);
      // Separate try/catch: /auth/me only enriches the displayed profile, so a
      // failure here must not discard an otherwise successful sign-in.
      let nextProfile: Record<string, string> = { ...demoProfile, name, initials: name.slice(0, 2).toUpperCase() };
      try {
        const user = await getCurrentUser();
        nextProfile = {
          name: user.username,
          role: user.role,
          // Placeholder, not the real address: the backend has no email field.
          // Agency deliberately does NOT go here -- this same value is rendered
          // in Platform.tsx's Settings modal under an "EMAIL" label whose save
          // handler would then persist the agency as the user's email. Revisit
          // in step 6 when Platform.tsx is in scope.
          email: `${user.username}@sentrix.local`,
          initials: user.username.slice(0, 2).toUpperCase(),
          // Carried as its own key so step 6 can surface it properly.
          agency: user.agency,
        };
      } catch (meError) {
        // Non-fatal: keep the username-only profile assembled above. Logged
        // rather than swallowed so a broken /auth/me is diagnosable, but only
        // the error's name and message -- never the object, whose stack could
        // surface request internals into a console the user may screenshot.
        // api.ts builds these messages from fixed strings or the server's
        // `detail`, and never embeds the bearer token.
        const reason = meError instanceof Error ? `${meError.name}: ${meError.message}` : "unknown error";
        console.warn(`[login] /auth/me failed (${reason}); showing a minimal profile`);
      }
      if (rememberMe) { localStorage.setItem("sentrix-remember-me", "true"); localStorage.setItem("sentrix-login-username", nextProfile.name); } else { localStorage.removeItem("sentrix-remember-me"); localStorage.removeItem("sentrix-login-username"); }
      sessionStorage.setItem("sentrix-logo-transition", "login-to-platform");
      localStorage.setItem("sentrix-profile", JSON.stringify(nextProfile));
      // Busy state intentionally stays set: the button holds its authenticating
      // look while the logo transition plays out into /platform.
      window.setTimeout(() => { window.location.href = "/platform"; }, 700);
    } catch (error) {
      setBusy(false);
      // NetworkError extends ApiError, so it must be tested first -- the
      // reverse order would report an unreachable server as a bad password.
      if (error instanceof NetworkError) setLoginError("Can't reach the server right now.");
      else if (error instanceof ApiError && error.status === 401) setLoginError("Incorrect username or password.");
      else setLoginError(error instanceof Error ? error.message : "Sign-in failed.");
    }
  };
  const validateEmail = (value: string) => /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(value.trim());
  const sendReset = () => { if (!validateEmail(email)) { setEmailError("Enter a valid email address, such as name@company.com."); setSent(false); return; } setEmailError(""); setSent(true); };
  return <main className={`login-screen ${returning ? "returning" : ""}`}><div className="login-glow" /><div className="login-route-wipe" /><section className="login-card"><div className={`login-logo-wrap ${busy ? "transitioning" : ""}`}><span className="sentrix-x-mark login-x-mark" aria-label="SentriX logo">X</span></div><span className="eyebrow"><span className="eyebrow-line" /> SECURE ACCESS</span><h1>Return to the<br /><em>signal desk.</em></h1><p>Enter the demo investigation workspace to continue exploring transaction intelligence.</p><label className="login-email-label">USERNAME<input type="text" autoComplete="username" placeholder="admin" value={username} onChange={(event) => { setUsername(event.target.value); if (loginError) setLoginError(""); }} onKeyDown={(event) => event.key === "Enter" && enter()} /></label><label className="login-email-label">PASSWORD<input type="password" autoComplete="current-password" placeholder="••••••••" value={password} onChange={(event) => { setPassword(event.target.value); if (loginError) setLoginError(""); }} onKeyDown={(event) => event.key === "Enter" && enter()} />{loginError && <span className="field-error" role="alert">{loginError}</span>}</label><button className="primary-button login-button" onClick={enter} disabled={busy}>{busy ? <><Loader2 className="login-spinner" size={15} /> AUTHENTICATING…</> : <>Continue{username.trim() ? ` as ${username.trim()}` : ""} <ArrowRight size={15} /></>}</button><label className="remember-row"><input type="checkbox" checked={rememberMe} onChange={(event) => setRememberMe(event.target.checked)} /><span className="remember-box" /> Remember me</label><button className="forgot-link" onClick={() => { setForgotOpen(true); setSent(false); setEmailError(""); }}>Forgot password?</button><small className="login-note"><ShieldCheck size={12} /> Demo workspace · admin / investigator1 / analyst1</small></section>{/* Non-functional demo UI: there is no password-reset endpoint behind this modal. */}{forgotOpen &&<div className="preferences-backdrop" onMouseDown={(event) => event.target === event.currentTarget && setForgotOpen(false)}><section className="preferences-modal recovery-modal" role="dialog" aria-modal="true" aria-labelledby="recovery-title"><button className="recovery-close" onClick={() => setForgotOpen(false)} aria-label="Close forgot password dialog"><X size={16} /></button>{sent ? <><div className="recovery-success"><CheckCircle2 size={22} /></div><span className="eyebrow"><span className="eyebrow-line" /> CHECK YOUR INBOX</span><h2 id="recovery-title">Reset link queued.</h2><p>If an account exists for <b>{email}</b>, a recovery link will arrive shortly.</p><button className="primary-button recovery-action" onClick={() => setForgotOpen(false)}>Back to login</button></> : <><div className="recovery-icon"><Mail size={20} /></div><span className="eyebrow"><span className="eyebrow-line" /> ACCOUNT RECOVERY</span><h2 id="recovery-title">Forgot password?</h2><p>Enter your account email and we’ll send a secure reset link.</p><label className="recovery-label">EMAIL ADDRESS<input autoFocus type="email" value={email} onChange={(event) => { setEmail(event.target.value); if (emailError) setEmailError(""); }} placeholder="you@company.com" onKeyDown={(event) => event.key === "Enter" && sendReset()} />{emailError && <span className="field-error" role="alert">{emailError}</span>}</label><div className="preferences-actions"><button className="secondary-button" onClick={() => setForgotOpen(false)}>Cancel</button><button className="primary-button" onClick={sendReset}>Send reset link <ArrowRight size={14} /></button></div></>}</section></div>}</main>;
}
