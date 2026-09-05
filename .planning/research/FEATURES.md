# Feature Research

**Domain:** AI-first crypto quant trading platform (NL strategy authoring → validated spec → backtest/paper/live on one engine, Copilot-approved live execution on Binance spot)
**Researched:** 2026-09-05
**Confidence:** MEDIUM (competitor feature sets verified against vendor primary docs where possible; market-size and churn figures are LOW)

---

## Headline Findings

Five things changed my view of the source docs. Read these before the tables.

1. **The safety architecture is no longer a differentiator — it is the marketed norm.** Minara's Autopilot page already sells per-asset mandate scoping, mandatory stops that "can't be silently removed," a drawdown stop that flattens everything, manual override treated as an intentional override with "no conflicts, no hidden retries," non-custodial operation, and "deterministic signals, mandatory risk controls, auditable actions — no discretionary AI trades." Its Copilot preps orders and "you approve before anything hits the book." That is this project's entire trust chain, already on a competitor's marketing page. Building it correctly is table stakes. Claiming it is worth nothing.

2. **Quant-Phase's claim that almost no platform ships live-vs-backtest divergence tracking is FALSE.** QuantConnect ships **Live Reconciliation**: it runs an out-of-sample backtest in parallel to *every* live deployment, automatically, and overlays the two equity curves on the live results page, with tooling to overlay order fills in the research environment. It has done so for years. The feature is real, valued, and taken. What is *not* taken is per-trade slippage attribution, strategy decay detection against a backtest confidence band, and cross-strategy correlation — three of the four survive.

3. **Quant-Phase's "sell the truth about overfitting" thesis is half right, and needs restating to survive.** Rigorous validation is already shipped — just not here. StrategyQuant X (desktop, forex/futures) ships two Monte Carlo engines with 9+ simulation types, walk-forward optimization *and* a walk-forward matrix with 3D result views, and automated "cross checks" that **auto-reject** strategies during generation. BuildAlpha is comparable. Meanwhile Minara markets walk-forward, out-of-sample, regime-sliced views, and automatic leakage detection. So "almost nobody does it properly" is wrong as stated. The defensible restatement is in the Differentiators section: **trial accounting**, not validation per se.

4. **The exchanges are commoditizing the "AI can trade" plumbing.** Kraken, Binance, OKX, and Coinbase all shipped native agent toolkits in 2026. OKX's Agentic Wallet simulates every transaction pre-execution with a plain-language summary and automatic risk grading, keys in a TEE. Coinbase for Agents (June 2026) lets ChatGPT or Claude execute crypto trades from natural language. Gemini shipped Agentic Trading in April 2026. **"An LLM can place a trade safely" is a solved, free, commodity capability by end of 2026.** Nothing in this project's value should rest on it.

5. **Composer — the best-funded NL-to-strategy builder — exited crypto entirely on 2026-01-31** and was acquired by SoFi in June 2026. Users with crypto symphonies were told to update or liquidate. Read as: the no-code AI strategy category retreated from crypto toward regulated equities/ETFs. That is either a vacated niche or a warning; it is at minimum a fact worth knowing before betting a year on the niche.

---

## Feature Landscape

### Table Stakes (Users Expect These)

Missing any of these and the product feels broken. None of them win a user; all of them lose one.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Backtest with a real cost model (maker/taker fees, slippage, partial fills) | Every competitor has it. A backtest without costs is the thing users have learned to distrust. | LOW | Nautilus supplies fill/fee models. Complexity is data, not code. Note Freqtrade's weakness for contrast: standard backtest fills at requested price with no slippage if inside the candle. |
| Equity curve, drawdown, Sharpe, win rate, per-trade P&L | Baseline literacy of the category | LOW | Nautilus produces most of it. |
| Paper trading on live data, same engine as live | 3Commas, Cryptohopper, Freqtrade, Minara, QuantConnect all ship it | LOW–MED | Free from the Nautilus decision. This is the *precondition* for the differentiators, not a differentiator itself. |
| Natural-language → editable structured strategy spec | Minara, Composer, TrendSpider all accept NL. This is the category's front door in 2026. | HIGH | The spec must be human-readable and hand-editable. See "NL authoring failure modes" below — the editable structured artifact *is* the mitigation. |
| Exchange connection with trade-only keys, withdrawals disabled, IP allowlist | Standard guidance in every bot setup guide; also this project's stated posture | MED | The onboarding cost is real: the user leaves your product, goes to Binance, and comes back. See Onboarding. |
| Immutable versioned strategy registry | Users edit strategies constantly and need to know which version produced which result | MED | Already an Active requirement. Also the substrate for trial accounting — see Differentiator D1. |
| Live position / order / balance view that matches the exchange | Position drift is the failure users notice first and forgive last | HIGH | This is reconciliation. Expensive, invisible, non-negotiable. |
| Per-trade approval showing exact executable values + expiry | Copilot mode is the product. Norm is the model stages, human approves. | MED | See "Approval UX" — the expiry design is harder than it looks. |
| Out-of-band notification for pending approvals | A 30-second in-app approval window is unusable if the user has to be looking at the tab | LOW–MED | **Hard dependency of Copilot, not a nice-to-have.** See conflict note vs "Mobile app" Out of Scope. |
| Kill switch / pause at strategy and account level | Minara markets it; users will not connect keys without it | MED | Already an Active requirement. Flatten must be separately gated — auto market-exits create their own losses. |
| Execution timeline: order → fills → fees → position, with timestamps | "Where did my money go" is the first support question | MED | Postgres ledger. Already planned. |
| Honest failure states surfaced (UNKNOWN order, stale data, disconnect, rate limit) | Silent failure is the trust-ending event named in the project's own success metric | MED | Most competitors hide these. Showing them is cheap and disproportionately trust-building. |
| Data quality visibility (gaps, outliers, exchange candle restatements) | If the user can't see the data was clean, the backtest is a claim not a result | MED | Already an Active requirement. Surfacing it in the UI costs little on top. |

### Differentiators (Competitive Advantage)

Ranked by defensibility, not by appeal.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **D1. Trial-counted overfitting evidence** — deflated Sharpe / probability of backtest overfitting where the trial count *N* is the platform's own record of every optimization attempt the user made | Bailey & López de Prado's central point: the number of trials attempted is the single most-missing datum in every published backtest, and P(overfit) grows rapidly with N. **Only the platform that ran the optimizations can count them honestly.** A user cannot self-report N; a competitor cannot retrofit it without owning both the optimizer and an immutable registry. | HIGH | Found only in academic literature — **no retail or AI-first platform surfaces DSR/PBO or trial counts as a user-facing feature.** Genuine open space. Requires: immutable registry + every backtest run logged as a trial against a strategy lineage. Cheap *given* the registry; impossible without it. |
| **D2. Enforced OOS lockbox with a look budget** | Everyone "recommends" out-of-sample. Nobody *enforces* it. Make OOS data technically unreachable until the user spends one of N looks, and record each look as a trial feeding D1. Turns a best practice into a state machine. | MED | Already implied by the Active requirement "OOS is genuinely untouched during optimization" — this makes it a product surface rather than an internal discipline. Directly enables D1's honesty. |
| **D3. Per-trade slippage attribution** — expected fill vs actual fill, per trade and aggregated, with a decomposition | Not found shipped anywhere. It is the concrete, per-trade version of the abstract "backtest lied to you," and it answers the question users actually have. Quant-Phase is right: "users will love you for this." | MED | Requires: intent records the expected price and the market snapshot; ledger records the actual fill. Both already planned. Nearly free once the ledger exists. |
| **D4. Strategy decay detection** — rolling Sharpe with an alert when live falls outside the backtest's confidence band | Not found shipped. Converts "check on your bot" from a chore into a notification, which is the actual retention mechanic. | MED | Depends on D5's divergence infrastructure and on having a backtest confidence band (Monte Carlo on trade ordering — already an Active requirement). |
| **D5. Live-vs-backtest divergence on a genuinely shared engine** | QuantConnect ships the overlay by re-running a parallel backtest of the same code. This project can make the *stronger* claim — the live and simulated paths are literally the same evaluator, so a divergence is attributable to data or execution and never to a code difference. That attribution is the value; the chart is table stakes. | MED | **Not novel — QC has it.** Sell the attribution ("your divergence is 80% slippage, 20% data lag"), not the overlay. Directly enabled by the Nautilus decision. |
| **D6. Cross-strategy correlation** — "your five strategies are one long-BTC-momentum bet at 5x" | Exists in institutional portfolio analytics; **not found in any retail crypto or AI-first trading product.** Quant-Phase is correct here. | MED | **Worth zero in v1** — two builders running one or two strategies have nothing to correlate. Value scales with strategy count. Defer to v1.x. |
| **D7. Explanation layer** — why this fired, why the backtest looks like this, where it is likely overfit | The AI capability that is actually load-bearing. It reads the frozen spec and the recorded evidence and explains; it does not decide. Distinct from every competitor's "AI picks trades." | HIGH | Depends on D1/D2 for the overfitting half and on the evidence store for the research half. Highest AI value per unit of AI risk. |
| **D8. Evidence provenance + information-cutoff tracking** on every research claim | Directly attacks the worst documented LLM failure mode in finance (plausible-but-false statistics/earnings/events) and is the only way to avoid look-ahead bias in AI-sourced signals. Also the artifact that makes a bull/bear debate auditable rather than theatrical. | MED–HIGH | `EvidenceReference` is already designed in Architecture_Plan. The hard part is discipline in tool wrappers, not schema. |
| **D9. Parameter sensitivity surface** — plateau or needle? | StrategyQuant and TrendSpider (Variance Explorer, 52 variants) ship versions of this; retail crypto does not. Cheap, visual, immediately legible. | MED | Highest legibility-per-unit-effort of the validation features. Good first validation surface to ship. |
| **D10. Risk-check receipt on the approval card** — not "14 checks passed" but the 14 checks, with observed value vs limit | `RiskDecision.checks[]` already carries this. Rendering it is nearly free and converts an opaque approval into an inspectable one. The single cheapest trust win in the product. | LOW | Do this in v1. |
| **D11. Strategy novelty / duplicate detection** | LLMs mode-collapse: ask for 20 strategies and get ~6 distinct ones in costumes. Flagging "this is your RSI-14 strategy with a different threshold, and it already counts as trial #37" is novel and feeds D1. | MED | Depends on D1's trial ledger. Not v1. |

**Verdict on the Quant-Phase overfitting thesis:** the thesis as written — "almost nobody does it properly, so validation is your differentiation" — does **not** hold. StrategyQuant X and BuildAlpha do it properly today and have for years, and Minara markets the same claims in this exact category. Validation rigor is a commodity you can buy for $/month in the adjacent desktop segment.

The thesis survives only in this restated form, and in this form it is strong:

> **We are the only party who can count your trials, and we lock the out-of-sample data so the count stays honest.**

That is D1 + D2. It is not "we run walk-forward" (buyable) or "we tell you it's overfit" (unsellable pessimism). It is a structural claim that requires owning the optimizer, the registry, and the data gate simultaneously — which this project already plans to own for unrelated reasons. It is also, honestly, a *retention* feature with weak top-of-funnel: nobody signs up to be told they are wrong. Do not put it on the landing page; put it in the product where a user who already trusts you finds it.

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Marketplace / copy trading / leaderboards | Cryptohopper and 3Commas both ship it; it is the category's growth engine | Needs supply and trust you don't have; over short windows luck is indistinguishable from skill; in most jurisdictions it starts to look like offering securities. The SEC's May 2026 action against Privvy Investments ($12.3M, ~150 investors, fake AI bots) targeted *performance claims and pooled funds* — exactly the surface a leaderboard creates. | Already Out of Scope. Keep it there. Share strategy *specs* privately between the two builders if needed; never share *results*. |
| Projected returns, APR estimates, "AI confidence: 87%" | Every competitor shows them; they convert | This is the precise thing CFTC advisories ("AI Won't Turn Trading Bots into Money Machines") and SEC enforcement target. A confidence percentage from an LLM is a number with no referent, and users read it as a probability. | Show realized distributions and confidence *bands* from Monte Carlo. Show the trial count. Never a single forward number. |
| Custody / wallets | Simplifies onboarding enormously — no API key detour | Existential security risk and a licensing question. Also converts you into the pooled-fund pattern regulators pursue. | Already Out of Scope. Correct. Eat the API-key onboarding friction; it is a feature, not a bug, and it should be *said* to users as one. |
| Social sentiment as a strategy input | Every AI trading product advertises it; TradingAgents has a sentiment analyst | Point-in-time correctness for scraped social data is near-impossible, so it silently poisons backtests with look-ahead. It is the highest-hallucination-risk input in the stack. | If used at all, only inside the research plane producing a human-read artifact with `availableToStrategyTime` — never as a live DSL input. |
| Continuous / unattended model retraining in live | FreqAI ships constant background retraining as a headline feature | It manufactures live-vs-backtest divergence by construction — the live model is by definition not the backtested model. Destroys D5. | Retrain as an explicit, versioned, re-validated new strategy version that re-enters the state machine. Never in-place. |
| Building on exchange-native agent toolkits (Coinbase for Agents, OKX Agentic Wallet) | Free, fast, shipping now, "why build a risk kernel" | Inverts the trust model: the agent holds the authority and the exchange holds the gate. The core value here is that the LLM never reaches `createOrder()`. Adopting these is abandoning the product's thesis. | Nautilus + own deterministic gate. Note these exist so you can articulate why you're not using them. |
| Open-ended AI market chat as the primary interface | It is what "AI-first" reads as, and it demos beautifully | Quant-Phase: only valuable once the data layer is good enough to answer from. Before that it is a hallucination surface attached to your brand. | Scope chat to the artifact in front of the user — authoring and editing *this* strategy, explaining *this* backtest, *this* fill. Not a market oracle. |
| Multi-agent debate transcripts as a UI surface | It is TradingAgents' most impressive-looking output | Nobody reads a five-agent transcript before a trade. It is the canonical demo-ware of this category. | Ship the *artifact*: a `SignalCandidate` with a thesis, the strongest opposing evidence, and citations, readable in 30 seconds. The debate is machinery, not a deliverable. |
| Autopilot | The obvious next step; Minara sells it | Already Out of Scope for v1. Also: with Copilot you learn what your risk gate misses while a human is still in the loop to catch it. That learning is the entire reason to ship Copilot first. | Keep out of scope. Resist the "standing approval within a price band" shortcut — that is Autopilot wearing a Copilot costume. |
| PineScript / LEAN strategy importer | Quant-Phase recommends it: "a strategy library on day one instead of an empty marketplace" | **I disagree for v1.** An importer is a compiler project of its own — PineScript's semantics are underspecified and its indicator library is large. The first users are the two builders, who do not need a library and can author directly. Solving the empty-library problem before you have users is solving a problem you do not have. | A dozen hand-written reference specs in the repo. Revisit the importer when a third user exists. |
| Mobile app | Approvals need to reach the user away from a desk | Already Out of Scope, and correctly — quant work doesn't happen on a phone. **But the approval loop genuinely needs mobile reach.** | See conflict note below. Push notification / Telegram bot / PWA — a notification channel, not an application. |

---

## Conflicts With PROJECT.md "Out of Scope"

Flagged explicitly, per the downstream consumer's request.

1. **Approval notifications vs. "Mobile app — quant work does not happen on a phone."**
   These collide. A per-trade approval with a short expiry is unusable if delivery is in-app only; the user misses fills while asleep, commuting, or on another tab. Every DIY bot that requires per-trade approval routes it through **Telegram** for exactly this reason.
   *Resolution:* build a notification channel (web push and/or a Telegram bot), not a mobile app. Approving from the phone is a one-tap action against a preview; authoring, backtesting, and analysis stay on desktop. This respects the intent of the Out of Scope entry while unblocking the v1 loop. **It should be an Active requirement, and it currently is not.**

2. **Cross-strategy correlation vs. v1 reality.** Not an Out of Scope conflict, but it is listed under Active "Post-deployment monitoring" and it produces literally no signal with fewer than ~3 concurrent live strategies. Recommend moving to v1.x with an explicit trigger.

3. **AI chat.** Architecture_Plan §17 lists `Chat` in the `web` service; Quant-Phase lists "AI chat" under features not to build for a long time. PROJECT.md does not resolve this. Recommendation above: artifact-scoped chat in v1, no open-ended market chat.

---

## Answers to the Specific Questions

**1. What NL→strategy actually looks like in shipped products, and where it fails.**
Three shipped shapes: Minara (NL thesis → structured spec → backtest → paper → Autopilot, free), Composer (NL → visual drag-and-drop "symphony" you then edit by hand, ~$32/mo, crypto removed Jan 2026), TrendSpider (NL *or* point-and-click into a strategy tester). All three converge on the same answer: **NL produces a structured artifact the user then edits.** Nobody ships NL→execution without an inspectable intermediate, and that is the correct pattern for the right reason.

The failures are documented. QuantCode-Bench (2026) finds frontier models reach only ~70–76% pass rate generating executable trading strategies single-turn, rising to 95–98% in *agentic* settings with tool feedback — and the failures are not syntax but **wrong operationalization of trading logic, API misuse, and task-semantic drift**. Secondary failures: **mode collapse** (ask for 20 strategies, get ~6 distinct ones renamed), **financial-data hallucination** (plausible false statistics/earnings/events, most dangerous when executed unreviewed), and **action instability** (buy-then-immediately-sell flipping).

Every one of these is mitigated by the architecture already chosen: restricted JSON DSL (no free code), a validator that rejects ambiguity, an agentic compile loop where validator errors feed back to the model (the 70%→95% delta), and a human reading the spec before it runs.

**2. Validation and honesty features — does the thesis hold?** Answered above. Short version: rigorous validation is shipped by StrategyQuant X / BuildAlpha (desktop, forex/futures) and *marketed* by Minara in this exact category. QuantConnect leaves walk-forward as a documented DIY pattern. TrendSpider has no walk-forward and no Monte Carlo. Retail crypto bots have essentially nothing. **Nobody sells "your strategy is probably overfit" and nobody surfaces DSR/PBO or trial counts.** The thesis survives only as trial accounting + an enforced OOS lockbox (D1+D2), and it is a retention feature, not an acquisition one.

**3. Post-deployment monitoring — does the thesis hold?** Partly. **Live-vs-backtest divergence is taken** — QuantConnect's Live Reconciliation runs an OOS backtest in parallel to every live deployment and overlays the curves automatically. Slippage attribution, decay detection, and cross-strategy correlation were **not found shipped anywhere in this category**, so 3 of 4 survive. The retention argument is sound regardless: the documented churn driver is the backtest-to-live disappointment gap, and these four features are the only ones that address it after deployment rather than before.

**4. Approval UX.** The norm: the model stages, the human reviews an exact preview, approval is required when the action spends money or is hard to reverse, and the preview must show the exact amounts and instrument being authorized. OKX's Agentic Wallet simulates every transaction pre-execution with a plain-language summary plus automatic risk grading. Minara: "you approve before anything hits the book." DIY bots use Telegram. A common hybrid is deterministic auto-approval below a notional threshold with human approval above it — **that hybrid is Autopilot in disguise and is out of scope here.**

Architecture_Plan §8's preview content is correct and complete; add D10 (the itemized risk-check receipt). The unsolved design problem is **expiry**. A 30-second wall-clock window is brutal for a human. Two better framings:
- *Price-band expiry:* the approval stays valid while the market stays inside the slippage band, re-validated at approval time and rejected if it moved. Longer human window, same safety, still bound to the intent hash (the hash covers `expiresAt`, so this is a change to how `expiresAt` is chosen, not to the binding).
- *Notification-first:* time-to-approval is dominated by time-to-notice, so the notification channel matters more than the timer.
Both are cheap. The friction to *keep* is the requirement to read the values; the friction to *remove* is having to be at the screen.

**5. Trust and safety surface.** The marketed norm, per Minara/OKX, is: scoped authorization (which assets, nothing else), risk controls that cannot be silently disabled, a user-set drawdown stop, always-available manual override where manual actions are treated as intentional (no hidden retries), non-custodial, and auditable actions. This project plans all of it. **Treat it as table stakes and budget accordingly.** The things that would go *beyond* the norm, in order of cost-effectiveness: the itemized risk-check receipt (D10, nearly free), honest surfacing of `UNKNOWN`/stale/disconnected states rather than hiding them, a visible reconciliation status ("Nautilus, Postgres and Binance agree, as of 14:03:11"), and a user-readable audit export.

**6. Onboarding.** The path is: sign up → author or pick a strategy → backtest → create Binance API key with trade permission and withdrawals disabled → connect → paper trade → go live. Two documented loss points. First, **the API-key detour** — the user leaves your product for the exchange and must get permission scoping right; this is where the funnel bleeds, and it is also non-negotiable given no-custody. Mitigate with an in-product step-by-step with screenshots and an automated permission check that verifies withdrawals are actually disabled and fails loudly if not. Second, **the paper-trading gate is advice, not a gate** — community guidance is "paper trade at least two weeks," and a documented failure mode is a 3-day paper run with 2 wins from 3 trades followed by a live -15%. Since this project already has a `PAPER_RUNNING → PAPER_PASSED` state transition, **make PAPER_PASSED require a minimum duration and a minimum trade count**. That is a differentiator hiding in a state machine you are already building.

**7. AI research/chat — value vs demo-ware.**
Valued: the **opposing case** with citations (the bull/bear structure's one real contribution — it manufactures a counter-argument a motivated user won't generate themselves); provenance and timestamps on every claim; explanation of why a strategy fired, tied to the frozen spec.
Demo-ware: the debate transcript as a UI, the agent "deciding," a confidence percentage, sentiment scraped from social, and TradingAgents' own risk-manager/portfolio-manager approval stage — which in this architecture is *replaced* by the deterministic gate and should not be rendered at all. TradingAgents itself (102.6k stars, 19.8k forks) executes only against a **simulated exchange** and disclaims: "designed for research purposes… not intended as financial, investment, or trading advice." Its genuinely useful recent additions are checkpoint resume, a decision log with realized returns, structured output, and **look-ahead / point-in-time data-access fixes** — mine those, ignore the framing.

**8. Anti-features that harmed users or drew regulators.** Documented pattern: performance claims plus pooled funds. SEC v. Fuller / Privvy Investments (May 2026), $12.3M from ~150 investors on fake AI bots, $6.2M misappropriated, $5.5M in Ponzi-like payments. Steynberg: $1.7B from 23,000 people on a "proprietary AI bot" promising ≥10% monthly. CFTC has standing advisories on AI trading-bot scams. Legal baseline: bots are legal in the US, and every anti-fraud and anti-manipulation rule applying to a human applies identically to the bot and its operator. **Nothing in the enforcement pattern targets the software — it targets return promises, pooled capital, and custody.** No custody, user-owned accounts, no return projections, no leaderboard, no marketplace is therefore a compliance posture, not just conservatism. Say so internally so nobody relitigates it.

**9. Pricing norms (v1 has no billing — reference only).** Freemium is universal. Cryptohopper: free Pioneer, then ~$24 / $58 / $108 per month on annual. 3Commas: free, then ~$16 / $38 / $94 per month on annual. Composer: ~$32/month flat, no annual discount. Kryll: no subscription — pay per strategy execution in KRL tokens, ~0.1–1% of volume. Minara Strategy Studio: currently free. Freqtrade, Hummingbot, TradingAgents: open source. **The category anchor is $20–60/month with a free tier, and the AI-first entrants are currently giving it away.** Do not plan a pricing model against a free competitor; plan against the possibility that the AI layer is free forever and the validation/monitoring layer is what people pay for.

---

## Feature Dependencies

```
[Same-engine backtest/paper/live]            <- the Nautilus decision, load-bearing for everything below
    ├──enables──> [D5 Live-vs-backtest divergence]
    │                  └──enables──> [D4 Strategy decay detection]
    ├──enables──> [D3 Slippage attribution]  (also requires: intent expected-price + ledger actual fill)
    └──enables──> [Paper trading]
                       └──gates──> [PAPER_PASSED duration/trade-count gate]

[Immutable versioned strategy registry]
    └──enables──> [D1 Trial-counted DSR/PBO]
                       ├──requires──> [D2 Enforced OOS lockbox]
                       ├──requires──> [Monte Carlo on trade ordering]  (confidence bands)
                       ├──enables───> [D11 Novelty / duplicate detection]
                       └──feeds─────> [D7 Explanation layer: "where it's likely overfit"]

[Restricted JSON DSL + validator]
    ├──enables──> [NL -> StrategySpec compiler]   (validator errors feed back: 70% -> 95% pass rate)
    └──enables──> [D7 Explanation layer: "why it fired"]

[Evidence store + information-cutoff tracking]
    └──enables──> [D8 Provenance]  ──enables──> [SignalCandidate artifact]
                                                     └──feeds──> [D7 Explanation layer]

[Deterministic risk gate]
    ├──enables──> [Copilot approval]  ──requires──> [Notification channel]   <-- MISSING from Active reqs
    └──enables──> [D10 Risk-check receipt on approval card]

[Postgres ledger + reconciliation]
    ├──enables──> [Execution timeline]
    ├──enables──> [D3 Slippage attribution]
    └──enables──> [Honest failure-state surfacing]

[3+ concurrent live strategies] ──required-by──> [D6 Cross-strategy correlation]

[Continuous live retraining]  ──conflicts──>  [D5 Live-vs-backtest divergence]
[Standing band approval]      ──conflicts──>  [Copilot-only v1 constraint]
[Leaderboard / shared results]──conflicts──>  [no-custody, no-claims regulatory posture]
```

### Dependency Notes

- **D1 requires the registry, not the other way around.** Trial accounting is cheap if every backtest run is recorded against a strategy lineage from day one, and impossible to reconstruct later. **This is a schema decision that must be made in the foundation phase**, before anyone runs an optimization. Cheapest possible insurance: a `trials` table with `(strategy_lineage_id, params_hash, objective, ran_at, was_oos)` from the first backtest.
- **D3 requires the `TradeIntent` to carry the expected price and market snapshot.** Already in the Architecture_Plan schema (`marketSnapshotId`). Don't drop it as "unused" during implementation — it is the input to slippage attribution.
- **Copilot requires a notification channel.** Not currently an Active requirement. Without it the v1 success metric ("both builders run Copilot trades with real capital for a sustained period") is unreachable in practice — you cannot watch a screen for a sustained period.
- **D5 conflicts with in-place model retraining.** If the AI plane ever gains the ability to adjust a live strategy's parameters, divergence tracking becomes meaningless. Enforce via the registry: a parameter change is a new version that re-enters the state machine.
- **D4 depends on D5 plus Monte Carlo confidence bands.** Both must exist before decay detection has anything to compare against.
- **D6 has a data prerequisite that v1 will not meet.** Defer.

---

## MVP Definition

### Launch With (v1) — the Copilot loop with real capital

- [ ] Binance spot data ingestion with point-in-time correctness — every number downstream depends on it
- [ ] Same-engine backtest with real fees and slippage; reproduce a published backtest — the foundation acceptance test
- [ ] Restricted JSON DSL + validator — no unrestricted code in the trading path
- [ ] NL → `StrategySpec` compiler with validator-error feedback loop — the front door, and the loop is what takes pass rate from ~70% to ~95%
- [ ] Immutable versioned registry **with a trials table from day one** — the substrate for D1; unaddable later
- [ ] Paper trading with a real `PAPER_PASSED` gate (min duration + min trades) — closes the documented 3-day-paper-then-live failure
- [ ] Encrypted credential storage + in-product API-key setup with an automated withdrawals-disabled check — the onboarding bleed point
- [ ] Deterministic risk gate + `AgentMandate` — the authorization authority
- [ ] Copilot approval: exact executable preview, intent-hash bound, **itemized risk-check receipt (D10)**, price-band expiry
- [ ] **Notification channel for pending approvals (push and/or Telegram)** — currently missing from Active requirements
- [ ] Idempotent submission, `UNKNOWN` handling, continuous 3-way reconciliation, crash recovery — the invisible 80%
- [ ] Kill switches at strategy and account level; flatten separately gated
- [ ] Execution timeline + append-only audit
- [ ] Honest failure-state surfacing (UNKNOWN / stale / disconnected / reconciliation status)
- [ ] **D9 parameter sensitivity surface** — the cheapest legible validation feature; ship one differentiator in v1 so v1 has a point of view
- [ ] **D3 slippage attribution** — near-free once the ledger and intent snapshots exist, and it is the first thing you personally will want after your first live fill

### Add After Validation (v1.x)

- [ ] **D2 enforced OOS lockbox with a look budget** — trigger: the first time either builder catches themselves peeking at OOS
- [ ] **D1 trial-counted DSR / PBO** — trigger: >20 recorded trials on any strategy lineage. The trials table must exist from v1 regardless.
- [ ] Walk-forward analysis + Monte Carlo on trade ordering — trigger: D1 needs confidence bands
- [ ] **D5 live-vs-backtest divergence overlay** — trigger: first strategy live for 30+ days
- [ ] **D4 strategy decay detection** — trigger: after D5 and Monte Carlo bands exist
- [ ] TradingAgents research committee + **D8 evidence provenance** — trigger: after the spine is boring. Sequencing it late is correct: a slip here must never block live trading.
- [ ] **D7 explanation layer** — trigger: after D1 and D8; it explains artifacts that must exist first
- [ ] Artifact-scoped chat (this strategy, this backtest, this fill) — trigger: after the explanation layer

### Future Consideration (v2+)

- [ ] **D6 cross-strategy correlation** — defer: needs 3+ concurrent live strategies to produce any signal
- [ ] **D11 novelty / duplicate detection** — defer: needs a populated trial ledger
- [ ] PineScript / LEAN importer — defer: a compiler project solving an empty-library problem you don't have with two users
- [ ] Second venue, margin, perps — already Out of Scope; each venue is a month of edge cases
- [ ] Autopilot — already Out of Scope; Copilot must first teach you what the gate misses
- [ ] Billing — already Out of Scope; note the category anchor is $20–60/mo freemium and the AI-first entrants are free

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Same-engine backtest/paper/live | HIGH | HIGH (mostly bought via Nautilus) | P1 |
| Point-in-time correct data + quality monitors | HIGH (invisible) | HIGH | P1 |
| Restricted DSL + validator | HIGH | MEDIUM | P1 |
| NL → spec compiler with error feedback loop | HIGH | HIGH | P1 |
| Immutable registry **+ trials table** | MEDIUM now, HIGH later | MEDIUM | P1 (unaddable later) |
| Deterministic risk gate + mandate | HIGH | MEDIUM | P1 |
| Copilot approval + intent hash | HIGH | MEDIUM | P1 |
| **Notification channel for approvals** | HIGH | LOW | P1 (missing from reqs) |
| Idempotency, UNKNOWN, reconciliation, recovery | HIGH (invisible) | HIGH | P1 |
| Kill switches | HIGH | MEDIUM | P1 |
| Execution timeline + audit | MEDIUM | MEDIUM | P1 |
| Paper gate (min duration + trades) | HIGH | LOW | P1 |
| API-key setup with permission verification | MEDIUM | LOW | P1 |
| **D10 risk-check receipt** | MEDIUM | LOW | P1 (best trust-per-hour in the product) |
| **D9 parameter sensitivity surface** | HIGH | MEDIUM | P1 |
| **D3 slippage attribution** | HIGH | MEDIUM | P1/P2 |
| **D2 OOS lockbox** | HIGH | MEDIUM | P2 |
| **D1 trial-counted DSR/PBO** | HIGH | HIGH | P2 |
| Walk-forward + Monte Carlo | HIGH | HIGH | P2 |
| **D5 live-vs-backtest divergence** | HIGH | MEDIUM | P2 |
| **D4 decay detection** | HIGH | MEDIUM | P2 |
| **D8 evidence provenance** | MEDIUM | MEDIUM-HIGH | P2 |
| TradingAgents committee | MEDIUM | HIGH | P2 |
| **D7 explanation layer** | HIGH | HIGH | P2 |
| Artifact-scoped chat | MEDIUM | MEDIUM | P3 |
| **D6 cross-strategy correlation** | LOW at v1 scale, HIGH later | MEDIUM | P3 |
| **D11 novelty detection** | MEDIUM | MEDIUM | P3 |
| Strategy importer | LOW | HIGH | P3 |

---

## Competitor Feature Analysis

| Feature | Minara | QuantConnect | Cryptohopper / 3Commas | StrategyQuant X | Freqtrade / FreqAI | Our Approach |
|---------|--------|--------------|------------------------|-----------------|--------------------|--------------|
| NL → strategy | Yes, core product, free | No (C#/Python code) | No (presets, grid, DCA) | No (genetic generation) | No (Python code) | Yes → restricted JSON DSL, editable, validator feedback loop |
| Same engine backtest/paper/live | Claimed: "same engine that powers live execution" | Yes (LEAN) | Partial | N/A (desktop, exports to MT4/5) | Yes (dry-run shares strategy code) | Yes — Nautilus, and this is the non-negotiable core value |
| Cost model in backtest | Fees, funding, borrow, venue slippage curves | Yes, configurable fill models | Basic | Yes | **Fills at requested price, no slippage** if inside candle | Nautilus fill/fee models + Binance-specific slippage |
| Walk-forward / OOS | **Claimed**, plus regime slices and "automatic leakage detection" | **DIY** — documented pattern, user writes the optimizer | No | **Yes** — WFO + Walk-Forward Matrix with 3D views | No | Enforced OOS lockbox (D2) — a gate, not advice |
| Monte Carlo robustness | Not stated | No built-in | No | **Yes** — 2 engines, 9+ sim types, auto-reject | No | Trade-ordering MC feeding confidence bands for D4 |
| Overfitting evidence / trial count | Not stated | No | No | Auto-rejection, but no trial count | No | **D1 — DSR/PBO with the platform's own honest N. Unoccupied.** |
| Live-vs-backtest divergence | Not stated | **Yes — Live Reconciliation, automatic OOS backtest overlaid on every live deployment** | No | N/A | No | Same feature, stronger claim: literally one evaluator, so divergence is attributable to data/execution (D5) |
| Slippage attribution per trade | No | No | No | No | No | **D3 — unoccupied** |
| Strategy decay alerts | No | No | No | No | No | **D4 — unoccupied** |
| Cross-strategy correlation | Exposure/concentration map by asset, sector, chain | No | No | No | No | **D6 — unoccupied, but deferred to v2 (needs 3+ live strategies)** |
| Per-trade human approval | Copilot: "you approve before anything hits the book" | No | No | N/A | Telegram-based in community setups | Intent-hash bound, itemized risk-check receipt (D10), price-band expiry, out-of-band notification |
| Mandate scoping | Per-asset authorization; stops that can't be silently removed; drawdown flatten | Per-deployment | Per-bot | N/A | Per-config | `AgentMandate` — parity. Table stakes, not a differentiator. |
| Custody | Non-custodial (Hyperliquid perp wallet) | Non-custodial (user's broker) | Non-custodial (exchange API keys) | N/A | Non-custodial | Non-custodial, trade-only keys, withdrawals disabled |
| Venue / asset | Hyperliquid USDC perps (crypto + TradFi perps) | Equities, futures, forex, crypto | Many CEXs, spot | Forex/futures via MT4/5 | Many CEXs, spot + futures | **Binance spot only** |
| Marketplace / copy trading | No | Community strategies | **Yes — core growth engine** | Shared strategies | No | Never |
| Pricing | Strategy Studio free | Free tier; paid live deployment | Free → $16–108/mo | Desktop license | Open source | No billing in v1 |

---

## Sources

**Vendor primary documentation (read directly):**
- Minara Strategy Studio — https://minara.ai/product/strategy-studio (MEDIUM)
- Minara Autopilot — https://minara.ai/product/autopilot-trading (MEDIUM)
- QuantConnect Live Reconciliation — https://www.quantconnect.com/docs/v2/cloud-platform/live-trading/reconciliation (MEDIUM — corroborated by forum discussion #7454 and the Research Environment live-analysis docs)
- QuantConnect Walk-Forward Optimization — https://www.quantconnect.com/docs/v2/writing-algorithms/optimization/walk-forward-optimization (MEDIUM)
- TradingAgents — https://github.com/tauricresearch/tradingagents (MEDIUM — 102.6k stars, v0.4.0, simulated-exchange-only, research disclaimer quoted)
- StrategyQuant robustness tests / cross checks — https://strategyquant.com/doc/strategyquant/cross-checks-automated-strategy-robustness-tests/ (MEDIUM)
- Freqtrade / FreqAI — https://www.freqtrade.io/en/stable/freqai/ and backtesting docs (MEDIUM)
- Composer crypto discontinuation — https://www.composer.trade/crypto and /whats-new (MEDIUM)

**Regulatory:**
- CFTC, "AI Won't Turn Trading Bots into Money Machines" — https://www.cftc.gov/LearnAndProtect/AdvisoriesAndArticles/AITradingBots.html (MEDIUM)
- CFTC Customer Advisory on AI scams — https://www.cftc.gov/PressRoom/PressReleases/8854-24 (MEDIUM)
- SEC v. Fuller / Privvy Investments, May 2026 — CoinDesk, https://www.coindesk.com/business/2026/05/30/sec-sues-texas-man-over-usd12-3-million-alleged-crypto-scheme-built-on-fake-ai-trading-bots (MEDIUM)

**Academic:**
- Bailey & López de Prado, "The Deflated Sharpe Ratio" — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551 (MEDIUM)
- QuantCode-Bench, LLM executable strategy generation — https://arxiv.org/html/2604.15151 (MEDIUM — the 70–76% single-turn vs 95–98% agentic figures)
- "From Natural Language to Executable Option Strategies via LLMs" — https://arxiv.org/html/2603.16434 (LOW)

**Market/exchange landscape:**
- Coinbase for Agents — https://www.cnbc.com/2026/06/11/coinbase-launches-tool-to-let-ai-agents-manage-trading-and-payments.html (MEDIUM)
- OKX Agentic Wallet, Gemini Agentic Trading, exchange agent toolkits — KuCoin / BeInCrypto roundups (LOW — secondary aggregators, directionally consistent across three sources)

**Pricing and category surveys (LOW — vendor-adjacent review sites, cross-checked across 3+ sources for consistency):**
- Koinly, crypto.news, Altrady, mpost bot comparisons; therundown.ai and toolacademy.ai on Composer; backtestscore.com on TrendSpider

**Low-confidence, flagged in text:**
- "73% of automated crypto trading accounts fail within six months" — single vendor blog, uncorroborated. Directional only; do not cite externally.

---
*Feature research for: AI-first crypto quant trading platform (Binance spot, Copilot-approved live execution)*
*Researched: 2026-09-05*
