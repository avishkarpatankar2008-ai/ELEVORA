# ELEVORA — frontend replacement

This is an independent working copy of the ELEVORA Next.js frontend. It retains the verified API client, authentication/session-cookie flow, interview lifecycle, profile/settings functionality, report views, camera analytics code and existing tests from the supplied frontend archive, while rebuilding the public landing page and moving the application to a light editorial visual system inspired by the supplied Onda-style template. The supplied ZIPs remain unmodified.

## Requirements

- Node.js 20+ (Node 22 recommended)
- npm
- ELEVORA FastAPI backend running and reachable by the Next.js server

## Local setup

```bash
cp .env.local.example .env.local
# Set BACKEND_ORIGIN to the backend origin reachable from this machine.
npm ci
npm run dev
```

The app defaults to `http://127.0.0.1:8000` for the backend and proxies same-origin `/api/*` requests through Next.js. Keep `NEXT_PUBLIC_API_URL` unset unless you intentionally need a separate API origin. The recommended same-origin proxy preserves the first-party HTTP-only session cookie.

## Verification commands

```bash
npm run typecheck
npm test
npm run lint
npm run build
```

`npm run build` copies the MediaPipe WASM assets via the existing prebuild script. Optional on-device camera models can be configured using the variables documented in `.env.local.example`. Camera frames remain client-side according to the existing analytics implementation; do not enable or describe analytics as active unless the user has consented and the relevant model assets are available.

## Routes

- `/` public landing page
- `/login`, `/signup` authentication
- `/dashboard` authenticated overview
- `/history` paginated server-side interview history (20 per page; next page is inferred from returned page length, not a fabricated total)
- `/profile` authenticated profile details and name update through the existing profile API
- `/settings` supported user preferences
- `/interview-profiles` profile management
- `/interviews/new` interview configuration
- `/interviews/[id]` interview room
- `/results/[id]` saved report

## Design and assets

The design system uses white/paper surfaces, near-black typography, restrained violet accents, editorial display typography, fine borders and reduced-motion support. The template source is retained in `../design-reference/` for traceability. Fonts are self-hosted from the supplied app's licensed Inter assets; no new remote font build dependency is introduced. The supplied template's JavaScript was not copied into authenticated interview controls; scroll-driven motion must not interfere with interview input or camera workflows.

## Honest limitations

The environment used for this delivery did not have `node_modules`, and an offline install could not complete because at least one package tarball was absent from the local npm cache. Therefore the production build, typecheck, lint and automated test suite were **not verified** in this environment. Run the commands above in a network-enabled environment and fix any reported issues before deployment. The backend must be configured and reachable for live authentication and interview operations. No mock API responses or fabricated scores have been added.
