# MarketImmune — Frontier Agent Orchestration Plan

> Migrate the immune loop from a **static, hand-wired pipeline** to a
> **graph-based, stateful, dynamically-routed orchestrator** with reflection,
> first-class tools, parallelism, durable execution, streaming to the UI, and
> evals — without breaking the existing `LoopResult` contract or the deterministic
> demo. Built in slices; every slice ships green.

---

## 0. Design invariants (do not break these)

These are the properties the current core guarantees; the new architecture must
keep all of them:

1. **Deterministic by default.** Every agent runs end-to-end with no API keys
   and no network (`NullLLMClient`). The graph engine must too — an LLM is an
   optional collaborator, never a hard dependency.
2. **Framework-free core.** `marketimmune/agentic/` imports no vendor/agent SDK.
   The graph engine is ~150 lines of our own code (see §11 for the LangGraph
   alternative if we ever change our mind).
3. **Explicit traces, not magic.** Every node still emits `AgentRun` with
   `ToolCall` + `DecisionTrace`. Observability is additive.
4. **Honest about what is real.** Simulated vs. real data stays visible in traces.
5. **Backward-compatible output.** `ImmuneLoop.run(...)` still returns a
   `LoopResult`, and `GET /api/agentic/state/` keeps its shape, so the Geist UI
   and `AgenticService._persist` keep working untouched. Streaming is a *new*
   endpoint, not a breaking change.

---

## 1. Baseline (what exists today)

| Concern | Location |
|---|---|
| Orchestrator (static pipeline) | `marketimmune/agentic/loop.py` → `ImmuneLoop.run()` |
| Agent contract + value objects | `marketimmune/agentic/base.py` (`Agent`, `AgentRun`, `ToolCall`, `DecisionTrace`, `LLMClient`) |
| 8 role agents | `redteam / market_simulator / sentinel / investigator / policy / memory / trainer / judge .py` |
| LLM client (DeepSeek/Null) | `marketimmune/agentic/llm.py` → `build_default_llm()` |
| Bridge + persistence | `dashboard/services/agentic_service.py` → `run_once()` + `_persist()` (atomic) |
| HTTP surface | `dashboard/views/agentic.py` → `POST /api/agentic/run/`, `GET /api/agentic/state/`, `GET /api/agentic/llm-status/` |
| ORM | `ImmuneLoopRun`, `AgentRunRecord`, `AgentToolCallRecord`, `AgentDecisionTraceRecord`, `InvestigationCaseRecord`, `PolicyDecisionRecord`, `ScenarioProposalRecord`, `ImmuneMemoryEntry`, `ModelPromotionDecision` |
| Frontend viz | `frontend/src/components/agent.tsx` (`AgentOrchestrator`, `AgentDetailPanel`); screen `screens/AgenticLoop.tsx`; data via `data.loopState.loop.agent_runs` |

**Current control flow:** fixed order `RedTeam → Simulator → Sentinel →
Investigator → Policy → Memory → (Trainer → Judge)`, each output manually wired
into the next, early-`return` on any failure, run **synchronously**, persisted at
the end, fetched by the UI as one JSON document (no streaming).

**Limits:** no dynamic routing (always runs Investigator even with zero alerts);
no reflection/retry; no parallelism (one Investigator even for N alerts); no
tool-calling loop (tools are recorded post-hoc, not driven by the model); no
checkpoint/resume or human-in-the-loop; no live progress in the UI.

---

## 2. Target architecture

```
                    ┌─────────────────────────────────────────────┐
                    │              Graph engine (graph.py)         │
   build_default_llm│   nodes wrap agents · conditional edges ·    │
        │           │   cycles (reflection) · parallel fan-out ·   │
        ▼           │   per-node tracing + streaming hooks         │
  ImmuneLoop  ──────┤                                              │
 (graph DEFINITION) │   reads/writes one typed LoopState (state.py)│
                    └───────────────┬──────────────────────────────┘
                                    │ emits events + final LoopResult
        ┌───────────────────────────┼───────────────────────────────┐
        ▼                           ▼                                ▼
 AgenticService.run_stream     checkpoint LoopState           same _persist()
 (SSE: node/tool events)       after each node (resume/HITL)  (unchanged tables)
        │
        ▼
 GET /api/agentic/stream  ──►  provider.tsx EventSource  ──►  AgentOrchestrator
                                                              (nodes light up live)
```

New modules, all under `marketimmune/agentic/`:

| New file | Responsibility |
|---|---|
| `state.py` | `LoopState` — the typed **blackboard** every node reads/writes; serializable for checkpoint + streaming |
| `graph.py` | The **engine**: `Node`, conditional `Edge`s, cycles, parallel, retries, tracing/stream hooks, `Graph.run(state)` (sync) + `arun` (async) |
| `supervisor.py` | A **router/planner** node that picks the next agent from `LoopState` (dynamic path) |
| `critic.py` | **Reflection** node (or reuse `judge.py`) for bounded self-critique/retry |
| `tools/__init__.py`, `tools/registry.py` | First-class **tool registry** (`@tool` + JSON schema) and a ReAct dispatch loop added to `base.py` |
| `guards.py` | Input/output **guardrails** wrappers (validation, PII/῾honesty checks, budget enforcement) |

`loop.py` is rewritten to *define* the graph and run it, returning the same
`LoopResult`. No agent's internal logic changes in Phase 1–2.

---

## 3. `state.py` — the shared blackboard

```python
@dataclass
class LoopState:
    # ---- inputs ----
    difficulty: str = "medium"
    tick_limit: int = 60
    existing_memories: tuple[ImmuneMemory, ...] = ()
    enable_self_improvement: bool = True
    retrain_pending: bool = False

    # ---- working artifacts (filled as nodes run) ----
    proposal: ScenarioProposal | None = None
    plan: SimulationPlan | None = None
    alerts: tuple[SentinelAlert, ...] = ()
    cases: tuple[InvestigationCase, ...] = ()
    decisions: tuple[PolicyDecision, ...] = ()
    new_memories: tuple[ImmuneMemory, ...] = ()
    drift_report: DriftReport | None = None
    training_job: TrainingJob | None = None
    verdict: JudgeVerdict | None = None
    aggregate_posture: str = "no_action"

    # ---- control / observability ----
    runs: list[AgentRun] = field(default_factory=list)   # accumulates every AgentRun
    budget: dict[str, int] = field(default_factory=dict) # per-node retry caps
    visited: list[str] = field(default_factory=list)     # node history (loop guard)
    events: list[GraphEvent] = field(default_factory=list)
    halt_reason: str | None = None                       # set to short-circuit

    def to_result(self) -> LoopResult: ...   # compat shim → existing LoopResult
    def snapshot(self) -> dict: ...          # JSON-serializable, for checkpoint/stream
```

Rules: nodes **append** to `runs`/`events`, never mutate prior entries; a node may
set `halt_reason` to stop the graph early; `to_result()` keeps the public output
identical so `_persist` is untouched.

---

## 4. `graph.py` — the engine (framework-free)

```python
NodeFn = Callable[[LoopState], LoopState]          # usually wraps Agent.run

@dataclass
class Node:
    name: str
    fn: NodeFn
    retries: int = 0                                # bounded reflection/retry
    parallel_group: str | None = None              # nodes sharing a group fan out

@dataclass
class Graph:
    nodes: dict[str, Node]
    edges: dict[str, list[Edge]]                   # Edge = (predicate, target)
    entry: str

    def run(self, state: LoopState, *, on_event=None) -> LoopState: ...
    async def arun(self, state, *, on_event=None) -> LoopState: ...
```

- **Conditional edges:** each `Edge` carries a `predicate(state) -> bool`; the
  engine takes the first matching edge. This is where "skip Investigator when
  `state.alerts == ()`" lives.
- **Cycles + retries:** an edge may point back to an earlier node; `Node.retries`
  + `state.budget` + `state.visited` enforce a hard cap (no infinite loops).
- **Parallel:** nodes in the same `parallel_group` run concurrently in `arun`
  (e.g., one Investigator per alert) and join before the next node.
- **Tracing/streaming:** the engine calls `on_event` with `node_start`,
  `tool_call`, `node_finish`, `route` — this is the single hook that powers both
  the SSE stream and OpenTelemetry-style spans.

`ImmuneLoop` becomes:

```python
def build_graph(self) -> Graph:        # declarative wiring, was the imperative body
    g = GraphBuilder(entry="redteam")
    g.node("redteam", wrap(self.redteam, ...))
    ...
    g.edge("sentinel", to="investigator", when=lambda s: bool(s.alerts))
    g.edge("sentinel", to="memory",       when=lambda s: not s.alerts)   # dynamic skip
    g.edge("investigator", to="critic")                                   # reflection
    g.edge("critic", to="investigator", when=low_confidence, max_visits=2)
    g.edge("critic", to="policy",        when=ok)
    ...
    return g.build()

def run(self, **kwargs) -> LoopResult:
    state = LoopState(**kwargs)
    state = self.build_graph().run(state)
    return state.to_result()           # ← unchanged public contract
```

---

## 5. Dynamic routing, reflection, tools

- **Supervisor (`supervisor.py`):** an optional planner node that, instead of
  static edges, asks `state` (or the LLM, when present) "what next?" and returns a
  node name. Start with rule-based routing (severity/alert-count thresholds);
  upgrade to LLM function-calling once tools land. Deterministic fallback required.
- **Reflection (`critic.py`):** wraps/reuses `judge.py`. After Investigator, the
  critic scores case confidence; if below threshold and budget remains, route back
  for another evidence pass. Bounded by `Node.retries` + `state.budget`.
- **Tools (`tools/`):** a registry of typed callables —
  `@tool def query_features(...) -> ...` with an auto-generated JSON schema. Add a
  ReAct loop to `base.py`: when an `llm` is present, the agent gets the tool
  schemas, the model emits tool calls, the loop dispatches them (recording the
  same `ToolCall` objects we already persist) until the model returns a final
  answer. When `llm` is Null, agents keep their current deterministic path. This
  turns "post-hoc tool logging" into real model-driven tool use **without changing
  the persisted shape**.

---

## 6. Durable execution + human-in-the-loop

- **Checkpointing:** add `AgenticCheckpoint` (or a `state_json` + `status` field on
  `ImmuneLoopRun`) written by `AgenticService` after each `node_finish`. Lets a run
  resume after a crash and lets the UI inspect mid-run state.
- **Interrupts (HITL):** mark `policy` (control enactment) as an interrupt point;
  the engine halts with `halt_reason="awaiting_approval"`, persists the checkpoint,
  and a new `POST /api/agentic/resume/{loop_id}` continues the graph after a human
  approves. Off by default (keeps the one-click demo intact).

---

## 7. Streaming to the UI

**Backend** (`dashboard/views/agentic.py`):
- New `GET /api/agentic/stream/` (Server-Sent Events). `AgenticService.run_stream`
  runs the graph with an `on_event` callback that yields SSE frames:
  ```
  event: node_start   data: {"node":"investigator","i":3,"of":8,"ts":...}
  event: tool_call    data: {"node":"investigator","tool":"query_features",...}
  event: node_finish  data: {"node":"investigator","success":true,"duration_ms":...}
  event: route        data: {"from":"sentinel","to":"memory","why":"no_alerts"}
  event: done         data: {"loop_id":"loop_...", ...summary...}
  ```
- Keep `POST /api/agentic/run/` (synchronous) as the no-stream fallback.

**Frontend:**
- `data/provider.tsx`: add `runLoopStreaming()` that opens an `EventSource`,
  updates a new `liveRun` slice on each event, and falls back to the existing
  one-shot `runLoop()` if SSE 404s (offline/fixtures stay supported).
- `components/agent.tsx` (`AgentOrchestrator`): drive node status from the live
  event stream (nodes light up green/amber as `node_start`/`node_finish` arrive,
  tool calls stream into `AgentDetailPanel`), instead of rendering only the final
  snapshot. Render the **graph** (with the dynamic edges actually taken) rather
  than a fixed ring.
- `types.ts`: add `GraphEvent`, `LiveRunState`. The `simEngine` gains a scripted
  event stream so the live view also works fully offline.

---

## 8. Phased rollout (each phase is shippable + tests green)

| Phase | Scope | Files | Done when |
|---|---|---|---|
| **P1 — State + engine (behavior-identical)** | Extract `LoopState`; add `graph.py`; re-express the *existing* pipeline as a graph; `run()` returns the same `LoopResult` | `state.py`, `graph.py`, `loop.py` | All existing agentic tests pass unchanged; golden-loop snapshot identical |
| **P2 — Dynamic routing** | Add conditional edges (skip Investigator/Policy when no alerts; posture short-circuits) | `loop.py`, `graph.py` | New routing tests; no-alert loop skips correctly; snapshot updated |
| **P3 — Reflection** | `critic.py` cycle with bounded retries on low-confidence cases | `critic.py`, `loop.py` | Retry-cap test; confidence lift measured on a fixture |
| **P4 — Streaming UI** | SSE endpoint + `AgenticService.run_stream`; `provider.tsx` EventSource; live `AgentOrchestrator` | `views/agentic.py`, `urls.py`, `agentic_service.py`, `provider.tsx`, `agent.tsx`, `types.ts`, `simEngine.ts` | Nodes light up live in dev; offline fixtures still animate; `tsc`+`build` green |
| **P5 — Tools (ReAct)** | Tool registry + dispatch loop in `base.py`; migrate Investigator/Sentinel to tool-calling when LLM present | `tools/`, `base.py`, `investigator.py`, `sentinel.py` | Tool-call test (LLM mocked); deterministic path unchanged |
| **P6 — Durability + HITL** | Checkpoint model + resume endpoint + Policy interrupt | `models.py`, migration, `agentic_service.py`, `views/agentic.py` | Crash-resume test; approval gate test; default demo unaffected |
| **P7 — Parallelism** | Fan-out Investigator per alert via `arun`; join | `graph.py`, `loop.py`, `agentic_service.py` | Concurrency test; latency drop on multi-alert fixture |
| **P8 — Evals as a gate** | Wire `aegisbench` + Judge as a promotion gate; guardrails wrappers | `guards.py`, `aegisbench/*`, `judge.py` | Eval suite runs in CI; promotion blocked on regression |

**Land P1 first** — it's pure refactor, fully testable, and unlocks everything
else. P2 + P4 give the most visible payoff (smart routing + live UI).

---

## 9. Testing & evaluation

- **Engine unit tests:** linear, conditional skip, cycle-with-cap (no infinite
  loop), parallel join, early `halt_reason`.
- **Golden loop snapshot:** freeze `LoopResult` for a fixed seed; P1 must match
  byte-for-byte; later phases update the snapshot deliberately.
- **Determinism test:** same seed + `NullLLMClient` → identical output across runs.
- **Per-node tests:** unchanged agent tests keep passing (the contract is stable).
- **Streaming test:** event sequence assertions; SSE→fixtures fallback.
- **Evals (`aegisbench`):** PR-AUC / markout-lift gate stays honest under
  purged/embargoed walk-forward; promotion blocked on regression.

---

## 10. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Infinite reflection loops | `Node.retries` + `state.budget` + `visited` hard caps; engine raises on exceed |
| LLM nondeterminism breaks the demo | LLM stays optional; `NullLLMClient` deterministic path is the default and is tested |
| Breaking the UI / persistence | `to_result()` keeps `LoopResult` + `/state` shape identical; streaming is additive |
| Async complexity | Keep `run()` sync; add `arun()` only for P7; SSE uses a thread/async view, not a rewrite |
| Scope creep | Strict phase gates; P1 is a no-behavior-change refactor before any new capability |
| Cost/latency with tools | Budget per node; tools only engage when `MARKETIMMUNE_USE_LLM` is on |

---

## 11. Framework decision

**Recommended: build the ~150-line engine in `graph.py`.** It preserves the
"framework-free, deterministic-by-default, honest-traces" discipline the core is
designed around, keeps zero new runtime deps, and the graph we need (8 nodes, a
few conditional edges, one reflection cycle, optional fan-out) is small.

**Alternative: LangGraph.** Mature graph/checkpoint/HITL primitives and streaming
out of the box — but it pulls the LangChain orbit into a core that deliberately
avoids vendor SDKs, and its nondeterminism/async model fights the deterministic
demo. Reach for it only if the graph grows large or we want its persistence/HITL
tooling for free. The `state.py`/`Node`/`Edge` design above maps 1:1 onto
LangGraph nodes/edges, so switching later is mechanical.

---

## 12. Decisions needed from you

1. **Engine:** in-repo `graph.py` (recommended) or LangGraph?
2. **Streaming transport:** SSE (simpler, recommended) or WebSocket (bidirectional, needed only if we add live human steering)?
3. **HITL:** do you want the Policy approval gate now (P6) or leave it off until there's a real control-enactment path?
4. **Scope of slice 1:** just P1 (refactor to graph, no behavior change), or P1+P2+P4 together (graph + smart routing + live UI) as the first visible milestone?
```
