# Jurisdiction and data-access terms (Phase 0, task 1)

Checked 2026-10-30. Not legal advice: this records what each document says and
how the project is scoped around it. Recheck before Phase 6 and whenever a
document's "last updated" date changes.

## Conclusion

1. **Do not use the Hyperliquid web interface.** The interface terms (last
   updated 2026-06-15) list persons who reside in or are located in Ontario,
   Canada as Restricted Persons and bar them from the interface (§1.6). Opening
   app.hyperliquid.xyz from this machine shows a restricted-jurisdiction banner.
   The project never connects a wallet, never signs an action and never places an
   order. The strategy runs only in simulation.
2. **Do not route around a block.** §1.9 and §3.1.5 forbid VPNs, proxies or
   other methods used to conceal location or evade the restrictions. The recorder
   VPS is chosen for clock quality and uptime, not to change where the user
   appears to be, and nothing in this repository tries to defeat a geoblock. If
   any endpoint answers with a jurisdiction error, stop using it and record that
   here.
3. **The interface terms do not address the public API or the S3 archives.**
   They govern the website-hosted interface operated by Hyperliquid Corp. (§1),
   say the company does not operate the chain (§1.1), and say the interface is
   not the only way to access it (§1.1). They are silent on
   `api.hyperliquid.xyz` market-data WebSockets, the `info` endpoint, and the
   `hl-mainnet-node-data` / `hyperliquid-archive` buckets. No separate API terms
   were found. That silence is not a permission: it is the open question below.
4. **Foundation non-validating node: not eligible, and not needed.** Connecting
   to the Foundation's node requires 10,000 staked HYPE, Tier 1 maker volume and
   excludes certain activities involving the US or Ontario. The optional own node
   in Phase 3 peers with the public p2p network instead (see `infra/node/`).

## Open question (decide before the recorder goes live)

Is reading public market data from `api.hyperliquid.xyz` (WebSocket `l2Book`,
`bbo`, `trades`; `info` `meta`) from Ontario consistent with the interface terms'
intent? Options, in order of caution:

- Ask Hyperliquid support (support@hyperliquid.zendesk.com, the contact in §11.3)
  whether the API and S3 archives are covered by the interface restriction.
- Until answered, run Phase 0–1 on archived data only (S3 `replica_cmds`,
  `node_fills_by_block`, the Albers dataset) and start the recorder after the
  answer. Forward data is needed only from Phase 5 (simulator baseline) and the
  held-out window (Phase 6), so a short delay costs little.

The `info` endpoint has a `legalCheck` request type that returns
`acceptedTerms`, `userAllowed` and a `restrictions` code for an address. It is
about wallets, which this project never uses, so it does not answer the question.

## Other sources

| Source | Terms | What it means here |
| --- | --- | --- |
| Albers et al. L4 dataset (Zenodo 18184441) | CC BY 4.0 | Free to use and redistribute derivatives with citation. Cite the DOI in the data card and paper. |
| Binance Vision (`data.binance.vision`) | Binance Vision Terms of Use v1.0 (2026-08-26), datasets under CC BY-NC-SA 4.0 | Academic research is a permitted non-commercial use. A released dataset that contains Binance-derived fields must carry attribution and the same NC-SA licence. No geographic restriction in the text. |
| Binance USD-M WebSocket (`fstream.binance.com`) | Binance's general terms; Binance left Ontario in 2023 | Same open question as the Hyperliquid API: public market data, no account, but check before the recorder subscribes. Fallback reference venues: OKX, Bybit (both in Hyperliquid's oracle). |
| Hyperliquid S3 buckets | Requester pays; no data licence found | Use for research; do not redistribute raw files. Release only derived tables. |

## Sources

- Hyperliquid interface Terms of Use, last updated 2026-06-15: https://app.hyperliquid.xyz/terms (read in a browser; the page is client-rendered)
- Foundation non-validating node: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/nodes/foundation-non-validating-node
- `legalCheck` info request: https://docs.chainstack.com/reference/hyperliquid-info-legal-check
- Binance Vision Terms of Use: https://data.binance.vision/Binance_Vision-Terms_of_Use.pdf
- Albers et al. dataset: https://zenodo.org/records/18184441
