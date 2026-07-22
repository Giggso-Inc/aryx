# Ask Search — 2026-07-21

## Goal

Add search to the Ask conversation page and the right-side Ask Threads history panel.

## Decisions

- Reuse one accessible search input across both surfaces.
- Filter loaded conversation messages by content on the Ask page.
- Filter the 100 loaded thread summaries by title in the history drawer.
- Keep filtering client-side because both datasets are already present in page state.
- Reset conversation search when switching threads or starting a new Ask.

## Verification

- Focused frontend contracts: 3 passed.
- TypeScript: `tsc --noEmit` passed.
- Whitespace audit: `git diff --check` passed.
- Next.js lint requires an interactive first-time ESLint configuration.
- Production build reached optimization but did not finish within the validation window.

## Open Questions

- Decide later whether transcript search should request messages older than the currently loaded page.
