// High-tech Web Audio Synthesizer for SentriX (Zero external audio files required)

let audioCtx: AudioContext | null = null;
let ambientOscillator: OscillatorNode | null = null;
let ambientGain: GainNode | null = null;
let isSoundEnabled = false;

// Initialize from localStorage if present
if (typeof window !== "undefined") {
  try {
    isSoundEnabled = localStorage.getItem("sentrix-sound-enabled") === "true";
  } catch {
    isSoundEnabled = false;
  }
}

function getAudioContext(): AudioContext | null {
  if (typeof window === "undefined") return null;
  if (!audioCtx) {
    const AudioContextClass = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    if (AudioContextClass) {
      audioCtx = new AudioContextClass();
    }
  }
  if (audioCtx && audioCtx.state === "suspended") {
    audioCtx.resume();
  }
  return audioCtx;
}

export function isAudioEnabled(): boolean {
  return isSoundEnabled;
}

export function setAudioEnabled(enabled: boolean): void {
  isSoundEnabled = enabled;
  try {
    localStorage.setItem("sentrix-sound-enabled", enabled ? "true" : "false");
  } catch {}

  const ctx = getAudioContext();
  if (!ctx) return;

  if (enabled) {
    startAmbient();
    playUiSound("click");
  } else {
    stopAmbient();
  }
}

function startAmbient() {
  const ctx = getAudioContext();
  if (!ctx || ambientOscillator) return;

  try {
    ambientOscillator = ctx.createOscillator();
    ambientGain = ctx.createGain();

    // Very subtle warm cybernetic sub-bass drone (55Hz / A1)
    ambientOscillator.type = "sine";
    ambientOscillator.frequency.setValueAtTime(55, ctx.currentTime);

    // Filter to make it soft and pleasant
    const filter = ctx.createBiquadFilter();
    filter.type = "lowpass";
    filter.frequency.setValueAtTime(120, ctx.currentTime);

    ambientGain.gain.setValueAtTime(0.001, ctx.currentTime);
    ambientGain.gain.exponentialRampToValueAtTime(0.015, ctx.currentTime + 3);

    ambientOscillator.connect(filter);
    filter.connect(ambientGain);
    ambientGain.connect(ctx.destination);

    ambientOscillator.start();
  } catch {}
}

function stopAmbient() {
  if (ambientGain && audioCtx) {
    try {
      ambientGain.gain.exponentialRampToValueAtTime(0.0001, audioCtx.currentTime + 0.5);
      setTimeout(() => {
        ambientOscillator?.stop();
        ambientOscillator?.disconnect();
        ambientOscillator = null;
        ambientGain = null;
      }, 500);
    } catch {
      ambientOscillator = null;
      ambientGain = null;
    }
  }
}

export function playUiSound(type: "hover" | "click" | "radar" | "decode" | "confirm") {
  if (!isSoundEnabled) return;
  const ctx = getAudioContext();
  if (!ctx) return;

  try {
    const now = ctx.currentTime;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();

    if (type === "hover") {
      // Delicate futuristic cursor tick (1200Hz -> 1800Hz, 35ms duration)
      osc.type = "sine";
      osc.frequency.setValueAtTime(1400, now);
      osc.frequency.exponentialRampToValueAtTime(2200, now + 0.035);

      gain.gain.setValueAtTime(0.015, now);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.035);

      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(now);
      osc.stop(now + 0.035);
    } else if (type === "click") {
      // Deep mechanical cyber click (440Hz -> 220Hz, 80ms)
      osc.type = "triangle";
      osc.frequency.setValueAtTime(480, now);
      osc.frequency.exponentialRampToValueAtTime(180, now + 0.08);

      gain.gain.setValueAtTime(0.04, now);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.08);

      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(now);
      osc.stop(now + 0.08);
    } else if (type === "radar") {
      // Sonar pulse / intelligence ping
      osc.type = "sine";
      osc.frequency.setValueAtTime(880, now);
      osc.frequency.exponentialRampToValueAtTime(440, now + 0.25);

      gain.gain.setValueAtTime(0.03, now);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.25);

      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(now);
      osc.stop(now + 0.25);
    } else if (type === "decode") {
      // Rapid data chatter tick
      osc.type = "square";
      osc.frequency.setValueAtTime(800 + Math.random() * 400, now);
      gain.gain.setValueAtTime(0.008, now);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.02);

      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(now);
      osc.stop(now + 0.02);
    } else if (type === "confirm") {
      // Pleasant futuristic confirmation chime
      osc.type = "sine";
      osc.frequency.setValueAtTime(587.33, now);
      osc.frequency.setValueAtTime(880, now + 0.08);
      gain.gain.setValueAtTime(0.025, now);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.22);

      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(now);
      osc.stop(now + 0.22);
    }
  } catch {}
}
