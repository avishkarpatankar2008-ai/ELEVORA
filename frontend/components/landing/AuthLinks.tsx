"use client";

import { MButton, MLink, MLink2 } from "./ui";
import { useLandingLinks } from "./useLandingLinks";

/** Small auth-aware link variants, so the surrounding sections can stay server components. */
export function PrimaryMLink({ className }: { className?: string }) {
  const { primary } = useLandingLinks();
  return (
    <MLink href={primary.href} className={className}>
      {primary.label}
    </MLink>
  );
}

export function PrimaryButton({ className }: { className?: string }) {
  const { primary } = useLandingLinks();
  return (
    <MButton href={primary.href} className={className}>
      {primary.label}
    </MButton>
  );
}

export function AccountButton({ className }: { className?: string }) {
  const { account } = useLandingLinks();
  return (
    <MButton href={account.href} variant="secondary" className={className}>
      {account.label}
    </MButton>
  );
}

export function AccountLink2({ className }: { className?: string }) {
  const { account, signedIn } = useLandingLinks();
  return (
    <MLink2 href={account.href} className={className}>
      {signedIn ? "Dashboard" : "Log in"}
    </MLink2>
  );
}
