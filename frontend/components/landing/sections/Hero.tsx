import { ROUND_PHOTO } from "../data";
import { MLink, Photo } from "../ui";

export function Hero() {
  return (
    <section id="hero" data-8b-section="hero" aria-labelledby="hero-title">
      <div className="hero__intro">
        <p className="m-text-5 hero__lead">
          We&apos;re ELEVORA, an AI-powered interview practice platform. Practise real interview scenarios, improve your answers, and build the confidence to perform when it matters.
        </p>
        <MLink href="#work" className="hero__link">
          Explore practice
        </MLink>
      </div>
      <h1 className="m-text-2 hero__title" id="hero-title" style={{ "--len": 5 } as React.CSSProperties}>
        <span className="hero__word">
          <span className="hero__mask">
            <span className="hero__glyphs">Hello</span>
          </span>
        </span>
        <span className="hero__period" aria-hidden="true">
          <span className="hero__stage">
            <span className="hero__orbit">
              <span className="hero__moon" />
            </span>
            <span className="hero__aperture">
              <Photo id={ROUND_PHOTO} className="hero__img" alt="" priority roundPlaceholder />
              <span className="hero__tint" />
            </span>
          </span>
        </span>
      </h1>
    </section>
  );
}
