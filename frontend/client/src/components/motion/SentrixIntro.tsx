import React, { useEffect, useState } from "react";
import { setAudioEnabled, playUiSound } from "./SoundEngine";

interface SentrixIntroProps {
  onComplete?: () => void;
}

export function SentrixIntro({ onComplete }: SentrixIntroProps) {
  const [progress, setProgress] = useState(0);
  const [stage, setStage] = useState<"loading" | "prompt" | "exiting" | "hidden">("loading");
  const [statusText, setStatusText] = useState("INITIALIZING SENTRIX CORE");

  useEffect(() => {
    // Check if already visited in this session
    const hasSeen = sessionStorage.getItem("sentrix-intro-viewed");
    if (hasSeen === "true") {
      setStage("hidden");
      if (onComplete) onComplete();
      return;
    }

    // Step progression
    const interval = window.setInterval(() => {
      setProgress((prev) => {
        if (prev >= 100) {
          clearInterval(interval);
          setStage("prompt");
          return 100;
        }
        if (prev === 25) setStatusText("CALIBRATING GRAPH ML REASONING");
        if (prev === 60) setStatusText("SYNCING MEMPOOL STREAM #912,481");
        if (prev === 88) setStatusText("INTELLIGENCE PIPELINE ONLINE");
        return prev + 4;
      });
    }, 45);

    return () => clearInterval(interval);
  }, [onComplete]);

  const handleFinish = (enableAudio: boolean) => {
    if (enableAudio) {
      setAudioEnabled(true);
      playUiSound("radar");
    } else {
      setAudioEnabled(false);
    }

    try {
      sessionStorage.setItem("sentrix-intro-viewed", "true");
    } catch {}

    setStage("exiting");
    setTimeout(() => {
      setStage("hidden");
      if (onComplete) onComplete();
    }, 700);
  };

  if (stage === "hidden") return null;

  return (
    <div
      className={`sentrix-intro-overlay ${stage === "exiting" ? "is-exiting" : ""}`}
      role="dialog"
      aria-modal="true"
    >
      <div className="intro-shutter shutter-left" />
      <div className="intro-shutter shutter-right" />

      <div className="intro-center">
        {/* Animated SentriX Vector Emblem */}
        <div className="intro-emblem-box">
          <svg className="intro-svg" viewBox="0 0 200 200" aria-hidden="true">
            <defs>
              <linearGradient id="introGrad" x1="0" y1="0" x2="1" y2="1">
                <stop offset="0%" stopColor="#2dd4bf" />
                <stop offset="50%" stopColor="#a7f3e0" />
                <stop offset="100%" stopColor="#7f77dd" />
              </linearGradient>
            </defs>
            <circle cx="100" cy="100" r="88" className="intro-ring" />
            <circle cx="100" cy="100" r="70" className="intro-dashed-ring" />
            {/* The SentriX X mark */}
            <path d="M40 40 L160 160" className="intro-x-stroke stroke-1" />
            <path d="M160 40 L40 160" className="intro-x-stroke stroke-2" />
            {/* Center core pulse */}
            <circle cx="100" cy="100" r="6" className="intro-core-dot" />
          </svg>
        </div>

        <div className="intro-brand">
          <span className="intro-kicker">TRANSACTION INTELLIGENCE</span>
          <h1 className="intro-title">SENTRIX</h1>
        </div>

        {stage === "loading" && (
          <div className="intro-loading-state">
            <div className="intro-bar-track">
              <div className="intro-bar-fill" style={{ width: `${progress}%` }} />
            </div>
            <div className="intro-meta">
              <span className="intro-status-text">{statusText}</span>
              <span className="intro-percent">{progress}%</span>
            </div>
          </div>
        )}

        {stage === "prompt" && (
          <div className="intro-sound-prompt">
            <p className="intro-sound-copy">
              SentriX features real-time audio telemetry & kinetic soundscapes.
            </p>
            <div className="intro-actions">
              <button
                type="button"
                className="intro-btn primary"
                onClick={() => handleFinish(true)}
              >
                ENTER WITH SOUND
              </button>
              <button
                type="button"
                className="intro-btn secondary"
                onClick={() => handleFinish(false)}
              >
                ENTER SILENTLY
              </button>
            </div>
          </div>
        )}
      </div>

      <div className="intro-footer">
        <span>EST. 2026 // HIGH-DIMENSIONAL GRAPH INTELLIGENCE</span>
        <span>SYS.V2.4</span>
      </div>
    </div>
  );
}

export default SentrixIntro;
