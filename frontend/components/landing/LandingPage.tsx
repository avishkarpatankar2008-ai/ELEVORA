import { LandingNav } from "./LandingNav";
import { LandingRoot } from "./LandingRoot";
import { Again } from "./sections/Again";
import { Capabilities } from "./sections/Capabilities";
import { Faq } from "./sections/Faq";
import { Hero } from "./sections/Hero";
import { Journal } from "./sections/Journal";
import { LandingFooter } from "./sections/LandingFooter";
import { Method } from "./sections/Method";
import { StartCta } from "./sections/StartCta";
import { Statement } from "./sections/Statement";
import { Studio } from "./sections/Studio";
import { Work } from "./sections/Work";
import "./landing.css";

/**
 * Public landing page for "/" — the Design Studio template, rebuilt as React
 * sections. Section order matters: hero → statement and work → again animate
 * across their shared border (see motion.ts).
 */
export function LandingPage() {
  return (
    <LandingRoot>
      <LandingNav />
      <div id="main" className="onda__main">
        <Hero />
        <Statement />
        <Work />
        <Again />
        <Capabilities />
        <Method />
        <Studio />
        <Journal />
        <Faq />
        <StartCta />
      </div>
      <LandingFooter />
    </LandingRoot>
  );
}
