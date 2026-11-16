import Link from "next/link";
import type { ReactNode } from "react";
import { PHOTOS, ROUND_PHOTO_BACKGROUND, type PhotoId } from "./photos";

/** The violet full stop that ends every template heading. */
export function Dot({ className = "" }: { className?: string }) {
  return <span className={`m-dot ${className}`.trim()} aria-hidden="true" />;
}

export function ArrowIcon({ className = "m-link__arrow" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 16 16" aria-hidden="true">
      <path d="M2 8h11M9 3.5 13.5 8 9 12.5" />
    </svg>
  );
}

/** In-page anchors stay plain <a>; app routes go through next/link. */
function isRoute(href: string) {
  return href.startsWith("/");
}

type LinkBase = { href: string; children: ReactNode; className?: string };

function Anchor({ href, className, children }: LinkBase) {
  return isRoute(href) ? (
    <Link href={href} className={className}>
      {children}
    </Link>
  ) : (
    <a href={href} className={className}>
      {children}
    </a>
  );
}

/** Underlined text link with a sliding arrow (template `.m-link`). */
export function MLink({ href, children, className = "" }: LinkBase) {
  return (
    <Anchor href={href} className={`m-link ${className}`.trim()}>
      <span className="m-link__label">{children}</span>
      <ArrowIcon />
    </Anchor>
  );
}

/** Quiet footer/nav link (template `.m-link-2`). */
export function MLink2({ href, children, className = "" }: LinkBase) {
  return (
    <Anchor href={href} className={`m-link-2 ${className}`.trim()}>
      {children}
    </Anchor>
  );
}

/** Filled violet pill (`primary`) or white pill (`secondary`) with the ink-drop hover. */
export function MButton({
  href,
  children,
  variant = "primary",
  className = "",
}: LinkBase & { variant?: "primary" | "secondary" }) {
  return (
    <Anchor href={href} className={`${variant === "primary" ? "m-btn" : "m-btn-2"} ${className}`.trim()}>
      <span className="m-btn__label">{children}</span>
    </Anchor>
  );
}

type PhotoProps = {
  id: PhotoId;
  className?: string;
  loading?: "lazy" | "eager";
  priority?: boolean;
  /** Use the inline blurred placeholder painted behind the round hero/footer photo. */
  roundPlaceholder?: boolean;
  alt?: string;
};

/** Template <img> with its original srcset, intrinsic size and placeholder colour. */
export function Photo({ id, className, loading = "lazy", priority = false, roundPlaceholder = false, alt }: PhotoProps) {
  const photo = PHOTOS[id] as (typeof PHOTOS)[PhotoId] & { srcSet?: string; sizes?: string; bg?: string };
  const background = roundPlaceholder ? ROUND_PHOTO_BACKGROUND : photo.bg;
  return (
    // eslint-disable-next-line @next/next/no-img-element -- remote Unsplash photos with the template's own srcset
    <img
      className={className}
      style={background ? { background } : undefined}
      src={photo.src}
      srcSet={photo.srcSet}
      sizes={photo.sizes}
      width={photo.width}
      height={photo.height}
      alt={alt ?? photo.alt}
      loading={priority ? undefined : loading}
      decoding="async"
      // React 18 warns on the camelCase `fetchPriority`; the lowercase attribute is what browsers read.
      {...(priority ? ({ fetchpriority: "high" } as Record<string, string>) : {})}
    />
  );
}
