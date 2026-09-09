import React from "react";

interface HudFrameProps {
  children: React.ReactNode;
  className?: string;
  tag?: string;
  coordinates?: string;
  withScanline?: boolean;
  onClick?: (e: React.MouseEvent<HTMLDivElement>) => void;
  role?: string;
  tabIndex?: number;
}

export function HudFrame({
  children,
  className = "",
  tag,
  coordinates,
  withScanline = false,
  onClick,
  role,
  tabIndex,
}: HudFrameProps) {
  return (
    <div
      className={`hud-frame ${className}`}
      onClick={onClick}
      role={role}
      tabIndex={tabIndex}
    >
      {/* 4 Corner Crosshairs (+) like Alche Stellla cross */}
      <div className="hud-corner corner-tl" aria-hidden="true">
        <span className="cross-h" />
        <span className="cross-v" />
      </div>
      <div className="hud-corner corner-tr" aria-hidden="true">
        <span className="cross-h" />
        <span className="cross-v" />
      </div>
      <div className="hud-corner corner-bl" aria-hidden="true">
        <span className="cross-h" />
        <span className="cross-v" />
      </div>
      <div className="hud-corner corner-br" aria-hidden="true">
        <span className="cross-h" />
        <span className="cross-v" />
      </div>

      {/* Meta tags at corners if provided */}
      {tag && (
        <div className="hud-tag" aria-hidden="true">
          <span className="hud-tag-dot" />
          <span>{tag}</span>
        </div>
      )}
      {coordinates && (
        <div className="hud-coords" aria-hidden="true">
          {coordinates}
        </div>
      )}

      {/* Optional scanning laser line */}
      {withScanline && <div className="hud-laser-scan" aria-hidden="true" />}

      {/* Child Content */}
      <div className="hud-frame-content">{children}</div>
    </div>
  );
}

export default HudFrame;
