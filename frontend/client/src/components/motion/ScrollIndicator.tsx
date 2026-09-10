import React, { useEffect, useState } from "react";
import { useSmoothScroll } from "./SmoothScroll";
import { playUiSound } from "./SoundEngine";

interface SectionItem {
  id: string;
  label: string;
  subsections?: number;
}

const SECTIONS: SectionItem[] = [
  { id: "top", label: "TOP", subsections: 2 },
  { id: "system", label: "PREMISE", subsections: 2 },
  { id: "intelligence", label: "WORKS", subsections: 3 },
  { id: "signals", label: "SIGNALS", subsections: 2 },
  { id: "gnn", label: "MODEL", subsections: 2 },
  { id: "capabilities", label: "SERVICES", subsections: 4 },
  { id: "contact", label: "CONTACT", subsections: 1 },
];

// Every distinct progress value at which a subsection tick flips filled. The
// indicator only needs to re-render when one of these boundaries is crossed —
// ~16 times for a full-page scroll instead of once per scroll frame.
const TICK_THRESHOLDS = Array.from(
  new Set(
    SECTIONS.flatMap((s, idx) =>
      Array.from(
        { length: s.subsections || 1 },
        (_, k) => (idx + k / (s.subsections || 1)) / SECTIONS.length
      )
    )
  )
).sort((a, b) => a - b);

const bucketFor = (progress: number) =>
  TICK_THRESHOLDS.reduce((n, t) => (progress > t ? n + 1 : n), 0);

export function ScrollIndicator({ className = "" }: { className?: string }) {
  const [activeSection, setActiveSection] = useState<string>("top");
  // Coarse scroll progress (0..1). Committed only when the scroll position
  // crosses a tick boundary, so scrolling does not re-render on every frame.
  const [scrollProgress, setScrollProgress] = useState(0);
  const { scrollTo } = useSmoothScroll();

  // ── Active section: one IntersectionObserver, no scroll handler, no reflow ──
  useEffect(() => {
    const els = SECTIONS.map((s) => document.getElementById(s.id)).filter(
      (el): el is HTMLElement => !!el
    );
    if (!els.length) return;

    // A thin horizontal "reading line" ~40% down the viewport. Whichever section
    // is crossing that line is the active one — the last such in document order.
    const crossing = new Set<string>();
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting) crossing.add(e.target.id);
          else crossing.delete(e.target.id);
        }
        let current = SECTIONS[0].id;
        for (const s of SECTIONS) {
          if (crossing.has(s.id)) current = s.id;
        }
        setActiveSection((prev) => (prev === current ? prev : current));
      },
      { threshold: 0, rootMargin: "-40% 0px -58% 0px" }
    );
    els.forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, []);

  // ── Scroll progress: rAF-throttled, cached doc height, tick-boundary gate ──
  useEffect(() => {
    let docHeight = document.documentElement.scrollHeight - window.innerHeight;
    let ticking = false;
    let lastBucket = -1;

    const compute = () => {
      ticking = false;
      const progress = docHeight > 0 ? window.scrollY / docHeight : 0;
      const bucket = bucketFor(progress);
      if (bucket !== lastBucket) {
        lastBucket = bucket;
        setScrollProgress(progress);
      }
    };
    const onScroll = () => {
      if (!ticking) {
        ticking = true;
        requestAnimationFrame(compute);
      }
    };
    const onResize = () => {
      docHeight = document.documentElement.scrollHeight - window.innerHeight;
      onScroll();
    };

    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onResize);
    compute();
    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onResize);
    };
  }, []);

  const handleClick = (id: string) => {
    playUiSound("click");
    scrollTo(id);
  };

  return (
    <nav
      className={`hud-scroll-indicator ${className}`}
      aria-label="Section navigation indicator"
    >
      <div className="hud-indicator-track">
        {SECTIONS.map((section, idx) => {
          const isActive = activeSection === section.id;
          return (
            <div
              key={section.id}
              className={`hud-indicator-item ${isActive ? "is-active" : ""}`}
              onClick={() => handleClick(section.id)}
            >
              <div className="hud-indicator-main">
                <span className="hud-indicator-line" />
                <span className="hud-indicator-label">{section.label}</span>
              </div>
              <div className="hud-subsection-list">
                {Array.from({ length: section.subsections || 1 }).map((_, subIdx) => (
                  <div
                    key={subIdx}
                    className={`hud-subsection-tick ${
                      isActive && scrollProgress > (idx + subIdx / (section.subsections || 1)) / SECTIONS.length
                        ? "is-filled"
                        : ""
                    }`}
                  />
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </nav>
  );
}

export default ScrollIndicator;
