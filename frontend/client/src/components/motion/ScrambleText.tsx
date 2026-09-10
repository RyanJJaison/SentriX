import React, { useEffect, useRef, useState } from "react";
import { playUiSound } from "./SoundEngine";

interface ScrambleTextProps {
  text: string;
  scrambleOnHover?: boolean;
  scrambleOnMount?: boolean;
  className?: string;
  as?: "span" | "div" | "h2" | "h3" | "strong" | "b" | "p";
  speed?: number;
}

const GLYPHS = "01アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワヲンABCDEFXYZ0123456789_//--#%*+";

// Suppress hover-triggered scrambles while the page is actively scrolling — the
// pointer sweeping across headings mid-scroll would otherwise kick off bursts of
// interval-driven re-renders and fight the scroll for the main thread.
let lastScrollAt = 0;
if (typeof window !== "undefined") {
  window.addEventListener(
    "scroll",
    () => {
      lastScrollAt = performance.now();
    },
    { passive: true }
  );
}

export function ScrambleText({
  text,
  scrambleOnHover = true,
  scrambleOnMount = false,
  className = "",
  as: Component = "span",
  speed = 28,
}: ScrambleTextProps) {
  const [displayText, setDisplayText] = useState(text);
  const isScramblingRef = useRef(false);
  const timerRef = useRef<number | null>(null);

  const startScramble = () => {
    if (isScramblingRef.current) return;
    // Ignore scrambles provoked by the pointer passing over text during a scroll.
    if (performance.now() - lastScrollAt < 250) return;
    isScramblingRef.current = true;

    let iteration = 0;
    const maxIterations = text.length;

    if (timerRef.current) clearInterval(timerRef.current);

    // Play initial sound
    playUiSound("decode");

    timerRef.current = window.setInterval(() => {
      setDisplayText(
        text
          .split("")
          .map((char, index) => {
            if (char === " ") return " ";
            if (index < iteration) {
              return text[index];
            }
            return GLYPHS[Math.floor(Math.random() * GLYPHS.length)];
          })
          .join("")
      );

      iteration += 1 / 2;

      if (iteration >= maxIterations) {
        setDisplayText(text);
        isScramblingRef.current = false;
        if (timerRef.current) clearInterval(timerRef.current);
      }
    }, speed);
  };

  useEffect(() => {
    setDisplayText(text);
    if (scrambleOnMount) {
      startScramble();
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [text, scrambleOnMount]);

  return (
    <Component
      className={`scramble-text ${className}`}
      onMouseEnter={scrambleOnHover ? startScramble : undefined}
      aria-label={text}
    >
      {displayText}
    </Component>
  );
}

export default ScrambleText;
