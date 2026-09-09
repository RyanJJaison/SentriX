import React, { createContext, useContext, useEffect, useRef } from "react";

interface SmoothScrollContextType {
  scrollTo: (target: string | number, offset?: number) => void;
}

const SmoothScrollContext = createContext<SmoothScrollContextType>({
  scrollTo: () => {},
});

export const useSmoothScroll = () => useContext(SmoothScrollContext);

export function SmoothScrollProvider({ children }: { children: React.ReactNode }) {
  const isScrolling = useRef(false);

  const scrollTo = (target: string | number, offset = 0) => {
    if (typeof target === "number") {
      window.scrollTo({ top: target + offset, behavior: "smooth" });
      return;
    }

    const cleanId = target.replace(/^#/, "");
    const el = document.getElementById(cleanId);
    if (el) {
      const top = el.getBoundingClientRect().top + window.scrollY + offset;
      window.scrollTo({ top, behavior: "smooth" });
    }
  };

  useEffect(() => {
    // Check for reduced motion preference
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      return;
    }

    // Only apply kinetic inertia wheel damping on devices with mouse wheel (not touch)
    let currentY = window.scrollY;
    let targetY = window.scrollY;
    let animationId: number | null = null;
    const friction = 0.085; // Alche-like fluid gliding friction

    const onWheel = (e: WheelEvent) => {
      // Don't intercept if scrolling inside an overflow element (like a modal or table)
      let target = e.target as HTMLElement | null;
      while (target && target !== document.body) {
        const overflowY = window.getComputedStyle(target).overflowY;
        if ((overflowY === "auto" || overflowY === "scroll") && target.scrollHeight > target.clientHeight) {
          return; // Let native container scroll
        }
        target = target.parentElement;
      }

      // Delta mode normalization
      let delta = e.deltaY;
      if (e.deltaMode === 1) delta *= 40; // lines
      if (e.deltaMode === 2) delta *= 800; // pages

      // Clamp delta to prevent erratic jumps
      const maxDelta = 140;
      const clampedDelta = Math.sign(delta) * Math.min(Math.abs(delta), maxDelta);

      targetY = Math.max(0, Math.min(document.documentElement.scrollHeight - window.innerHeight, targetY + clampedDelta));

      if (!isScrolling.current) {
        isScrolling.current = true;
        animateScroll();
      }
    };

    const animateScroll = () => {
      currentY += (targetY - currentY) * friction;

      if (Math.abs(targetY - currentY) > 0.5) {
        window.scrollTo(0, currentY);
        animationId = requestAnimationFrame(animateScroll);
      } else {
        window.scrollTo(0, targetY);
        currentY = targetY;
        isScrolling.current = false;
        if (animationId) cancelAnimationFrame(animationId);
      }
    };

    const onNativeScroll = () => {
      if (!isScrolling.current) {
        currentY = window.scrollY;
        targetY = window.scrollY;
      }
    };

    window.addEventListener("wheel", onWheel, { passive: true });
    window.addEventListener("scroll", onNativeScroll, { passive: true });

    return () => {
      window.removeEventListener("wheel", onWheel);
      window.removeEventListener("scroll", onNativeScroll);
      if (animationId) cancelAnimationFrame(animationId);
    };
  }, []);

  return (
    <SmoothScrollContext.Provider value={{ scrollTo }}>
      {children}
    </SmoothScrollContext.Provider>
  );
}

export default SmoothScrollProvider;
