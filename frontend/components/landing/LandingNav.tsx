"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from "react";
import { SECTION_LINKS } from "./data";
import { landingScroll } from "./scroll";
import { Dot, MButton } from "./ui";
import { useLandingLinks } from "./useLandingLinks";

/** Fixed top bar (wordmark, section links, call to action) plus the phone menu overlay. */
export function LandingNav() {
  const { primary, account } = useLandingLinks();
  const [open, setOpen] = useState(false);
  const toggleRef = useRef<HTMLButtonElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const wasOpen = useRef(false);
  const restoreFocus = useRef(true);

  const close = useCallback((returnFocus: boolean) => {
    restoreFocus.current = returnFocus;
    setOpen(false);
  }, []);

  // Pause smooth scroll (or lock native scroll) while the overlay is open; focus management on open/close.
  useEffect(() => {
    if (open) {
      wasOpen.current = true;
      const lenis = landingScroll.lenis;
      const root = document.documentElement;
      const previous = root.style.overflow;
      if (lenis) lenis.stop();
      else root.style.overflow = "hidden";
      closeRef.current?.focus();
      return () => {
        if (lenis) lenis.start();
        else root.style.overflow = previous;
      };
    }
    if (wasOpen.current && restoreFocus.current) toggleRef.current?.focus();
    wasOpen.current = false;
  }, [open]);

  function onMenuKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") close(true);
    if (event.key !== "Tab" || !menuRef.current) return;
    const items = Array.from(menuRef.current.querySelectorAll<HTMLElement>("a, button"));
    const first = items[0];
    const last = items[items.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  return (
    <header id="navigation" className="nav" data-8b-section="navigation">
      <a className="nav__brand" href="#hero" aria-label="ELEVORA, back to the top">
        ELEVORA
        <Dot />
      </a>
      <nav className="nav__links" aria-label="Main">
        <ul>
          {SECTION_LINKS.map((link) => (
            <li key={link.href}>
              <a className="m-link-2" href={link.href}>
                {link.label}
              </a>
            </li>
          ))}
          <li>
            <Link className="m-link-2" href={account.href}>
              {account.label}
            </Link>
          </li>
        </ul>
      </nav>
      <MButton href={primary.href} className="nav__cta">
        {primary.label}
      </MButton>
      <button ref={toggleRef} className="m-btn-2 nav__menu" type="button" aria-expanded={open} aria-controls="menu" onClick={() => setOpen(true)}>
        <span className="m-btn__label">Menu</span>
      </button>
      <div ref={menuRef} className="menu" id="menu" role="dialog" aria-modal="true" aria-label="Menu" data-lenis-prevent hidden={!open} onKeyDown={onMenuKeyDown}>
        <div className="menu__top">
          <button ref={closeRef} className="m-icon menu__close" type="button" aria-label="Close the menu" onClick={() => close(true)}>
            <svg viewBox="0 0 16 16" aria-hidden="true">
              <path d="M3 3l10 10M13 3 3 13" />
            </svg>
          </button>
        </div>
        <ul className="menu__list">
          {SECTION_LINKS.map((link) => (
            <li key={link.href}>
              <a href={link.href} onClick={() => close(false)}>
                {link.label}
                <Dot />
              </a>
            </li>
          ))}
          <li>
            <a href="#contact" onClick={() => close(false)}>
              Get Started
              <Dot />
            </a>
          </li>
          <li>
            <Link href={account.href} onClick={() => close(false)}>
              {account.label}
              <Dot />
            </Link>
          </li>
        </ul>
        <p className="m-text menu__foot">ELEVORA · AI-powered interview practice</p>
      </div>
    </header>
  );
}
