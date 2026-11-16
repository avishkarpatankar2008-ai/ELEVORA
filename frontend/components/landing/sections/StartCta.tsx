"use client";

import Link from "next/link";
import { PrimaryButton, AccountButton } from "../AuthLinks";
import { Dot } from "../ui";
import { useLandingLinks } from "../useLandingLinks";

/**
 * The template's violet "Let's talk" contact block. ELEVORA has no contact
 * form endpoint, so the block leads into the real signup / interview flow instead.
 */
export function StartCta() {
  const { signedIn, primary, history } = useLandingLinks();
  return (
    <section id="contact" data-8b-section="contact" aria-labelledby="contact-title">
      <h2 className="m-text-3 contact__title" id="contact-title" style={{ "--len": 11 } as React.CSSProperties}>
        <span className="contact__voice">Let&apos;s start</span>
        <Dot />
      </h2>
      <div className="contact__grid">
        <div className="contact__info">
          <p className="m-text-5 contact__lead">
            Start practising with ELEVORA. Prepare for your next interview with focused practice and structured feedback.
          </p>
          <Link className="contact__mail" href={primary.href}>
            <span>{signedIn ? "Start an interview" : "Create your account"}</span>
          </Link>
          <dl className="contact__places">
            <div>
              <dt className="m-text-7">Your Next Interview</dt>
              <dd className="m-text">
                Prepare with purpose
                <br />
                Practise at your own pace
              </dd>
              <dd className="m-text">
                <Link href={primary.href}>Build interview confidence</Link>
              </dd>
            </div>
            <div>
              <dt className="m-text-7">Your Progress</dt>
              <dd className="m-text">
                Review your performance
                <br />
                Learn from each session
              </dd>
              <dd className="m-text">
                <Link href={history.href}>Keep improving</Link>
              </dd>
            </div>
          </dl>
        </div>
        <div className="contact__form m-surface">
          <p className="m-text-7">{signedIn ? "Pick up where you left off." : "Set up your first practice session."}</p>
          <p className="m-text contact__panel-text">
            {signedIn
              ? "Start a new interview, or head to your dashboard to review saved reports."
              : "Create an account, choose your target role and begin a focused interview session. Already registered? Log in to continue."}
          </p>
          <ul className="contact__chips">
            <li className="m-badge">Role-specific</li>
            <li className="m-badge">Voice or text answers</li>
            <li className="m-badge">Saved reports</li>
          </ul>
          <div className="contact__actions">
            <PrimaryButton />
            <AccountButton />
          </div>
        </div>
      </div>
    </section>
  );
}
