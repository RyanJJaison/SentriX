import React, { createContext, useContext, useEffect, useMemo, useRef } from "react";

interface SmoothScrollContextType {
  scrollTo: (target: string | number, offset?: number) => void;
}

const SmoothScrollContext = createContext<SmoothScrollContextType>({
  scrollTo: () => {},
});

export const useSmoothScroll = () => useContext(SmoothScrollContext);

const prefersReducedMotion = () =>
  typeof window !== "undefined" &&
  window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/**
 * Single, centralized scroll system.
 *
 * Free scrolling (wheel / trackpad / touch / keyboard) is left 100% native — no
 * hijacking, no per-frame window.scrollTo, no competing smooth-scroll engine.
 *
 * `scrollTo()` is the ONLY programmatic smoothing path. It runs a single
 * requestAnimationFrame tween for explicit navigation jumps (nav links, section
 * indicator, "back to top") and immediately yields to the user: any real wheel /
 * touch / key input cancels the tween so it can never fight input.
 */
export function SmoothScrollProvider({ children }: { children: React.ReactNode }) {
  const rafRef = useRef<number | null>(null);

  const value = useMemo<SmoothScrollContextType>(() => {
    const cancel = () => {
      if (rafRef.current != null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
    };

    const resolveTop = (target: string | number, offset: number): number | null => {
      const maxTop = Math.max(
        0,
        document.documentElement.scrollHeight - window.innerHeight
      );
      if (typeof target === "number") {
        return Math.min(Math.max(0, target + offset), maxTop);
      }
      const el = document.getElementById(target.replace(/^#/, ""));
      if (!el) return null;
      const top = el.getBoundingClientRect().top + window.scrollY + offset;
      return Math.min(Math.max(0, top), maxTop);
    };

    const scrollTo = (target: string | number, offset = 0) => {
      const to = resolveTop(target, offset);
      if (to == null) return;

      cancel();

      if (prefersReducedMotion()) {
        window.scrollTo(0, to);
        return;
      }

      const from = window.scrollY;
      const distance = to - from;
      if (Math.abs(distance) < 2) {
        window.scrollTo(0, to);
        return;
      }

      // Duration scales with distance but stays snappy and bounded.
      const duration = Math.min(900, Math.max(320, Math.abs(distance) * 0.45));
      const start = performance.now();
      // easeInOutCubic
      const ease = (t: number) =>
        t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;

      const onUserInterrupt = () => cancel();
      window.addEventListener("wheel", onUserInterrupt, { passive: true });
      window.addEventListener("touchstart", onUserInterrupt, { passive: true });
      window.addEventListener("keydown", onUserInterrupt);

      const step = (now: number) => {
        const p = Math.min(1, (now - start) / duration);
        window.scrollTo(0, Math.round(from + distance * ease(p)));
        if (p < 1) {
          rafRef.current = requestAnimationFrame(step);
        } else {
          rafRef.current = null;
          window.removeEventListener("wheel", onUserInterrupt);
          window.removeEventListener("touchstart", onUserInterrupt);
          window.removeEventListener("keydown", onUserInterrupt);
        }
      };
      rafRef.current = requestAnimationFrame(step);
    };

    return { scrollTo };
  }, []);

  useEffect(() => {
    return () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
    };
  }, []);

  return (
    <SmoothScrollContext.Provider value={value}>
      {children}
    </SmoothScrollContext.Provider>
  );
}

export default SmoothScrollProvider;
