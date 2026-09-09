import React, { useCallback, useEffect, useRef, useState, createContext, useContext } from "react";
import { playUiSound } from "./SoundEngine";

/* ─── Shared transition context ───────────────────────────────── */
interface TransitionAPI {
  navigateTo: (path: string) => void;
  isActive: boolean;
}

const TransitionCtx = createContext<TransitionAPI>({ navigateTo: () => {}, isActive: false });
export const usePageTransition = () => useContext(TransitionCtx);

declare global {
  interface Window {
    __sentrixNavigate?: (path: string) => void;
  }
}

/* ─── Glyph set for scramble readout ─────────────────────────── */
const GLYPHS = "!<>-_\\/[]{}—=+*^?#_0123456789ABCDEF";
function scramble(target: string, progress: number): string {
  return target
    .split("")
    .map((ch, i) => {
      if (i / target.length < progress) return ch;
      return GLYPHS[Math.floor(Math.random() * GLYPHS.length)];
    })
    .join("");
}

/* ─── Route labels ────────────────────────────────────────────── */
const ROUTE_LABELS: Record<string, string> = {
  "/": "HOMEPAGE // SENTRIX HQ",
  "/platform": "PLATFORM // INFERENCE DESK",
  "/login": "AUTH // SECURE GATEWAY",
  "/404": "STATUS 404 // NODE NOT FOUND",
};

function getLabel(path: string): string {
  if (path.startsWith("/works/")) {
    const slug = path.replace("/works/", "");
    return `CASE STUDY // ${slug.toUpperCase()}`;
  }
  return ROUTE_LABELS[path] || `ROUTING // ${path.toUpperCase()}`;
}

interface Props {
  children: React.ReactNode;
  location: string;
  navigate: (to: string) => void;
}

export default function PageTransition({ children, location, navigate }: Props) {
  const [phase, setPhase] = useState<"idle" | "closing" | "loading" | "opening">("idle");
  const [destination, setDestination] = useState<string>(location);
  const [progress, setProgress] = useState(0);
  const [scrambled, setScrambled] = useState("");
  const [telemetry, setTelemetry] = useState("0x4F92");

  const progressIntervalRef = useRef<number | null>(null);
  const prevLocationRef = useRef<string>(location);
  const isNavigatingRef = useRef(false);

  /* Start the transition to a new path */
  const navigateTo = useCallback(
    (targetPath: string) => {
      if (targetPath === location) return;
      if (isNavigatingRef.current) return;
      isNavigatingRef.current = true;

      setDestination(targetPath);
      setProgress(0);
      setScrambled("");
      setPhase("closing");
      playUiSound("radar");

      // Phase 1: Shutters close (350ms)
      window.setTimeout(() => {
        setPhase("loading");

        // Swap the route while covered
        navigate(targetPath);
        window.scrollTo({ top: 0, behavior: "instant" });

        // Phase 2: Progress ticker and text scramble (500ms)
        let pct = 0;
        if (progressIntervalRef.current) clearInterval(progressIntervalRef.current);
        const label = getLabel(targetPath);

        progressIntervalRef.current = window.setInterval(() => {
          pct += 12;
          const clamped = Math.min(100, pct);
          setProgress(clamped);
          setScrambled(scramble(label, clamped / 100));
          setTelemetry("0x" + Math.floor(Math.random() * 0xffff).toString(16).toUpperCase().padStart(4, "0"));

          if (clamped >= 100) {
            if (progressIntervalRef.current) clearInterval(progressIntervalRef.current);

            // Phase 3: Unmask / shutters open
            window.setTimeout(() => {
              setPhase("opening");
              playUiSound("confirm");

              // Phase 4: Back to idle
              window.setTimeout(() => {
                setPhase("idle");
                isNavigatingRef.current = false;
              }, 600);
            }, 150);
          }
        }, 35);
      }, 350);
    },
    [location, navigate]
  );

  // Expose globally for any external component or vanilla handler
  useEffect(() => {
    window.__sentrixNavigate = navigateTo;
    return () => {
      delete window.__sentrixNavigate;
    };
  }, [navigateTo]);

  // Intercept any direct location changes (e.g. browser back/forward buttons)
  useEffect(() => {
    if (prevLocationRef.current !== location) {
      const oldLoc = prevLocationRef.current;
      prevLocationRef.current = location;
      if (!isNavigatingRef.current) {
        // Trigger brief loading flash for back/forward
        setDestination(location);
        setPhase("closing");
        window.setTimeout(() => {
          setPhase("opening");
          window.setTimeout(() => setPhase("idle"), 500);
        }, 400);
      }
    }
  }, [location]);

  // Intercept click on internal links
  useEffect(() => {
    const handleLinkClick = (event: MouseEvent) => {
      const target = (event.target as HTMLElement).closest("a");
      if (!target) return;
      const href = target.getAttribute("href");
      if (href && href.startsWith("/") && !href.startsWith("//") && !target.getAttribute("target")) {
        event.preventDefault();
        navigateTo(href);
      }
    };
    document.addEventListener("click", handleLinkClick, { capture: true });
    return () => document.removeEventListener("click", handleLinkClick, { capture: true });
  }, [navigateTo]);

  const isActive = phase !== "idle";

  return (
    <TransitionCtx.Provider value={{ navigateTo, isActive }}>
      {/* ── Content Stage ── */}
      <div className={`ptx-content-stage ${isActive ? "is-transitioning" : ""}`}>
        {children}
      </div>

      {/* ── Alche-Style Fullscreen Cinematic Transition Overlay ── */}
      {isActive && (
        <div
          className={`sentrix-page-transition-overlay phase-${phase}`}
          aria-live="polite"
          aria-busy="true"
        >
          {/* Dual Split Mechanical Shutters */}
          <div className="ptx-shutter ptx-shutter-left" />
          <div className="ptx-shutter ptx-shutter-right" />

          {/* HUD Reticle Corners */}
          <div className="ptx-hud-corner ptx-corner-tl">+ [SYS.NODE // {telemetry}]</div>
          <div className="ptx-hud-corner ptx-corner-tr">[RELAY // 12ms] +</div>
          <div className="ptx-hud-corner ptx-corner-bl">+ SENTRIX TRANSACTION PROTOCOL</div>
          <div className="ptx-hud-corner ptx-corner-br">GNN ENGINE V2.4 +</div>

          {/* Laser Scanning Sweep */}
          <div className="ptx-scanning-laser" />

          {/* Centerpiece Vector Emblem & Scramble Readout */}
          <div className="ptx-centerpiece">
            <div className="ptx-emblem-box">
              <svg className="ptx-svg" viewBox="0 0 200 200" aria-hidden="true">
                <defs>
                  <linearGradient id="ptxGrad" x1="0" y1="0" x2="1" y2="1">
                    <stop offset="0%" stopColor="#2dd4bf" />
                    <stop offset="50%" stopColor="#a7f3e0" />
                    <stop offset="100%" stopColor="#7f77dd" />
                  </linearGradient>
                </defs>
                <circle cx="100" cy="100" r="88" className="intro-ring" />
                <circle cx="100" cy="100" r="70" className="intro-dashed-ring" />
                <path d="M40 40 L160 160" className="intro-x-stroke stroke-1" />
                <path d="M160 40 L40 160" className="intro-x-stroke stroke-2" />
                <circle cx="100" cy="100" r="6" className="intro-core-dot" />
              </svg>
            </div>

            <div className="ptx-readout-wrap">
              <span className="ptx-readout-kicker">COMMENCING ROUTE SHIFT</span>
              <h2 className="ptx-readout-title">{scrambled || getLabel(destination)}</h2>
            </div>

            <div className="ptx-progress-container">
              <div className="ptx-bar-rail">
                <div className="ptx-bar-lead" style={{ width: `${progress}%` }} />
              </div>
              <div className="ptx-progress-metrics">
                <span>BUFFERING QUANTUM STATE</span>
                <span className="ptx-pct-num">{progress}%</span>
              </div>
            </div>
          </div>
        </div>
      )}
    </TransitionCtx.Provider>
  );
}
