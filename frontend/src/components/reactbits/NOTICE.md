# React Bits components

`Counter`, `CountUp`, and `StatusMark` are vendored from
[React Bits](https://reactbits.dev) (TypeScript + CSS variants,
`github.com/DavidHDev/react-bits`).

Copyright (c) 2026 David Haz. Licensed under MIT + Commons Clause: they may be used
inside an application such as this one, but the components themselves may not be
sold, sublicensed, or redistributed on their own.

Where each is used in MarketImmune:

| Component | Where | Why |
|---|---|---|
| `Counter` | Market header mark price, Quote guard p(regret) | Rolling digits keep a fast-changing number readable instead of flickering |
| `CountUp` | Model report headline metrics | One count-up when the report opens; static afterwards |
| `StatusMark` | Backfill jobs, feed status | Pending / running / done / failed glyphs for long-running jobs |
