import type Lenis from "lenis";

/** The smooth-scroll instance while the landing page is mounted (the phone menu pauses it). */
export const landingScroll: { lenis: Lenis | null } = { lenis: null };
