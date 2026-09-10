import { useEffect, useMemo, useState } from "react";
import "../platform.css";
import { HudFrame, ScrambleText, SoundToggle, playUiSound } from "@/components/motion";
import { ApiError, NetworkError, UnauthorizedError, clearToken, listAlerts, type Alert as ApiAlert } from "@/lib/api";
import {
  Activity,
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  Bot,
  Check,
  CheckCircle2,
  ChevronDown,
  CircleHelp,
  Clock3,
  Database,
  ExternalLink,
  Filter,
  GitBranch,
  Globe2,
  Layers,
  Loader2,
  LayoutDashboard,
  LogOut,
  Menu,
  MoreHorizontal,
  Moon,
  Network,
  Play,
  Radio,
  RefreshCw,
  Search,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Terminal,
  UserRound,
  X,
  Zap,
  Sun,
} from "lucide-react";

// `agency` is optional and comes from the backend's /auth/me (written into
// localStorage by Login.tsx). It must stay on this type: the effect below
// re-serialises `profile` over the stored value on every change, so a field
// missing here is silently stripped from storage. It deliberately does not
// share the `email` slot -- that value is bound to the Settings modal's EMAIL
// input, whose save handler would then persist the agency as an email address.
type UserProfile = { name: string; email: string; role: string; initials: string; agency?: string };

const defaultProfile: UserProfile = { name: "User", email: "user@sentrix.local", role: "Lead investigator", initials: "US" };

function getInitials(name: string) {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  return (parts.length > 1 ? `${parts[0][0]}${parts[parts.length - 1][0]}` : name.slice(0, 2)).toUpperCase();
}

function readAuthenticatedProfile(): UserProfile {
  try {
    const hostUser = (window as Window & { __SENTRIX_AUTH_USER__?: Partial<UserProfile> }).__SENTRIX_AUTH_USER__;
    const storedUser = JSON.parse(localStorage.getItem("sentrix-profile") || "null") as Partial<UserProfile> | null;
    const user = hostUser || storedUser;
    if (!user) return defaultProfile;
    const name = user.name || defaultProfile.name;
    // `agency` is carried through rather than defaulted: it has no sensible
    // placeholder, and dropping it here would strip it from storage via the
    // serialising effect below.
    return { name, email: user.email || defaultProfile.email, role: user.role || defaultProfile.role, initials: user.initials || getInitials(name), ...(user.agency ? { agency: user.agency } : {}) };
  } catch { return defaultProfile; }
}

function DashboardCursor() {
  const [position, setPosition] = useState({ x: -100, y: -100 });
  const [cursorMode, setCursorMode] = useState<"default" | "button" | "avatar" | "node">("default");
  useEffect(() => {
    const move = (event: MouseEvent) => setPosition({ x: event.clientX, y: event.clientY });
    const onEnter = (event: Event) => { const target = event.currentTarget as HTMLElement; setCursorMode(target.classList.contains("top-avatar") || target.classList.contains("profile-avatar") ? "avatar" : target.classList.contains("graph-node") ? "node" : "button"); };
    const onLeave = () => setCursorMode("default");
    window.addEventListener("mousemove", move);
    const targets = Array.from(document.querySelectorAll("button, a, input, [role=button]"));
    targets.forEach((target) => { target.addEventListener("mouseenter", onEnter); target.addEventListener("mouseleave", onLeave); });
    return () => { window.removeEventListener("mousemove", move); targets.forEach((target) => { target.removeEventListener("mouseenter", onEnter); target.removeEventListener("mouseleave", onLeave); }); };
  }, []);
  return <div className={`dashboard-cursor ${cursorMode}`} style={{ left: position.x, top: position.y }}><span>{cursorMode === "avatar" ? "USER" : cursorMode === "node" ? "NODE" : cursorMode === "button" ? "VIEW" : ""}</span></div>;
}

function LogoutModal({ onCancel, onConfirm }: { onCancel: () => void; onConfirm: () => void }) { return <div className="preferences-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onCancel()}><section className="preferences-modal logout-modal" role="dialog" aria-modal="true" aria-labelledby="logout-title"><div className="logout-orb"><LogOut size={20} /></div><span className="eyebrow"><span className="eyebrow-line" /> SESSION CONTROL</span><h2 id="logout-title">Leave the signal desk?</h2><p>Your local profile session will be cleared and you will return to the SentriX login screen.</p><div className="preferences-actions"><button className="secondary-button" onClick={onCancel}>Stay signed in</button><button className="danger-button" onClick={onConfirm}>Log out <LogOut size={14} /></button></div></section></div>; }

function PreferencesModal({ profile, setProfile, theme, setTheme, notifications, setNotifications, onClose }: { profile: UserProfile; setProfile: (profile: UserProfile) => void; theme: "midnight" | "dusk"; setTheme: (theme: "midnight" | "dusk") => void; notifications: boolean; setNotifications: (enabled: boolean) => void; onClose: () => void }) {
  const [name, setName] = useState(profile.name);
  const [email, setEmail] = useState(profile.email);
  return <div className="preferences-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}><section className="preferences-modal" role="dialog" aria-modal="true" aria-labelledby="preferences-title"><div className="preferences-header"><div><span className="eyebrow"><span className="eyebrow-line" /> ACCOUNT CONTROL</span><h2 id="preferences-title">Settings</h2></div><button className="icon-button" onClick={onClose} aria-label="Close settings"><X size={17} /></button></div><label>DISPLAY NAME<input value={name} onChange={(event) => setName(event.target.value)} /></label><label>EMAIL<input value={email} onChange={(event) => setEmail(event.target.value)} /></label><div className="preference-row"><div><strong>Theme atmosphere</strong><small>Adjust the analyst console contrast.</small></div><div className="segmented-control"><button className={theme === "midnight" ? "selected" : ""} onClick={() => setTheme("midnight")}>Midnight</button><button className={theme === "dusk" ? "selected" : ""} onClick={() => setTheme("dusk")}>Dusk</button></div></div><div className="preference-row"><div><strong>Live notifications</strong><small>Receive new signal and rescoring updates.</small></div><button className={`toggle ${notifications ? "on" : ""}`} onClick={() => setNotifications(!notifications)} aria-label="Toggle live notifications"><span /></button></div><div className="preferences-actions"><button className="secondary-button" onClick={onClose}>Cancel</button><button className="primary-button" onClick={() => { setProfile({ ...profile, name: name || "User", email: email || "user@sentrix.local", role: profile.role, initials: getInitials(name || "User") }); onClose(); }}>Save changes <Check size={14} /></button></div></section></div>;
}

type Alert = {
  id: string;
  address: string;
  kind: string;
  detail: string;
  score: number;
  ago: string;
  color: "red" | "amber" | "violet";
};

type AddressRow = {
  address: string;
  cluster: string;
  score: number;
  delta: string;
  volume: string;
  seen: string;
  status: "Critical" | "Review" | "Monitor";
};


// STILL MOCK, deliberately. The backend exposes no address list/search
// endpoint -- only GET /address/{address_id}/risk, which scores one known
// address at a time. There is also no source for this table's `cluster`,
// `delta`, `volume` or `seen` columns anywhere in the API (AddressRisk
// carries address, risk_score, contributing_factors, last_updated only), so
// populating it from real data would mean inventing those values client-side.
// Replace once a list/search endpoint exists.
const addresses: AddressRow[] = [
  { address: "bc1q8r3v…8f2", cluster: "C-1048", score: 0.87, delta: "+0.12", volume: "18.42 BTC", seen: "2 min", status: "Critical" },
  { address: "3J98t1Wp…2Xh", cluster: "C-0981", score: 0.74, delta: "+0.08", volume: "6.81 BTC", seen: "7 min", status: "Review" },
  { address: "bc1p5x0y…k4m", cluster: "C-1120", score: 0.69, delta: "+0.03", volume: "3.22 BTC", seen: "12 min", status: "Review" },
  { address: "1FfmbHfn…qT7", cluster: "C-0874", score: 0.53, delta: "−0.04", volume: "9.16 BTC", seen: "18 min", status: "Monitor" },
  { address: "bc1q0v4d…w9c", cluster: "C-0994", score: 0.41, delta: "+0.01", volume: "1.78 BTC", seen: "24 min", status: "Monitor" },
];

const navItems = [
  { label: "Overview", icon: LayoutDashboard },
  { label: "Risk signals", icon: Activity, count: "12" },
  { label: "Transaction graph", icon: Network },
  { label: "Address explorer", icon: Search },
];

const ALERT_THRESHOLD = 0.8;
const ALERT_LIMIT = 12;

/** "2m ago" / "3h ago" from an ISO timestamp. */
function timeAgo(iso: string): string {
  const seconds = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`;
  return `${Math.round(seconds / 86400)}d ago`;
}

/**
 * Adapt one API alert to the local feed shape.
 *
 * `kind` and `color` are derived from the score band rather than invented per
 * row, and `detail` reuses the server's own `reason` text, so nothing here
 * fabricates a signal the backend did not report.
 */
function toFeedAlert(row: ApiAlert): Alert {
  const color: Alert["color"] = row.risk_score >= 0.9 ? "red" : row.risk_score >= 0.85 ? "amber" : "violet";
  const kind = row.risk_score >= 0.9 ? "HIGH RISK" : row.risk_score >= 0.85 ? "ELEVATED" : "REVIEW";
  return { id: row.id, address: row.address, kind, detail: row.reason, score: row.risk_score, ago: timeAgo(row.flagged_at), color };
}

function RiskScore({ value, size = "md" }: { value: number; size?: "sm" | "md" | "lg" }) {
  const color = value >= 0.8 ? "critical" : value >= 0.6 ? "review" : "monitor";
  return <span className={`risk-score ${color} ${size}`}>{value.toFixed(2)}</span>;
}

function MiniSparkline({ points, accent = "teal" }: { points: number[]; accent?: "teal" | "violet" | "red" }) {
  const width = 96;
  const height = 28;
  const max = Math.max(...points);
  const min = Math.min(...points);
  const path = points
    .map((point, index) => {
      const x = (index / (points.length - 1)) * width;
      const y = height - ((point - min) / (max - min || 1)) * 20 - 4;
      return `${index === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg className={`sparkline ${accent}`} viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
      <path d={path} fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
    </svg>
  );
}

function NetworkMap() {
  return (
    <HudFrame tag="TRANSACTION GRAPH // LIVE TOPOLOGY" withScanline>
      <div className="network-map" aria-label="Interactive transaction graph visualization" style={{ margin: 0, border: 0 }}>
        <div className="graph-grid" />
        <svg viewBox="0 0 640 280" preserveAspectRatio="none" className="graph-lines" aria-hidden="true">
          <defs>
            <linearGradient id="edgeGlow" x1="0" x2="1">
              <stop offset="0" stopColor="#2dd4bf" stopOpacity="0.1" />
              <stop offset="0.5" stopColor="#2dd4bf" stopOpacity="0.55" />
              <stop offset="1" stopColor="#7f77dd" stopOpacity="0.18" />
            </linearGradient>
          </defs>
          <path d="M126 138 C180 112, 180 72, 242 62 S340 90, 386 72 S480 72, 538 96" />
          <path d="M126 138 C190 160, 212 202, 276 184 S360 142, 386 72" />
          <path d="M126 138 C186 144, 206 122, 276 128 S384 154, 448 190 S512 196, 538 96" />
          <path d="M276 184 C324 212, 368 206, 430 218 S512 196, 538 96" />
          <path d="M242 62 C260 90, 260 112, 276 128" />
          <path d="M386 72 C416 106, 410 152, 448 190" />
        </svg>
        <div className="graph-edge-label label-top">0.92 PPR</div>
        <div className="graph-edge-label label-bottom">18.4 BTC</div>
        <button className="graph-node node-root" onClick={() => playUiSound("click")} aria-label="Selected address bc1q8r3v…8f2"><span>bc1q8r3v…8f2</span></button>
        <button className="graph-node node-a" onClick={() => playUiSound("click")} aria-label="Connected address"><span>0.74</span></button>
        <button className="graph-node node-b" onClick={() => playUiSound("click")} aria-label="Connected address"><span>0.68</span></button>
        <button className="graph-node node-c" onClick={() => playUiSound("click")} aria-label="Connected address"><span>0.49</span></button>
        <button className="graph-node node-d" onClick={() => playUiSound("click")} aria-label="Connected address"><span>0.71</span></button>
        <button className="graph-node node-e" onClick={() => playUiSound("click")} aria-label="Connected address"><span>0.35</span></button>
        <button className="graph-node node-f" onClick={() => playUiSound("click")} aria-label="Connected address"><span>0.27</span></button>
        <div className="graph-legend"><span><i className="legend-dot root" /> selected</span><span><i className="legend-dot high" /> elevated</span><span><i className="legend-dot low" /> normal</span></div>
        <div className="graph-toolbar"><button onClick={() => playUiSound("click")} aria-label="Zoom in">+</button><button onClick={() => playUiSound("click")} aria-label="Zoom out">−</button><button onClick={() => playUiSound("click")} aria-label="Reset graph"><RefreshCw size={13} /></button></div>
      </div>
    </HudFrame>
  );
}

function GnnPipeline() {
  return (
    <HudFrame tag="GNN FUSION PIPELINE // 184ms INFERENCE">
      <div className="pipeline-wrap" style={{ margin: 0, border: 0 }}>
        <div className="pipeline-stage stage-input"><span className="stage-kicker">ADDRESS IN</span><strong>bc1q…8f2</strong><small>new observation</small></div>
        <div className="pipeline-arrow"><span /></div>
        <div className="pipeline-neighborhood"><span className="stage-kicker">NEIGHBORHOOD</span><div className="neighborhood-orbit"><i /><i /><i /><i /><b /></div><small>14 connected nodes</small></div>
        <div className="pipeline-arrow"><span /></div>
        <div className="pipeline-layers"><span className="stage-kicker">GRAPHSAGE</span><div className="layer-stack"><b /><b /><b /></div><small>3 inference layers</small></div>
        <div className="pipeline-arrow"><span /></div>
        <div className="pipeline-fusion"><span className="stage-kicker">FUSION ENGINE</span><div className="fusion-ring"><strong>0.87</strong></div><small>GNN 0.82 · traffic 0.91</small></div>
      </div>
    </HudFrame>
  );
}

function MetricCard({ label, value, note, trend, icon: Icon, accent, points }: { label: string; value: string; note: string; trend: string; icon: typeof Activity; accent: string; points: number[] }) {
  return (
    <div className="metric-card">
      <div className="metric-top"><span className={`metric-icon ${accent}`}><Icon size={15} /></span><span className="metric-label">{label}</span><MoreHorizontal size={15} className="metric-more" /></div>
      <div className="metric-value-row"><strong>{value}</strong><span className={`metric-trend ${trend.startsWith("+") ? "positive" : "negative"}`}>{trend.startsWith("+") ? <ArrowUpRight size={13} /> : <ArrowDownRight size={13} />}{trend}</span></div>
      <div className="metric-bottom"><span>{note}</span><MiniSparkline points={points} accent={accent === "violet" ? "violet" : accent === "red" ? "red" : "teal"} /></div>
    </div>
  );
}

export default function Home() {
  const [activeNav, setActiveNav] = useState("Overview");
  const [query, setQuery] = useState("");
  const [filterOpen, setFilterOpen] = useState(false);
  // Live alerts from GET /alerts. Mapped onto the existing local `Alert` type
  // so the rendering below is unchanged: the backend sends
  // {id, address, risk_score, reason, flagged_at} and this fills in the
  // presentational fields (kind/detail/color/ago) that have no API equivalent.
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [alertsLoading, setAlertsLoading] = useState(true);
  const [alertsError, setAlertsError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setAlertsLoading(true);
    setAlertsError("");
    listAlerts(ALERT_THRESHOLD, ALERT_LIMIT)
      .then((rows) => {
        if (cancelled) return;
        setAlerts(rows.map(toFeedAlert));
        setAlertsLoading(false);
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setAlertsLoading(false);
        // NetworkError extends ApiError, so it is tested first; UnauthorizedError
        // means the token expired mid-session, which is the route guard's case.
        if (error instanceof UnauthorizedError) {
          clearToken();
          window.location.href = "/login";
          return;
        }
        if (error instanceof NetworkError) setAlertsError("Can't reach the SentriX API.");
        else if (error instanceof ApiError) setAlertsError(`Alerts unavailable (HTTP ${error.status}).`);
        else setAlertsError("Alerts unavailable.");
      });
    return () => { cancelled = true; };
  }, []);

  const [selectedAddress, setSelectedAddress] = useState(addresses[0]);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [querySent, setQuerySent] = useState(false);
  const [mobileNav, setMobileNav] = useState(false);
  const [profile, setProfile] = useState<UserProfile>(readAuthenticatedProfile);
  const [profileOpen, setProfileOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [logoutOpen, setLogoutOpen] = useState(false);
  const [theme, setTheme] = useState<"midnight" | "dusk">(() => (localStorage.getItem("sentrix-theme") as "midnight" | "dusk") || "midnight");
  const [notifications, setNotifications] = useState(() => localStorage.getItem("sentrix-notifications") !== "off");
  const [logoTransition, setLogoTransition] = useState(() => sessionStorage.getItem("sentrix-logo-transition") === "login-to-platform");

  useEffect(() => { localStorage.setItem("sentrix-profile", JSON.stringify(profile)); }, [profile]);
  useEffect(() => { const syncProfile = () => setProfile(readAuthenticatedProfile()); window.addEventListener("storage", syncProfile); window.addEventListener("sentrix:auth-change", syncProfile); return () => { window.removeEventListener("storage", syncProfile); window.removeEventListener("sentrix:auth-change", syncProfile); }; }, []);
  useEffect(() => { localStorage.setItem("sentrix-theme", theme); document.documentElement.dataset.dashboardTheme = theme; }, [theme]);
  useEffect(() => { localStorage.setItem("sentrix-notifications", notifications ? "on" : "off"); }, [notifications]);
  useEffect(() => { if (!logoTransition) return; sessionStorage.removeItem("sentrix-logo-transition"); const timer = window.setTimeout(() => setLogoTransition(false), 950); return () => window.clearTimeout(timer); }, [logoTransition]);

  const filteredAddresses = useMemo(() => {
    const normalized = query.toLowerCase().trim();
    if (!normalized) return addresses;
    return addresses.filter((row) => [row.address, row.cluster, row.status].some((field) => field.toLowerCase().includes(normalized)));
  }, [query]);

  const refresh = () => {
    setIsRefreshing(true);
    window.setTimeout(() => setIsRefreshing(false), 850);
  };

  return (
    <div className={`app-shell dashboard-theme-${theme}`}><DashboardCursor />{logoTransition && <div className="dashboard-entry-transition"><span className="sentrix-x-mark dashboard-x-mark" aria-label="SentriX logo">X</span><span>LOADING SIGNAL DESK</span></div>}
      <aside className={`sidebar ${mobileNav ? "open" : ""}`}>
        <div className="brand" role="button" tabIndex={0} style={{ cursor: "pointer" }} onClick={() => { if (window.__sentrixNavigate) window.__sentrixNavigate("/"); else window.location.href = "/"; }}><span className="brand-image sentrix-x-mark" aria-label="SentriX logo">X</span><div><strong>SENTRIX</strong><small>TRANSACTION INTELLIGENCE</small></div><button className="sidebar-close" onClick={(e) => { e.stopPropagation(); setMobileNav(false); }} aria-label="Close navigation"><X size={17} /></button></div>
        <div className="workspace-label">WORKSPACE</div>
        <button className="workspace-switch"><span className="workspace-avatar">X</span><span><strong>Project SentriX</strong><small>Analyst workspace</small></span><ChevronDown size={14} /></button>
        <nav className="primary-nav" aria-label="Primary navigation">
          {navItems.map((item) => { const Icon = item.icon; return <button key={item.label} className={activeNav === item.label ? "active" : ""} onClick={() => { setActiveNav(item.label); setMobileNav(false); }}><Icon size={16} /><span>{item.label}</span>{item.count && <em>{item.count}</em>}</button>; })}
        </nav>
        <div className="sidebar-divider" />
        <div className="workspace-label">PIPELINE</div>
        <div className="pipeline-status"><div className="status-row"><span className="status-pulse" /> <span>Live rescoring loop</span><strong>ON</strong></div><div className="status-copy">Last cycle completed <b>2m ago</b><br />Next cycle in <b>08:42</b></div><div className="progress-line"><span /></div></div>
        <div className="sidebar-links"><button><Database size={15} /> Data sources <span>2/2</span></button><button><GitBranch size={15} /> Model registry <span>v1.4.2</span></button><button><Settings size={15} /> Workspace settings</button></div>
        <div className="sidebar-bottom"><button className="help-link"><CircleHelp size={15} /> Documentation</button><button className="profile profile-trigger" onClick={() => setProfileOpen(!profileOpen)}><div className="profile-avatar">{profile.initials}</div><div><strong>{profile.name}</strong><small>{profile.role}</small></div><MoreHorizontal size={15} /></button></div>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <div className="topbar-left">
            <button className="mobile-menu" onClick={() => setMobileNav(true)} aria-label="Open navigation"><Menu size={19} /></button>
            <div className="breadcrumb"><span>Workspace</span><b>/</b><strong>{activeNav}</strong></div>
          </div>
          <div className="topbar-actions">
            <SoundToggle />
            <div className="live-pill"><span className="status-pulse" /> LIVE MONITORING</div>
            <button className="icon-button" aria-label="Refresh dashboard" onClick={() => { playUiSound("click"); refresh(); }}><RefreshCw size={16} className={isRefreshing ? "spin" : ""} /></button>
            <button className="icon-button" aria-label="Notifications" onClick={() => { playUiSound("click"); setNotifications(!notifications); }}><AlertTriangle size={16} /><i /></button>
            <div className="profile-menu-wrap">
              <button className="top-avatar" onClick={() => { playUiSound("click"); setProfileOpen(!profileOpen); }} aria-expanded={profileOpen} aria-label="Open profile menu">{profile.initials}</button>
              {profileOpen && (
                <div className="profile-menu">
                  <div className="profile-menu-head"><div className="top-avatar large">{profile.initials}</div><div><strong>{profile.name}</strong><small>{profile.email}</small></div></div>
                  <button onClick={() => { setSettingsOpen(true); setProfileOpen(false); }}><UserRound size={14} /> Account settings</button>
                  <button onClick={() => { setSettingsOpen(true); setProfileOpen(false); }}><Settings size={14} /> Workspace settings</button>
                  <button className="quick-theme" onClick={() => { playUiSound("click"); setTheme(theme === "midnight" ? "dusk" : "midnight"); }}><span>{theme === "midnight" ? <Sun size={14} /> : <Moon size={14} />} Quick {theme === "midnight" ? "light" : "dark"} mode</span><i className={`quick-switch ${theme === "dusk" ? "on" : ""}`} /></button>
                  <button onClick={() => setProfileOpen(false)}><ShieldCheck size={14} /> Session secured</button>
                  <button className="logout-menu-item" onClick={() => { setLogoutOpen(true); setProfileOpen(false); }}><LogOut size={14} /> Log out</button>
                </div>
              )}
            </div>
          </div>
        </header>

        <div className="content-wrap">
          <section className="hero-row"><div><div className="eyebrow"><span className="eyebrow-line" /> SYSTEM OVERVIEW</div><h1>Good evening, <em>User.</em></h1><p>Live intelligence across the Bitcoin network, tuned for signal over noise.</p></div><div className="hero-meta"><span><Clock3 size={14} /> Tuesday, 08 Sep 2026</span><span><Radio size={14} /> Block <b>#912,481</b></span></div></section>

          <section className="metric-grid" aria-label="Network metrics">
            <MetricCard label="Addresses monitored" value="184,392" note="Across 12 active clusters" trend="+4.8%" icon={Globe2} accent="teal" points={[25, 30, 28, 36, 34, 42, 50, 46, 55]} />
            <MetricCard label="High-risk signals" value="12" note="4 new in the last hour" trend="+3" icon={AlertTriangle} accent="red" points={[36, 30, 38, 32, 44, 43, 50, 46, 63]} />
            <MetricCard label="Transactions analyzed" value="2.84M" note="Ledger + traffic signals" trend="+12.6%" icon={Layers} accent="violet" points={[22, 28, 26, 34, 32, 44, 42, 50, 59]} />
            <MetricCard label="Model confidence" value="94.2%" note="GraphSAGE · v1.4.2" trend="−0.8%" icon={ShieldCheck} accent="teal" points={[58, 52, 54, 56, 52, 50, 48, 47, 45]} />
          </section>

          <section className="section-heading"><div><div className="eyebrow"><span className="eyebrow-line" /> INVESTIGATION SURFACE</div><h2>Signal desk</h2></div><div className="section-actions"><button className="secondary-button" onClick={() => setFilterOpen(!filterOpen)}><SlidersHorizontal size={14} /> Filters <ChevronDown size={13} /></button><button className="primary-button" onClick={() => { playUiSound("radar"); refresh(); }}><RefreshCw size={14} className={isRefreshing ? "spin" : ""} /> Rescore now</button></div></section>

          {filterOpen && <div className="filter-bar"><span>Showing</span><button className="filter-chip active">All signals <X size={12} /></button><button className="filter-chip">Risk &gt; 0.6</button><button className="filter-chip">Last 24 hours</button><button className="filter-reset" onClick={() => setFilterOpen(false)}>Clear filters</button></div>}

          <section className="desk-grid">
            <div className="panel table-panel">
              <div className="panel-header"><div><h3>Risk-ranked addresses</h3><p>Prioritized by fused GNN + traffic score</p></div><button className="panel-menu" aria-label="Table options"><MoreHorizontal size={17} /></button></div>
              <div className="table-tools"><div className="search-field"><Search size={14} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search address or cluster" /><kbd>/</kbd></div><button className="filter-icon-button" aria-label="Filter address list"><Filter size={14} /></button></div>
              <div className="risk-table-wrap">
                <table className="risk-table">
                  <thead><tr><th>ADDRESS</th><th>CLUSTER</th><th>RISK SCORE <ChevronDown size={12} /></th><th>24H Δ</th><th>VOLUME</th><th>LAST SEEN</th><th /></tr></thead>
                  <tbody>
                    {filteredAddresses.map((row) => (
                      <tr
                        key={row.address}
                        className={selectedAddress.address === row.address ? "selected" : ""}
                        onClick={() => { playUiSound("click"); setSelectedAddress(row); }}
                      >
                        <td>
                          <div className="address-cell">
                            <span className={`address-dot ${row.status.toLowerCase()}`} />
                            <div>
                              <strong><ScrambleText text={row.address} /></strong>
                              <small>{row.status}</small>
                            </div>
                          </div>
                        </td>
                        <td><span className="cluster-tag">{row.cluster}</span></td>
                        <td><RiskScore value={row.score} /></td>
                        <td><span className={row.delta.startsWith("+") ? "delta-up" : "delta-down"}>{row.delta}</span></td>
                        <td className="muted-cell">{row.volume}</td>
                        <td className="muted-cell">{row.seen}</td>
                        <td><button className="row-more" aria-label={`More options for ${row.address}`} onClick={(event) => event.stopPropagation()}><MoreHorizontal size={15} /></button></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="panel-footer"><span>Showing {filteredAddresses.length} of 184,392 addresses</span><button>View address explorer <ExternalLink size={12} /></button></div>
            </div>

            <div className="panel alerts-panel">
              <div className="panel-header"><div><h3>Live signal feed</h3><p>New flags as they land</p></div><span className="feed-live"><span className="status-pulse" /> STREAMING</span></div>
              <div className="alert-list">
                {alertsLoading && <div className="alert-empty" role="status"><Loader2 className="alert-spinner" size={14} /> Loading live signals…</div>}
                {!alertsLoading && alertsError !== "" && <div className="alert-empty error" role="alert"><AlertTriangle size={14} /> {alertsError}</div>}
                {!alertsLoading && alertsError === "" && alerts.length === 0 && <div className="alert-empty" role="status"><ShieldCheck size={14} /> No alerts at or above {ALERT_THRESHOLD.toFixed(2)}.</div>}
                {!alertsLoading && alertsError === "" && alerts.map((alert) => (
                  <button
                    className="alert-item"
                    key={alert.id}
                    onClick={() => {
                      playUiSound("radar");
                      setSelectedAddress(addresses.find((row) => row.score === alert.score) ?? addresses[0]);
                    }}
                  >
                    <span className={`alert-icon ${alert.color}`}>{alert.color === "red" ? <AlertTriangle size={14} /> : alert.color === "violet" ? <Radio size={14} /> : <GitBranch size={14} />}</span>
                    <span className="alert-copy"><strong>{alert.kind}</strong><span><ScrambleText text={alert.address} /> · {alert.detail}</span></span>
                    <span className="alert-meta"><RiskScore value={alert.score} size="sm" /><small>{alert.ago}</small></span>
                  </button>
                ))}
              </div>
              <div className="panel-footer"><button className="full-link">Open all alerts <ArrowUpRight size={13} /></button></div>
            </div>
          </section>

          <section className="lower-grid"><div className="panel graph-panel"><div className="panel-header"><div><h3>Transaction neighborhood</h3><p>Cluster <span className="mono">{selectedAddress.cluster}</span> · 14 connected addresses</p></div><div className="panel-header-actions"><button className="icon-button small" aria-label="Graph settings"><SlidersHorizontal size={14} /></button><button className="panel-menu" aria-label="Graph options"><MoreHorizontal size={17} /></button></div></div><NetworkMap /><div className="graph-footer"><span><span className="selection-dot" /> Selected <b>{selectedAddress.address}</b></span><button>Open graph explorer <ArrowUpRight size={13} /></button></div></div><div className="panel detail-panel"><div className="panel-header"><div><h3>Address intelligence</h3><p>Explainable risk breakdown</p></div><span className="detail-id">#{selectedAddress.cluster.replace("C-", "")}</span></div><div className="detail-address"><span className="address-dot critical" /><div><strong>{selectedAddress.address}</strong><small>First seen 03 Sep 2026 · Cluster {selectedAddress.cluster}</small></div><button aria-label="Copy address"><Check size={14} /></button></div><div className="score-detail"><div className="score-orbit"><div><span>FUSED RISK</span><strong>{selectedAddress.score.toFixed(2)}</strong><small>HIGH RISK</small></div></div><div className="factor-list"><div><span><i className="factor-dot teal" /> GNN ledger score</span><b>0.82</b></div><div><span><i className="factor-dot violet" /> Traffic anomaly</span><b>0.91</b></div><div><span><i className="factor-dot amber" /> PPR proximity</span><b>0.76</b></div></div></div><div className="confidence-row"><span>MODEL CONFIDENCE</span><b>94.2%</b><div className="confidence-bar"><span /></div></div><button className="outline-action"><Terminal size={14} /> View full address history <ArrowUpRight size={13} /></button></div></section>

          <section className="pipeline-panel panel"><div className="pipeline-header"><div><div className="eyebrow"><span className="eyebrow-line" /> MODEL ACTIVITY</div><h2>Live GNN pipeline</h2><p>Watch the latest observation move through graph analysis, traffic correlation, and explainable fusion.</p></div><div className="pipeline-live"><span className="status-pulse" /> INFERENCE ACTIVE <span>184ms</span></div></div><GnnPipeline /><div className="pipeline-caption"><span><Sparkles size={13} /> Animation slowed for observability · real inference completes in milliseconds</span><button onClick={refresh}><Play size={12} /> Replay sequence</button></div></section>

          <section className="nlq-panel"><div className="nlq-icon"><Bot size={18} /></div><div className="nlq-copy"><span className="eyebrow"><span className="eyebrow-line" /> NATURAL LANGUAGE QUERY</span><h3>Ask the graph in plain English.</h3><p>Translate investigator questions into traceable Cypher queries without leaving the signal desk.</p></div><div className="nlq-form"><div className="nlq-input"><Search size={15} /><input value={querySent ? "Show addresses connected to bc1q…8f2 with risk above 0.8" : "Try: show high-risk addresses near bc1q…8f2"} onChange={(event) => { setQuerySent(false); setQuery(event.target.value); }} /><kbd>⌘ ↵</kbd></div><button className="primary-button" onClick={() => setQuerySent(true)}><Zap size={14} /> Run query</button></div>{querySent && <div className="nlq-result"><CheckCircle2 size={14} /> Query translated to Cypher · 8 matching addresses found <button onClick={() => setQuerySent(false)}><X size={13} /></button></div>}</section>

          <footer className="app-footer"><span>SENTRIX / INTERNAL ANALYST CONSOLE</span><span>Data refreshed 2m ago · <b>All systems nominal</b> <CheckCircle2 size={12} /></span></footer>
        </div>
      </main>
      {settingsOpen && <PreferencesModal profile={profile} setProfile={setProfile} theme={theme} setTheme={setTheme} notifications={notifications} setNotifications={setNotifications} onClose={() => setSettingsOpen(false)} />}{logoutOpen && <LogoutModal onCancel={() => setLogoutOpen(false)} onConfirm={() => { localStorage.removeItem("sentrix-profile"); localStorage.removeItem("sentrix-theme"); localStorage.removeItem("sentrix-notifications"); sessionStorage.setItem("sentrix-logo-transition", "platform-to-login"); window.location.href = "/login"; }} />}
    </div>
  );
}

export function NotFound() { return <div>Not found</div>; }
