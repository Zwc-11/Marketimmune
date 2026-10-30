# MarketImmune frontend: visual and engineering contract

This is the one source of truth for how the web app looks and behaves.
`CLAUDE.md` and `AGENTS.md` in this folder point here. Change this file first when
a change would break a rule below.

## What the app is

An exchange-style terminal for one question: **which SOL perp fills will a market
maker regret 10 seconds later?** It sits next to Hyperliquid and Phoenix in a
trader's tab bar, so it borrows their conventions instead of a dashboard kit:
dark, dense, numbers first, green and red with fixed meanings.

## References

- **Hyperliquid** (`app.hyperliquid.xyz/trade/SOL`): one font at 12 px for nearly
  everything, market header of label-over-value pairs, order book with cumulative
  depth bars, underlined text tabs, a thin status footer.
- **Phoenix** (`phoenix.trade`): near-black field, panels with small radii and
  4 px gutters, tabular numerals everywhere, a single strong CTA.
- **designeer.xyz** (curated interface craft): translucent hairlines instead of
  grey borders, pill filters, tactile pressed buttons, slightly negative tracking
  on display type, dot-matrix data marks.
- **React Bits** (`reactbits.dev`): four vendored components, each with a job
  (see `frontend/src/components/reactbits/NOTICE.md`). No decorative backgrounds.

## Tokens (`frontend/src/styles/tokens.css`)

| Token | Value | Use |
|---|---|---|
| `--ink-0` | `#0c1015` | Page field |
| `--ink-1` | `#11161c` | Panels |
| `--ink-2` / `--ink-3` | `#171e25` / `#1e262f` | Hover / selected |
| `--rule` / `--rule-strong` | white at 7% / 12% | Hairlines |
| `--fg` / `--fg-2` / `--fg-3` | `#e1e6eb` / `#9ea9b4` / `#67737f` | Text ladder |
| `--bid` | `#1fb873` | Bids, maker gained, quote |
| `--ask` | `#f0464f` | Asks, maker regretted, withhold |
| `--warn` | `#e3a43b` | Sample data, decisions in the audit log |
| `--cta` | `#f2f5f7` | The one primary button per view |

Colour carries meaning only. The brand is monochrome so green and red stay loud.
Dark only, like the venues.

## Type

- **IBM Plex Sans** for everything (it is the family BinancePlex grew from);
  numbers always `tabular-nums` (`.num`). 12 px data, 11 px column heads and
  labels, 13 px panel titles and tabs, 28 px report headlines with -0.025em
  tracking.
- **IBM Plex Mono** only for code, commands, and record IDs. Never for labels.
- Sentence case everywhere. No all-caps labels, no eyebrow text above headings.

## Layout

```
┌ top nav: brand · Terminal  Model  Immune loop  Audit ··············· Source ┐
├ market header: SOL-PERP  mark  oracle  24h  volume  OI  funding  spread  OFI ┤
├ price (1m candles) ─────────────────┬ order book ──────┬ quote guard ───────┤
│                                     │ asks / spread /  │ decision           │
│                                     │ bids, depth bars │ regret matrix      │
├ regret log | Gold fills | folds | … ┤ fills + 10 s     │ live stats         │
│                                     │ regret clock     │ held-out benchmark │
└ status bar: stream state · last message · model artifact · Django API ─────┘
```

Under 1280 px the guard drops below; under 860 px everything stacks in one column
with the bottom tables capped at 520 px tall.

## Signature elements

1. **Regret clock.** Each pending fill on the tape draws a bar that fills over the
   10 s label horizon (pure CSS, phase-aligned to the exchange clock at mount),
   then settles into the realized maker markout. It keeps running under reduced
   motion because it is a progress readout.
2. **Regret matrix.** The last 100 resolved fills, one square each: red regretted,
   green kept with a gain, grey kept but under the 1 bps fee, hollow if the model
   would have withheld it.

Everything else stays quiet.

## Honesty rules

- Live numbers come from Hyperliquid's public API; model numbers come from the
  committed report in `docs/benchmarks/` or the Django API. Nothing is simulated.
- With no exported model, fills are labelled but not scored, and the UI says so.
- The sample immune-loop run appears only after "Show a sample run" and is badged
  "Sample run, not live output" on every view.
- The validation scheme is named as it was run (`purged_kfold` for the committed
  report); the held-out day is the headline because it is the out-of-time number.

## Engineering rules

- The feed (`src/market/feed.ts`) mutates private state per WebSocket message and
  publishes one snapshot per animation frame. Slices keep identity until they
  change; components select a slice with `useMarket(s => s.book)`.
- Feature and model code in `src/lib/` mirrors Python and is pinned by
  `src/lib/parity.test.ts` against fixtures from
  `python -m scripts.make_frontend_parity_fixtures`.
- No per-row timers. Animations are CSS; React only renders on data change.
- Every source file stays under 1000 lines (`scripts/check_line_limit.py`).

## Checklist

- [ ] Colours from tokens; green and red only for side or outcome.
- [ ] Numbers right-aligned and tabular; labels sentence case.
- [ ] Empty states say what to run, not that something is missing.
- [ ] Keyboard focus visible; selectable rows reachable with Enter or Space.
- [ ] `npm run typecheck`, `npm test`, `npm run build` pass in `frontend/`.
