"use client";

import { SECTION_LINKS, ROUND_PHOTO } from "../data";
import { Dot, MButton, MLink2, Photo } from "../ui";
import { useLandingLinks } from "../useLandingLinks";

/** Template footer: "Bye" with the round photo as its full stop, link columns and a closing call to action. */
export function LandingFooter() {
  const { signedIn, primary, account } = useLandingLinks();
  return (
    <footer id="footer" data-8b-section="footer">
      <p className="m-text-2 footer__bye" style={{ "--len": 3 } as React.CSSProperties}>
        <span className="footer__word">Bye</span>
        <span className="footer__period" aria-hidden="true">
          <span className="footer__aperture">
            <Photo id={ROUND_PHOTO} className="footer__img" alt="" loading="lazy" roundPlaceholder />
            <span className="footer__tint" />
          </span>
        </span>
      </p>
      <div className="footer__grid">
        <nav className="footer__col" aria-label="Footer">
          <p className="m-text-6 footer__label">Explore ELEVORA</p>
          {SECTION_LINKS.map((link) => (
            <MLink2 key={link.href} href={link.href}>
              {link.label}
            </MLink2>
          ))}
        </nav>
        <div className="footer__col">
          <p className="m-text-6 footer__label">Get Started</p>
          {!signedIn && <MLink2 href="/signup">Create your account</MLink2>}
          <MLink2 href={account.href}>{account.label}</MLink2>
          <MLink2 href="/interviews/new">New interview</MLink2>
        </div>
        <div className="footer__col">
          <p className="m-text-6 footer__label">Your Workspace</p>
          <MLink2 href="/interview-profiles">Interview profiles</MLink2>
          <MLink2 href="/history">History</MLink2>
          <MLink2 href="/settings">Settings</MLink2>
        </div>
        <div className="footer__news">
          <p className="m-text-7">
            Ready when you are
            <Dot />
          </p>
          <p className="m-text-6 footer__note">Practical interview preparation, feedback and progress tracking in one workspace.</p>
          <div>
            <MButton href={primary.href}>{primary.label}</MButton>
          </div>
        </div>
      </div>
      <div className="footer__legal m-text-6">
        <p>
          © {new Date().getFullYear()} ELEVORA · Design:{" "}
          <a href="https://8b.com/" style={{ color: "inherit" }} target="_blank" rel="noopener noreferrer">
            8B
          </a>
        </p>
        <p>AI Interview Practice Platform</p>
      </div>
    </footer>
  );
}
