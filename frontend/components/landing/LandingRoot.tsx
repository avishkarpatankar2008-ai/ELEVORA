"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { initLandingMotion } from "./motion";

/** Scope element for all landing CSS (`.onda`) and the owner of the GSAP / Lenis lifecycle. */
export function LandingRoot({ children }: { children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current) return;
    return initLandingMotion(ref.current);
  }, []);

  return (
    <div ref={ref} className="onda">
      <div className="m-text">{children}</div>
    </div>
  );
}
