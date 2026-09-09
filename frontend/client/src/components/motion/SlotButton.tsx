import React from "react";
import { playUiSound } from "./SoundEngine";

interface SlotButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  children: React.ReactNode;
  icon?: React.ReactNode;
  variant?: "primary" | "outline" | "nav" | "ghost";
  className?: string;
  onClick?: (e: React.MouseEvent<HTMLButtonElement>) => void;
  href?: string;
  target?: string;
  rel?: string;
}

export function SlotButton({
  children,
  icon,
  variant = "primary",
  className = "",
  onClick,
  href,
  target,
  rel,
  ...rest
}: SlotButtonProps) {
  const handleMouseEnter = () => {
    playUiSound("hover");
  };

  const handleClick = (e: React.MouseEvent<HTMLButtonElement | HTMLAnchorElement>) => {
    playUiSound("click");
    if (onClick) {
      onClick(e as React.MouseEvent<HTMLButtonElement>);
    }
  };

  const content = (
    <>
      <span className="slot-button-track">
        <span className="slot-button-text default-text">{children}</span>
        <span className="slot-button-text hover-text" aria-hidden="true">{children}</span>
      </span>
      {icon && <span className="slot-button-icon">{icon}</span>}
    </>
  );

  const combinedClass = `slot-button variant-${variant} ${className}`;

  if (href) {
    return (
      <a
        href={href}
        target={target}
        rel={rel}
        className={combinedClass}
        onMouseEnter={handleMouseEnter}
        onClick={handleClick}
      >
        {content}
      </a>
    );
  }

  return (
    <button
      className={combinedClass}
      onMouseEnter={handleMouseEnter}
      onClick={handleClick}
      {...rest}
    >
      {content}
    </button>
  );
}

export default SlotButton;
