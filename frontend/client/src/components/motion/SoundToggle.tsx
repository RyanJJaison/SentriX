import React, { useEffect, useState } from "react";
import { isAudioEnabled, setAudioEnabled } from "./SoundEngine";

export function SoundToggle({ className = "" }: { className?: string }) {
  const [enabled, setEnabled] = useState(false);

  useEffect(() => {
    setEnabled(isAudioEnabled());
  }, []);

  const toggle = () => {
    const next = !enabled;
    setEnabled(next);
    setAudioEnabled(next);
  };

  return (
    <button
      className={`sound-toggle-button ${enabled ? "is-active" : "is-muted"} ${className}`}
      onClick={toggle}
      type="button"
      title={enabled ? "Mute audio atmosphere" : "Enable audio atmosphere"}
      aria-label="Toggle audio atmosphere"
    >
      <div className="sound-toggle-bars" aria-hidden="true">
        <div className="sound-toggle-bar bar-1" />
        <div className="sound-toggle-bar bar-2" />
        <div className="sound-toggle-bar bar-3" />
      </div>
      <span className="sound-toggle-label">{enabled ? "SOUND ON" : "SOUND OFF"}</span>
    </button>
  );
}

export default SoundToggle;
