import { useEffect, useMemo, useState } from "react";
import { ArrowDownRight, ArrowRight, ArrowUpRight, Check, ChevronLeft, ChevronRight, Copy, Lock, Menu, Plus, Radio, ShieldCheck, Terminal, X } from "lucide-react";
import {
  WebGLBackground,
  ScrollIndicator,
  SlotButton,
  ScrambleText,
  HudFrame,
  SoundToggle,
  SentrixIntro,
  playUiSound,
} from "@/components/motion";

type NodeData = { id: string; x: number; y: number; r: number; label: string; value: string; tone: "green" | "violet" | "red" | "muted" };
const nodes: NodeData[] = [
  { id: "root", x: 48, y: 48, r: 13, label: "Entity / C-1048", value: "0.87 risk · 18.42 BTC", tone: "green" },
  { id: "a", x: 28, y: 28, r: 7, label: "Address / bc1q…8f2", value: "0.74 risk · 6.81 BTC", tone: "violet" },
  { id: "b", x: 68, y: 24, r: 6, label: "Address / 3J98…2Xh", value: "0.69 risk · 3.22 BTC", tone: "red" },
  { id: "c", x: 75, y: 64, r: 8, label: "Cluster / C-1120", value: "14 linked addresses", tone: "violet" },
  { id: "d", x: 26, y: 72, r: 5, label: "Address / 1Ffm…qT7", value: "0.53 risk · 9.16 BTC", tone: "muted" },
  { id: "e", x: 58, y: 79, r: 4, label: "Relay / node-44", value: "0.91 traffic anomaly", tone: "red" },
  { id: "f", x: 87, y: 39, r: 4, label: "Address / bc1p…k4m", value: "0.41 risk · 1.78 BTC", tone: "muted" },
];
const edges: [string, string, string][] = [["root", "a", "0.92 PPR"], ["root", "b", "6.81 BTC"], ["root", "c", "0.74 PPR"], ["root", "d", "0.31 PPR"], ["root", "e", "relay"], ["b", "f", "1.9 BTC"], ["c", "e", "timing"]];
const capabilities = [
  {
    number: "01",
    title: "REAL-TIME MONITORING",
    body: "A live view of the ledger and the network around it. Every new observation enters a continuous rescoring loop, so the signal stays current while the chain keeps moving.",
    stat: "184,392",
    meta: "ADDRESSES OBSERVED",
    kind: "pulse",
    highlights: ["Sub-second block ingestion", "Continuous mempool rescoring", "Live peer gossip telemetry"],
  },
  {
    number: "02",
    title: "RISK INTELLIGENCE",
    body: "GraphSAGE embeddings, Personalized PageRank (PPR), and P2P traffic anomaly signals converge into one explainable score. Not a black box — a fully accountable trail of evidence.",
    stat: "0.87",
    meta: "FUSED RISK SCORE",
    kind: "rings",
    highlights: ["GraphSAGE GNN inductive learning", "Dual-signal anomaly reconciliation", "Automated compliance audit trails"],
  },
  {
    number: "03",
    title: "RELATIONSHIP MAPPING",
    body: "See the hidden shape of activity: entities, clusters, relay paths, and the relationships that only emerge when the high-dimensional graph is allowed to speak.",
    stat: "14",
    meta: "CONNECTED NODES",
    kind: "nodes",
    highlights: ["Force-directed cluster discovery", "Mixer & peel chain unraveling", "Multi-hop taint propagation"],
  },
  {
    number: "04",
    title: "TRANSACTION ANALYTICS",
    body: "Move seamlessly from the macro pattern to the address-level detail without losing context. Volume, timing, historical drift, and forensic context in one continuous surface.",
    stat: "2.84M",
    meta: "TRANSACTIONS ANALYZED",
    kind: "bars",
    highlights: ["Historical UTXO flow velocity", "Temporal timing correlation", "Entity volume aggregation"],
  },
];

function NetworkField({ compact = false }: { compact?: boolean }) {
  const [selected, setSelected] = useState<NodeData>(nodes[0]);
  const [pointer, setPointer] = useState({ x: 0, y: 0 });
  const [active, setActive] = useState(false);
  const selectedIndex = nodes.findIndex((node) => node.id === selected.id);
  return <div className={`network-field ${compact ? "compact" : ""}`} onPointerMove={(event) => { const rect = event.currentTarget.getBoundingClientRect(); setPointer({ x: ((event.clientX - rect.left) / rect.width - .5) * 18, y: ((event.clientY - rect.top) / rect.height - .5) * 18 }); }} onPointerEnter={() => setActive(true)} onPointerLeave={() => { setActive(false); setPointer({ x: 0, y: 0 }); }}>
    <div className="network-noise" /><div className="network-crosshair" />
    <svg className="network-svg" viewBox="0 0 100 100" preserveAspectRatio="none" aria-label="Interactive transaction network">
      <defs><linearGradient id="signalLine" x1="0" x2="1"><stop offset="0" stopColor="#2dd4bf" stopOpacity=".06" /><stop offset=".5" stopColor="#a7f3e0" stopOpacity=".72" /><stop offset="1" stopColor="#7f77dd" stopOpacity=".14" /></linearGradient><filter id="softGlow"><feGaussianBlur stdDeviation=".55" /></filter></defs>
      <g className="network-lines" style={{ transform: `translate(${pointer.x * -.06}px, ${pointer.y * -.06}px)` }}>{edges.map(([from, to, label], index) => { const a = nodes.find((node) => node.id === from)!; const b = nodes.find((node) => node.id === to)!; return <g key={`${from}-${to}`}><path d={`M${a.x} ${a.y} C ${(a.x + b.x) / 2} ${a.y - 12 - index * 1.3}, ${(a.x + b.x) / 2} ${b.y + 12}, ${b.x} ${b.y}`} /><text x={(a.x + b.x) / 2} y={(a.y + b.y) / 2 - 1}>{label}</text></g>; })}</g>
      <g className="network-particles">{[18, 31, 47, 64, 79].map((cx, i) => <circle key={cx} cx={cx} cy={32 + (i % 2) * 29} r=".6" style={{ animationDelay: `${i * .25}s` }} />)}</g>
      <g className="network-nodes" style={{ transform: `translate(${pointer.x * .12}px, ${pointer.y * .12}px)` }}>{nodes.map((node, index) => <g key={node.id} className={`data-node ${selected.id === node.id ? "is-selected" : ""} tone-${node.tone}`} onClick={() => setSelected(node)} role="button" tabIndex={0} aria-label={node.label} onKeyDown={(event) => event.key === "Enter" && setSelected(node)}><circle className="node-aura" cx={node.x} cy={node.y} r={node.r * 1.9} /><circle className="node-core" cx={node.x} cy={node.y} r={node.r / 2.2} /><circle className="node-ring" cx={node.x} cy={node.y} r={node.r} style={{ animationDelay: `${index * .22}s` }} /></g>)}</g>
    </svg>
    <div className="network-label network-label-top"><span>LIVE GRAPH / 08.09.26</span><span>BLOCK #912,481</span></div><div className={`network-selected ${active ? "is-active" : ""}`}><div className="selected-kicker"><span className="signal-dot" /> SELECTED SIGNAL <button onClick={() => setSelected(nodes[selectedIndex === nodes.length - 1 ? 0 : selectedIndex + 1])} aria-label="Select next signal"><ArrowRight size={12} /></button></div><strong>{selected.label}</strong><span>{selected.value}</span></div><div className="network-legend"><span><i className="legend-green" /> ledger</span><span><i className="legend-violet" /> entity</span><span><i className="legend-red" /> anomaly</span></div><div className="network-hint"><span>MOVE TO EXPLORE</span><span>CLICK A NODE</span></div>
  </div>;
}

function Cursor() { const [position, setPosition] = useState({ x: -100, y: -100 }); const [trail, setTrail] = useState({ x: -100, y: -100 }); const [hover, setHover] = useState(false); useEffect(() => { let frame = 0; let current = { x: -100, y: -100 }; const move = (event: MouseEvent) => setPosition({ x: event.clientX, y: event.clientY }); const animate = () => { current = { x: current.x + (position.x - current.x) * .18, y: current.y + (position.y - current.y) * .18 }; setTrail(current); frame = requestAnimationFrame(animate); }; const enter = () => setHover(true); const leave = () => setHover(false); window.addEventListener("mousemove", move); const interactive = Array.from(document.querySelectorAll("a, button, [role=button]")); interactive.forEach((element) => { element.addEventListener("mouseenter", enter); element.addEventListener("mouseleave", leave); }); frame = requestAnimationFrame(animate); return () => { cancelAnimationFrame(frame); window.removeEventListener("mousemove", move); interactive.forEach((element) => { element.removeEventListener("mouseenter", enter); element.removeEventListener("mouseleave", leave); }); }; }, [position]); return <><div className={`custom-cursor-trail ${hover ? "hover" : ""}`} style={{ left: trail.x, top: trail.y }} /><div className={`custom-cursor ${hover ? "hover" : ""}`} style={{ left: position.x, top: position.y }}><span>{hover ? "VIEW" : ""}</span></div></>; }
function HeroLogo({ onNavigate }: { onNavigate: (id: string) => void }) { const [tilt, setTilt] = useState({ x: 0, y: 0 }); const onMove = (event: React.PointerEvent<HTMLDivElement>) => { const rect = event.currentTarget.getBoundingClientRect(); setTilt({ x: ((event.clientY - rect.top) / rect.height - .5) * -8, y: ((event.clientX - rect.left) / rect.width - .5) * 10 }); }; const orbitNodes = [{ label: "SYSTEM", id: "system", className: "orbit-system" }, { label: "WORKS", id: "intelligence", className: "orbit-intelligence" }, { label: "SERVICES", id: "capabilities", className: "orbit-services" }, { label: "CONTACT", id: "contact", className: "orbit-contact" }]; return <div className="hero-logo-object" onPointerMove={onMove} onPointerLeave={() => setTilt({ x: 0, y: 0 })} aria-label="Interactive SentriX X logo"><div className="hero-logo-halo" /><div className="hero-logo-depth depth-one" /><div className="hero-logo-depth depth-two" /><div className="hero-logo-face" style={{ transform: `rotateX(${tilt.x}deg) rotateY(${tilt.y}deg)` }}><svg viewBox="0 0 240 180" aria-hidden="true"><path className="z-mark-stroke" d="M36 42L204 138M204 42L36 138" /><path className="z-mark-glow" d="M36 42L204 138M204 42L36 138" pathLength="320" /><circle className="z-mark-dot" cx="36" cy="42" r="5" /></svg></div><span className="hero-logo-signal" /><div className="orbit-connector orbit-connector-v" /><div className="orbit-connector orbit-connector-h" />{orbitNodes.map((node) => <button key={node.id} className={`orbit-nav-node ${node.className}`} onClick={() => onNavigate(node.id)}><i /><span>{node.label}</span></button>)}</div>; }
function LoaderMark() { return <div className="loader-mark reference-loader-mark"><svg viewBox="0 0 240 180" aria-hidden="true"><path className="reference-loader-draw" d="M36 42L204 138M204 42L36 138" /><path className="reference-loader-fill" d="M40 50h120l-120 80h120l-18 10H21l120-80H22z" /></svg></div>; }
function Reveal({ children, className = "" }: { children: React.ReactNode; className?: string }) { const [visible, setVisible] = useState(false); useEffect(() => { const element = document.querySelector(`[data-reveal="${className}"]`); if (!element) return; const observer = new IntersectionObserver(([entry]) => { if (entry.isIntersecting) { setVisible(true); observer.disconnect(); } }, { threshold: .15 }); observer.observe(element); return () => observer.disconnect(); }, [className]); return <div data-reveal={className} className={`reveal ${visible ? "visible" : ""} ${className}`}>{children}</div>; }



const projects = [
  { slug: "graph-intelligence", title: "Graph Intelligence", category: "INVESTIGATION SYSTEM", year: "2026", video: "https://storage.googleapis.com/coverr-main/mp4/Mt_Baker.mp4", description: "An explainable graph surface for tracing entities, clusters, and the relationships hidden inside transaction activity." },
  { slug: "signal-fusion", title: "Signal Fusion", category: "RISK MODELING", year: "2026", video: "https://storage.googleapis.com/coverr-main/mp4/Footboys.mp4", description: "A dual-signal model that brings ledger behavior and network traffic into one readable risk narrative." },
];

function ProjectCard({ project }: { project: typeof projects[number] }) { return <button className="project-card" onClick={() => { if (window.__sentrixNavigate) window.__sentrixNavigate(`/works/${project.slug}`); else window.location.href = `/works/${project.slug}`; }}><div className="project-media"><video autoPlay muted loop playsInline preload="metadata" aria-label={`${project.title} preview`} src={project.video} /><div className="project-media-fallback" /></div><div className="project-card-copy"><div><span>{project.category}</span><h3>{project.title}</h3></div><div className="project-year">{project.year} <ArrowUpRight size={16} /></div></div><p>{project.description}</p></button>; }

const INQUIRY_TOPICS = [
  { id: "investigation", label: "INVESTIGATION ACCESS" },
  { id: "api", label: "API & TELEMETRY" },
  { id: "gnn", label: "CUSTOM GNN TRAINING" },
  { id: "enterprise", label: "ENTERPRISE DESK" },
];

function ContactForm() {
  const [form, setForm] = useState({
    name: "",
    email: "",
    org: "",
    topic: "investigation",
    message: "",
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [sent, setSent] = useState(false);
  const [dispatchId, setDispatchId] = useState("");
  const [copied, setCopied] = useState(false);

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const next: Record<string, string> = {};
    if (!form.name.trim()) next.name = "Operator identity required.";
    if (!/^\S+@\S+\.\S+$/.test(form.email)) next.email = "Valid communication endpoint required.";
    if (form.message.trim().length < 10) next.message = "Provide minimum 10 characters for forensic triage.";
    setErrors(next);
    if (!Object.keys(next).length) {
      playUiSound("confirm");
      const id = `SX-${Math.floor(100000 + Math.random() * 900000)}`;
      setDispatchId(id);
      setSent(true);
    } else {
      playUiSound("click");
    }
  };

  const copyDispatch = () => {
    navigator.clipboard?.writeText(dispatchId);
    setCopied(true);
    playUiSound("click");
    setTimeout(() => setCopied(false), 2000);
  };

  if (sent) {
    return (
      <div className="contact-terminal-receipt">
        <div className="receipt-header">
          <div className="receipt-status-pill">
            <span className="signal-dot" />
            <span>TRANSMISSION CONFIRMED</span>
          </div>
          <span className="receipt-timestamp">{new Date().toISOString().slice(0, 19).replace("T", " ")} UTC</span>
        </div>

        <div className="receipt-body">
          <div className="receipt-check-row">
            <div className="receipt-pulse-ring">
              <ShieldCheck size={26} className="receipt-icon" />
            </div>
            <div>
              <h3>Signal Logged to Surveillance Queue</h3>
              <p>Dispatch payload encrypted with recipient key and routed for investigator triage.</p>
            </div>
          </div>

          <div className="receipt-metadata-table">
            <div className="metadata-entry">
              <span>DISPATCH REF</span>
              <strong className="copy-ref-action" onClick={copyDispatch} title="Click to copy">
                {dispatchId} {copied ? "✓ COPIED" : "[COPY]"}
              </strong>
            </div>
            <div className="metadata-entry">
              <span>OPERATOR</span>
              <strong>{form.name}</strong>
            </div>
            <div className="metadata-entry">
              <span>ENDPOINT</span>
              <strong>{form.email}</strong>
            </div>
            <div className="metadata-entry">
              <span>ROUTING TOPIC</span>
              <strong style={{ color: "var(--green)" }}>{form.topic.toUpperCase()}</strong>
            </div>
          </div>
        </div>

        <div className="receipt-footer">
          <button
            type="button"
            className="receipt-reset-btn"
            onClick={() => {
              playUiSound("click");
              setSent(false);
              setForm({ name: "", email: "", org: "", topic: "investigation", message: "" });
            }}
          >
            DISPATCH ANOTHER TRANSMISSION
          </button>
        </div>
      </div>
    );
  }

  return (
    <form className="contact-terminal-form" onSubmit={submit} noValidate>
      <div className="form-header-bar">
        <div className="form-security-tag">
          <Lock size={11} />
          <span>END-TO-END ENCRYPTED COMMS CHANNEL</span>
        </div>
        <span className="form-channel-telemetry">PORT_08::SECURE</span>
      </div>

      {/* Topic selection pills */}
      <div className="form-field-group">
        <label className="field-label">SELECT INQUIRY VECTOR</label>
        <div className="topic-pills-row">
          {INQUIRY_TOPICS.map((t) => (
            <button
              key={t.id}
              type="button"
              className={`topic-pill ${form.topic === t.id ? "is-selected" : ""}`}
              onClick={() => {
                playUiSound("click");
                setForm((prev) => ({ ...prev, topic: t.id }));
              }}
            >
              <span className="topic-dot" />
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {/* Name and Email side-by-side */}
      <div className="form-split-row">
        <div className="form-field-group">
          <label className="field-label">
            OPERATOR / NAME <span className="req-star">*</span>
          </label>
          <input
            className={`terminal-input ${errors.name ? "has-error" : ""}`}
            value={form.name}
            onChange={(e) => {
              setForm({ ...form, name: e.target.value });
              if (errors.name) setErrors((prev) => ({ ...prev, name: "" }));
            }}
            placeholder="Analyst name or handle"
            autoComplete="name"
          />
          {errors.name && <small className="field-error">{errors.name}</small>}
        </div>

        <div className="form-field-group">
          <label className="field-label">
            WORK EMAIL / SECURE ENDPOINT <span className="req-star">*</span>
          </label>
          <input
            type="email"
            className={`terminal-input ${errors.email ? "has-error" : ""}`}
            value={form.email}
            onChange={(e) => {
              setForm({ ...form, email: e.target.value });
              if (errors.email) setErrors((prev) => ({ ...prev, email: "" }));
            }}
            placeholder="analyst@agency.gov or you@firm.com"
            autoComplete="email"
          />
          {errors.email && <small className="field-error">{errors.email}</small>}
        </div>
      </div>

      {/* Organization field */}
      <div className="form-field-group">
        <label className="field-label">ORGANIZATION / INSTITUTION</label>
        <input
          className="terminal-input"
          value={form.org}
          onChange={(e) => setForm({ ...form, org: e.target.value })}
          placeholder="Agency, exchange, compliance desk, or lab (optional)"
        />
      </div>

      {/* Message brief field */}
      <div className="form-field-group">
        <div className="field-label-row">
          <label className="field-label">
            DISPATCH BRIEF / FORENSIC REQUIREMENTS <span className="req-star">*</span>
          </label>
          <span className="char-count">{form.message.length} CHARS</span>
        </div>
        <textarea
          className={`terminal-input terminal-textarea ${errors.message ? "has-error" : ""}`}
          value={form.message}
          onChange={(e) => {
            setForm({ ...form, message: e.target.value });
            if (errors.message) setErrors((prev) => ({ ...prev, message: "" }));
          }}
          placeholder="Detail the transaction scope, address clusters, or API integration goals you wish to explore with our intelligence desk."
          rows={4}
        />
        {errors.message && <small className="field-error">{errors.message}</small>}
      </div>

      {/* Submit Action */}
      <div className="form-submit-row">
        <div className="form-assurance-note">
          <ShieldCheck size={14} style={{ color: "var(--green)", flexShrink: 0 }} />
          <span>Responses routed through Tier-1 cryptographic review desk.</span>
        </div>
        <button type="submit" className="terminal-submit-btn">
          <span>SEND TRANSMISSION</span>
          <ArrowUpRight size={14} />
        </button>
      </div>
    </form>
  );
}

export default function Home() {
  const [menuOpen, setMenuOpen] = useState(false);
  const [activeCapability, setActiveCapability] = useState(0);
  const [platformOpening, setPlatformOpening] = useState(false);
  const [platformProgress, setPlatformProgress] = useState(0);
  const scrollTo = (id: string) => {
    const clean = id.replace(/^#/, "");
    document.getElementById(clean)?.scrollIntoView({ behavior: "smooth" });
    setMenuOpen(false);
  };

  const selectCapability = (index: number) => {
    playUiSound("click");
    setActiveCapability(index);
  };

  const enterPlatform = () => {
    if (window.__sentrixNavigate) {
      window.__sentrixNavigate("/platform");
    } else {
      window.location.href = "/platform";
    }
  };

  return (
    <div className="immersive-site">
      <Cursor />
      {/* 1. Alche-style 3D WebGL Background Scene */}
      <WebGLBackground opacity={0.78} />

      {/* 2. Alche-style Cinematic Boot Screen / Sound Intro */}
      <SentrixIntro />

      {/* 3. Alche-style Vertical Telemetry Scroll Indicator */}
      <ScrollIndicator />

      {/* Platform Transition Portal */}
      <div className={`platform-transition ${platformOpening ? "active" : ""}`}>
        <div className="transition-logo-lock">
          <span className="sentrix-x-mark" aria-label="SentriX logo">X</span>
        </div>
        <div className="transition-progress" role="progressbar" aria-label="Loading platform" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(platformProgress)}>
          <i style={{ width: `${platformProgress}%` }} />
        </div>
        <span>ENTERING SENTRIX INTELLIGENCE DESK <b>{Math.round(platformProgress)}%</b></span>
      </div>

      {/* Header Navigation with Alche-Style Sound Toggle & SlotButtons */}
      <header className="site-nav">
        <button className="site-logo" onClick={() => scrollTo("top")} type="button">
          <span className="site-logo-image sentrix-x-mark" aria-label="SentriX logo">X</span>
          <span>
            <b><ScrambleText text="SENTRIX" /></b>
            <small>TRANSACTION INTELLIGENCE</small>
          </span>
        </button>

        <nav className={menuOpen ? "open" : ""}>
          {[
            { label: "WORKS", id: "intelligence" },
            { label: "ABOUT", id: "system" },
            { label: "SIGNALS", id: "signals" },
            { label: "MODEL", id: "gnn" },
            { label: "SERVICES", id: "capabilities" },
            { label: "CONTACT", id: "contact" },
          ].map((item) => (
            <SlotButton
              key={item.label}
              variant="nav"
              onClick={() => scrollTo(item.id)}
            >
              <ScrambleText text={item.label} />
            </SlotButton>
          ))}
          <SlotButton
            variant="primary"
            onClick={enterPlatform}
            icon={<ArrowUpRight size={13} />}
          >
            ENTER PLATFORM
          </SlotButton>
        </nav>

        <div style={{ display: "flex", alignItems: "center", gap: "12px", zIndex: 10 }}>
          <SoundToggle />
          <button className="nav-menu" onClick={() => setMenuOpen(!menuOpen)} aria-label="Toggle navigation" type="button">
            {menuOpen ? <X size={18} /> : <Menu size={18} />}
          </button>
        </div>
      </header>

      <main id="top">
        {/* HERO SECTION */}
        <section className="hero-section">
          <div className="hero-topline">
            <span>AI-POWERED MONITORING / 01</span>
            <span><span className="signal-dot" /> NETWORK STATUS: NOMINAL</span>
          </div>

          <HeroLogo onNavigate={scrollTo} />

          <div className="hero-type">
            <span><ScrambleText text="SENTRIX" /></span>
            <strong>
              <ScrambleText text="TRANSACTION" /><br />
              <em><ScrambleText text="INTELLIGENCE" /></em>
            </strong>
            <span className="hero-for">
              SEE THE<br />SIGNAL.
            </span>
          </div>

          <div className="hero-network">
            <HudFrame tag="LIVE GRAPH // #912,481" coordinates="37.7749° N, 122.4194° W" withScanline>
              <NetworkField />
            </HudFrame>
          </div>

          <div className="hero-bottom">
            <div className="hero-actions">
              <SlotButton
                variant="outline"
                onClick={() => scrollTo("system")}
                icon={<ArrowDownRight size={14} />}
              >
                SCROLL TO EXPLORE
              </SlotButton>
              <SlotButton
                variant="primary"
                onClick={enterPlatform}
                icon={<ArrowUpRight size={14} />}
              >
                ENTER PLATFORM
              </SlotButton>
            </div>
            <p>Where complex activity<br />becomes clear intelligence.</p>
            <span className="hero-index">01 <i /> 06</span>
          </div>
        </section>

        {/* PREMISE SECTION */}
        <section id="system" className="statement-section">
          <Reveal className="statement-inner">
            <HudFrame tag="PREMISE // 02" coordinates="BLOCK #912,481">
              <div style={{ padding: "40px 30px" }}>
                <span className="section-index">02 / THE PREMISE</span>
                <h2>
                  BITCOIN LEAVES<br />
                  A <em><ScrambleText text="TRAIL." /></em><br />
                  <span>WE TURN THE TRAIL<br />INTO INTELLIGENCE.</span>
                </h2>
                <div className="statement-note">
                  <span className="fine-line" />
                  <p>Every address is connected.<br />SentriX makes the connections legible.</p>
                </div>
              </div>
            </HudFrame>
          </Reveal>
        </section>

        {/* SELECTED WORK SECTION */}
        <section id="intelligence" className="intelligence-section works-section">
          <div className="section-heading-large">
            <span className="section-index">03 / SELECTED WORK</span>
            <h2>
              The network<br />
              <em><ScrambleText text="has a shape." /></em>
            </h2>
            <p>Click into the graph. Follow the path.<br />Find the signal beneath the activity.</p>
            <span className="works-meta">INTERACTIVE SYSTEM / 2026</span>
          </div>

          <HudFrame tag="GRAPH TOPOLOGY RECON" withScanline>
            <NetworkField compact />
          </HudFrame>

          <div className="project-grid">
            {projects.map((project) => (
              <ProjectCard key={project.slug} project={project} />
            ))}
          </div>
        </section>

        {/* SIGNALS SECTION */}
        <section id="signals" className="signals-section">
          <Reveal className="signals-inner">
            <span className="section-index">04 / TWO SIGNALS</span>
            <h2>
              ONE NETWORK.<br />
              <em><ScrambleText text="TWO WAYS OF SEEING." /></em>
            </h2>
            <HudFrame tag="DUAL-STREAM CONVERGENCE">
              <div className="signals-flow" style={{ padding: "30px 20px" }}>
                <article className="signal-stream ledger-stream">
                  <span className="stream-number">01</span>
                  <h3>BLOCKCHAIN<br />LEDGER</h3>
                  <p>Transaction graph<br />PPR enrichment<br />GraphSAGE inference</p>
                  <div className="stream-visual"><i /><i /><i /><b>0.82</b></div>
                </article>

                <div className="stream-convergence">
                  <span /><span />
                  <div>FUSION<br /><small>ENGINE</small></div>
                  <strong>0.87</strong>
                  <em>HIGH RISK</em>
                </div>

                <article className="signal-stream traffic-stream">
                  <span className="stream-number">02</span>
                  <h3>P2P<br />NETWORK</h3>
                  <p>Broadcast traffic<br />Relay timing<br />Anomaly signal</p>
                  <div className="traffic-lines"><i /><i /><i /><i /></div>
                  <div className="stream-score">0.91</div>
                </article>
              </div>
            </HudFrame>
          </Reveal>
        </section>

        {/* GNN MODEL SECTION */}
        <section id="gnn" className="gnn-section">
          <div className="gnn-heading">
            <span className="section-index">05 / LIVE MODEL VISUALIZATION</span>
            <h2>
              WATCH THE<br />
              <em><ScrambleText text="REASONING." /></em>
            </h2>
            <p>Signals move through the actual analysis path — from an address, through its neighborhood, into the score.</p>
          </div>

          <HudFrame tag="GNN PIPELINE // 184ms INFERENCE" withScanline>
            <div className="gnn-pipeline" style={{ margin: "0", border: "0", padding: "30px 20px" }}>
              <div className="gnn-node input"><span>ADDRESS IN</span><b>bc1q…8f2</b></div>
              <div className="gnn-arrow" />
              <div className="gnn-node neighborhood">
                <span>NEIGHBORHOOD</span>
                <div className="mini-network"><i /><i /><i /><i /><b /></div>
                <small>14 connected nodes</small>
              </div>
              <div className="gnn-arrow" />
              <div className="gnn-node ppr">
                <span>PPR ENRICHMENT</span>
                <div className="ppr-bars"><i /><i /><i /><i /></div>
                <small>proximity signal</small>
              </div>
              <div className="gnn-arrow" />
              <div className="gnn-layers">
                <span>GRAPHSAGE</span>
                <div><i>01</i><i>02</i><i>03</i></div>
                <small>inference layers</small>
              </div>
              <div className="gnn-arrow" />
              <div className="gnn-node final-score"><span>FUSION ENGINE</span><b>0.87</b><small>explainable risk</small></div>
            </div>
          </HudFrame>

          <div className="gnn-foot" style={{ marginTop: "20px" }}>
            <span><Radio size={12} /> INFERENCE ACTIVE · 184ms</span>
            <span>Graph risk 0.82 + traffic anomaly 0.91</span>
          </div>
        </section>

        {/* EDITORIAL BREAK */}
        <section className="editorial-break">
          <Reveal className="editorial-break-inner">
            <span>TWO SIGNALS.</span>
            <em><ScrambleText text="ONE EXPLAINABLE SCORE." /></em>
          </Reveal>
        </section>

        {/* 06 / SERVICES & CAPABILITIES - FULL-BLEED 4-COMPONENT MOTION MATRIX */}
        <section id="capabilities" className="services-matrix-section">
          {/* Section Header */}
          <div className="services-matrix-header">
            <div className="services-header-left">
              <span className="section-index">06 / SERVICES &amp; CAPABILITIES</span>
              <h2>From raw ledger noise<br />to <em><ScrambleText text="complete knowing." /></em></h2>
            </div>
            <div className="services-header-right">
              <p>
                Four interconnected intelligence vectors running concurrently. SentriX continuously fuses high-dimensional graph topology, P2P anomalous traffic flows, and sub-second mempool dynamics into one unified, explainable surveillance surface.
              </p>
              <div className="services-hud-badge">
                <span className="signal-dot" />
                <span>4 / 4 ENGINES ONLINE // REAL-TIME SYNC</span>
              </div>
            </div>
          </div>

          {/* 4-Component Full Space Grid (2x2 Matrix filling the space with rich motion) */}
          <div className="services-quad-grid">
            {capabilities.map((cap, idx) => (
              <HudFrame
                key={cap.number}
                className={`service-quad-card ${activeCapability === idx ? "is-selected-card" : ""}`}
                tag={`VECTOR // 0${idx + 1}`}
                coordinates={`SENTRIX-CORE::NODE_${idx + 1}`}
                withScanline={activeCapability === idx}
                onClick={() => {
                  playUiSound("confirm");
                  selectCapability(idx);
                }}
                role="button"
                tabIndex={0}
              >
                {/* Background Watermark Number */}
                <span className="quad-watermark" aria-hidden="true">{cap.number}</span>

                {/* Topbar inside Card */}
                <div className="quad-topbar">
                  <span className="quad-index-pill">MODULE // {cap.number}</span>
                  <div className="quad-live-tag">
                    <span className="quad-live-dot" />
                    <span>SYSTEM ONLINE</span>
                  </div>
                </div>

                {/* Motion Visualizer Stage */}
                <div className="quad-visual-stage">
                  {cap.kind === "pulse" && (
                    <div className="radar-dish" title="Live Mempool Radar">
                      <div className="radar-ring" />
                      <div className="radar-inner-ring" />
                      <div className="radar-sweep-arm" />
                      <div className="radar-pip" style={{ top: "30px", left: "86px" }} />
                      <div className="radar-pip" style={{ top: "88px", left: "44px", animationDelay: "0.6s" }} />
                      <div className="radar-pip" style={{ top: "52px", left: "102px", animationDelay: "1.1s" }} />
                      <div className="radar-feed-badge">
                        <span>FEED: <b>MEMPOOL // ACTIVE</b></span>
                      </div>
                    </div>
                  )}

                  {cap.kind === "rings" && (
                    <div className="gyro-container" title="Risk Intelligence Fused Gyroscope">
                      <div className="gyro-ring gyro-outer" />
                      <div className="gyro-ring gyro-mid" />
                      <div className="gyro-ring gyro-inner" />
                      <div className="gyro-center-score">
                        <strong>0.87</strong>
                        <small>HIGH ANOMALY</small>
                      </div>
                      <div className="gyro-weights">
                        <span>GNN: <b>0.82</b></span>
                        <span>PPR: <b>0.74</b></span>
                        <span>P2P: <b>0.91</b></span>
                      </div>
                    </div>
                  )}

                  {cap.kind === "nodes" && (
                    <div className="constellation-box" title="Relationship Mapping Network Topology">
                      <svg className="constellation-svg" viewBox="0 0 240 140" fill="none">
                        <defs>
                          <linearGradient id="constGrad" x1="0" y1="0" x2="1" y2="1">
                            <stop offset="0%" stopColor="#2dd4bf" stopOpacity="0.8" />
                            <stop offset="100%" stopColor="#8079d8" stopOpacity="0.4" />
                          </linearGradient>
                        </defs>
                        <path d="M40 70 L90 35 L150 45 L200 75 L150 105 L90 100 Z" stroke="rgba(45, 212, 191, 0.25)" strokeWidth="1" strokeDasharray="3 3" />
                        <path d="M90 35 L150 105 M150 45 L90 100 M90 70 L150 70" stroke="rgba(128, 121, 216, 0.25)" strokeWidth="1" />
                        <path d="M40 70 L120 70 L200 75" stroke="url(#constGrad)" strokeWidth="1.2" />
                        <circle cx="40" cy="70" r="4" fill="#2dd4bf" />
                        <circle cx="90" cy="35" r="3" fill="#8079d8" />
                        <circle cx="150" cy="45" r="3.5" fill="#2dd4bf" />
                        <circle cx="200" cy="75" r="4.5" fill="#d96a70" />
                        <circle cx="150" cy="105" r="3" fill="#2dd4bf" />
                        <circle cx="90" cy="100" r="3.5" fill="#8079d8" />
                        <circle cx="120" cy="70" r="5" fill="#2dd4bf" style={{ filter: "drop-shadow(0 0 8px #2dd4bf)" }} />
                      </svg>
                      <div className="constellation-tag">
                        <span>TOPOLOGY: <b>14 CLUSTERS IDENTIFIED</b></span>
                      </div>
                    </div>
                  )}

                  {cap.kind === "bars" && (
                    <div className="spectrum-box" title="Transaction Analytics UTXO Spectrum">
                      <div className="spectrum-bars">
                        {[38, 62, 45, 88, 74, 95, 52, 80, 68, 92, 48, 84, 60, 78, 55, 90].map((h, i) => (
                          <div
                            key={i}
                            className="spectrum-bar"
                            style={{
                              height: `${h}%`,
                              animationDelay: `${i * 0.07}s`,
                              animationDuration: `${1.4 + (i % 5) * 0.2}s`,
                            }}
                          />
                        ))}
                      </div>
                      <div className="spectrum-metrics">
                        <span>HISTORICAL VELOCITY: <b>2.84M TX/SEC</b></span>
                        <span>UTXO FLIGHT: <b>ACTIVE</b></span>
                      </div>
                    </div>
                  )}
                </div>

                {/* Content Details */}
                <div className="quad-content">
                  <div className="quad-stat-row">
                    <span className="quad-stat-val">{cap.stat}</span>
                    <span className="quad-stat-label">{cap.meta}</span>
                  </div>
                  <h3 className="quad-title"><ScrambleText text={cap.title} /></h3>
                  <p className="quad-desc">{cap.body}</p>
                  <ul className="quad-features">
                    {cap.highlights.map((h) => (
                      <li key={h}>
                        <span />
                        {h}
                      </li>
                    ))}
                  </ul>
                </div>

                {/* Footer Action */}
                <div
                  className="quad-footer"
                  onClick={(e) => {
                    e.stopPropagation();
                    playUiSound("confirm");
                    enterPlatform();
                  }}
                  role="button"
                  tabIndex={0}
                >
                  <span>LAUNCH MODULE IN PLATFORM</span>
                  <ArrowRight size={13} />
                </div>
              </HudFrame>
            ))}
          </div>
        </section>

        {/* ARCHITECTURE SECTION */}
        <section className="architecture-section">
          <Reveal className="architecture-inner">
            <div>
              <span className="section-index">07 / UNDER THE SURFACE</span>
              <h2>A second<br /><em>opinion.</em></h2>
            </div>
            <div className="architecture-copy">
              <p>Ledger patterns tell one story. Network behavior tells another. SentriX brings both into the same frame — a transparent fusion of graph intelligence and traffic correlation.</p>
              <div className="architecture-flow">
                <span>LEDGER</span><i />
                <span>GRAPH ML</span><i />
                <span>TRAFFIC</span><i />
                <span className="flow-result">RISK / 0.87</span>
              </div>
            </div>
          </Reveal>
        </section>

        {/* 08 / CONTACT & DISPATCH TERMINAL */}
        <section id="contact" className="contact-section">
          <Reveal className="contact-layout">
            {/* Left Column: Direct Intelligence Channels & Comms Telemetry */}
            <div className="contact-intel-column">
              <div className="contact-badge">
                <span className="signal-dot" />
                <span>SECURE DISPATCH // COMMS 08</span>
              </div>
              <h2 className="contact-headline">
                SEE THE<br />
                <em><ScrambleText text="SIGNAL." /></em><br />
                ACT ON IT.
              </h2>
              <p className="contact-lead">
                Deploy SentriX for high-stakes ledger surveillance, real-time cross-chain AML tracking, or graph anomaly modeling. Our investigative team and systems engineers respond directly.
              </p>

              {/* Direct Access Channels Grid */}
              <div className="contact-channels-grid">
                <div className="channel-card">
                  <span className="channel-label">INTELLIGENCE DESK</span>
                  <a href="mailto:intel@sentrix.network" className="channel-value">
                    intel@sentrix.network
                  </a>
                  <span className="channel-meta">DIRECT INQUIRIES &amp; POC</span>
                </div>
                <div className="channel-card">
                  <span className="channel-label">SECURITY PROTOCOL</span>
                  <span className="channel-value monospace">PGP: 4A9F 82C1 9D03 B4E7</span>
                  <span className="channel-meta">ENCRYPTED AT REST</span>
                </div>
                <div className="channel-card">
                  <span className="channel-label">RESPONSE SLA</span>
                  <span className="channel-value">&lt; 4 HOURS</span>
                  <span className="channel-meta">TIER 1 INCIDENT SUPPORT</span>
                </div>
                <div className="channel-card">
                  <span className="channel-label">GLOBAL HEADQUARTERS</span>
                  <span className="channel-value">ZÜRICH // SINGAPORE</span>
                  <span className="channel-meta">UTC+1 / UTC+8 TELEMETRY</span>
                </div>
              </div>

              {/* Live Signal Status Pill */}
              <div className="contact-status-bar">
                <div className="status-ping">
                  <span className="ping-dot" />
                  <span className="ping-ring" />
                </div>
                <span>NODE SURVEILLANCE DESK: <b>ACTIVE &amp; MONITORING</b></span>
              </div>
            </div>

            {/* Right Column: Encrypted Terminal Form inside HudFrame */}
            <div className="contact-form-column">
              <HudFrame
                className="contact-terminal-frame"
                tag="DISPATCH // SECURE TERMINAL"
                coordinates="SENTRIX::COMMS_PORT_08"
                withScanline={true}
              >
                <ContactForm />
              </HudFrame>
            </div>
          </Reveal>

          {/* Polished Alche-Style Cyberpunk Footer */}
          <footer className="site-footer-bar">
            <div className="footer-brand-lock">
              <span className="footer-x-emblem">X</span>
              <div>
                <div className="footer-brand-title">SENTRIX / TRANSACTION INTELLIGENCE</div>
                <div className="footer-brand-sub">HIGH-DIMENSIONAL GRAPH SURVEILLANCE</div>
              </div>
            </div>

            <div className="footer-links-row">
              <button type="button" onClick={() => enterPlatform()}>
                INTELLIGENCE DESK
              </button>
              <button type="button" onClick={() => scrollTo("capabilities")}>
                SERVICES
              </button>
              <button type="button" onClick={() => scrollTo("system")}>
                GNN PIPELINE
              </button>
              <a href="mailto:intel@sentrix.network">
                PGP COMMS
              </a>
            </div>

            <div className="footer-legal-copy">
              <span>© 2026 TEAM SENTRIX. ALL RIGHTS RESERVED.</span>
            </div>

            <SlotButton
              variant="outline"
              onClick={() => scrollTo("top")}
              icon={<ArrowUpRight size={12} />}
            >
              BACK TO TOP
            </SlotButton>
          </footer>
        </section>
      </main>
    </div>
  );
}
