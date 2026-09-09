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

export function ScrollIndicator({ className = "" }: { className?: string }) {
  const [activeSection, setActiveSection] = useState<string>("top");
  const [scrollProgress, setScrollProgress] = useState(0);
  const { scrollTo } = useSmoothScroll();

  useEffect(() => {
    const handleScroll = () => {
      const docHeight = document.documentElement.scrollHeight - window.innerHeight;
      const progress = docHeight > 0 ? window.scrollY / docHeight : 0;
      setScrollProgress(progress);

      // Determine active section
      const scrollPos = window.scrollY + window.innerHeight * 0.35;
      for (let i = SECTIONS.length - 1; i >= 0; i--) {
        const el = document.getElementById(SECTIONS[i].id);
        if (el && el.offsetTop <= scrollPos) {
          setActiveSection(SECTIONS[i].id);
          break;
        }
      }
    };

    window.addEventListener("scroll", handleScroll, { passive: true });
    handleScroll();

    return () => window.removeEventListener("scroll", handleScroll);
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
