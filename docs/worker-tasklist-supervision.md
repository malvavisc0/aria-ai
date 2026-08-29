# Plan — Worker TaskList Supervision

**Date:** 2026-08-14 · **Status:** proposed, revised 2026-08-15 · **Scope:** `worker spawn` now **requires** `steps` and always creates a plan; the worker's plan renders live as a Chainlit `TaskList`, and Aria supervises execution without coupling the tracking logic to the web UI (future CLI reuse). No backward compatibility for unsupervised spawns.

> **This document is the single source of truth for the feature.** Every
> code reference (paths, signatures, statuses, line behaviors) below was
> verified against the repository and the installed dependencies on
> 2026-08-15. Implement from this doc, not from memory or older summaries.
> When you diverge from it, update it.

## Revision 2026-08-15 — pre-implementation verification

Every code reference was re-verified against the repository and the installed
chainlit 2.11.1. Changes from the 2026-08-14 draft (details in the referenced
sections):

1. **Persistence mechanism corrected** (§1, §4.3, §5.4, §10). The draft
   claimed `TaskList` rows persist in the `elements` table on `send()`. That
   is wrong: `TaskList.send()` hard-codes `for_id=""` (`element.py:351-353`)
   and both `create_element` implementations skip elements whose `for_id` is
   falsy (chainlit `data/sql_alchemy.py:588-589`; Aria override
   `src/aria/db/layer.py:435-436`), so a plain `cl.TaskList` writes **no row**
   and requirement 2 (visible after reload/resume) was unmet. Fix: the
   `PersistedTaskList` subclass in §5.4 sends with the spawning message id —
   rows upsert per re-send (`layer.py:413-417`) — and resume re-arming reuses
   the persisted row's element id + `forId` (§4.3.1) so there is one panel
   per worker across sessions.
2. **`worker()` signature** (§5.1). `steps: list[str] | None = None` — the
   non-spawn actions take no steps, so a hard-required parameter is not
   possible in Python; required-ness is enforced at spawn (`missing_steps` on
   `None` **or** empty). No spawn proceeds without steps. Also documented:
   `src/aria/cli/worker/__init__.py` holds an orphaned, unregistered duplicate
   `spawn` (no `aria worker` CLI command exists) — dead weight, left
   untouched; `tools/worker/functions._spawn` is the only live spawn path.
 3. **`settle_unfinished_step`** (§5.2) — shared helper
   (`results.py`) fails the first unfinished step; no "completed" promotion
   (a worker is never completed on subprocess exit alone). Crash-path safety
   re-scoped (planner tables guaranteed present because the web process
   seeded the plan before `Popen`, §7).
4. **`snapshot.py` reads `WORKERS_DIR` at call time** (§5.3) so the §8.3
   module-attribute patch actually lands (an import-time binding would make
   the patch — and the tests behind it — vacuous).
5. **`worker.md` line 20 updated** (§5.7) — the "`plan` — Create before any
   work." bullet contradicted the no-reauthor flow. Regression-test literal
   corrected to the actual current wording; template path fixed to
   `src/aria/agents/instructions/_worker_plan_section.py`.
6. **Header mapping pinned** (§6) — zombie → `"Failed"`, running + all
   steps done → `"Done"`, zero steps → `"Ready"`; §8.5 pins the per-state
   values.
7. **`ensure_watching` grows an `elements` kwarg** (§5.5/§5.6) carrying the
   thread's persisted element rows for the resume row-reuse lookup;
   `cancel_all_watchers()` runs first in `on_chat_end_handler` (before the
   `memory is None` early-return). The draft's §5.5 re-arm bullet (terminal
   workers "get one final render then exit") contradicted §4.3.6 and is
   corrected.
8. **Edge cases / tests / sequencing** (§7, §8, §9) — row-loss fallback on
   resume, `steps=None` rejection, row-reuse and header-mapping tests, and a
   live-validation step for reload-while-running (single panel) and
   reload-after-completion (persisted row).

---

## 1. Confirmation

### Chainlit `TaskList` (verified against installed chainlit **2.11.1**, `chainlit/element.py:309-371`)

- `cl.TaskList` (subclass of `Element`, `type="tasklist"`, `element.py:333-340`) is a **dedicated side panel** (desktop), *not* message-attached; `updatable=True` is set in `TaskList.__post_init__` (`element.py:341-343`) so every change re-sends it. `TaskList.update()` aliases `send()` (`element.py:347-349`).
- `TaskList.send()` runs `preprocess_content()` then `super().send(for_id="")` (`element.py:351-353`) — the plain class hard-codes an **empty** element-level `for_id` (see the pivotal persistence fact below). In-chat navigation is per-`Task`: `cl.Task(title, status, forId)` — `title: str`; `status: TaskStatus` (`READY | RUNNING | FAILED | DONE`, lowercase values `"ready"|"running"|"failed"|"done"`, `element.py:309-313`); `forId: str | None` links a single task to a message id (`element.py:316-330`).
- `TaskList.tasks: list[Task]` is excluded from dataclass serialization (`Field(exclude=True)`); `preprocess_content` builds the send payload — the JSON `{status, tasks[{title, status.value, forId}]}` — onto `self.content` (`element.py:355-370`).
- `TaskList.status: str = "Ready"` — free-form short string shown in the panel header.
- **Element wiring and persistence path** (verified against `element.py` and both installed data layers). `Element` fields: per-instance `id` (uuid default-factory, assignable before the first send, `element.py:78`) and `for_id` (`element.py:94`). `Element.send(for_id)` sets `self.for_id`, then `_create` (`element.py:206-226`) does two things: (a) fires `data_layer.create_element(self)` **fire-and-forget** (`asyncio.create_task`, not awaited), and (b) *awaits* `context.session.persist_file(...)` and sets `self.chainlit_key`, so `send()`'s no-url/no-chainlitKey raise (`element.py:249-250`) never fires. `to_dict()` carries the row columns (camelCase: `id`, `threadId`, `type`, `name`, `forId`, `objectKey`, `url`, `chainlitKey`, ...) with **no `content` field** (`element.py:107-124`) — the JSON bytes live in the storage provider, and `create_element` is where the row is written.
- **`create_element` guards on `for_id` — the pivotal fact.** Chainlit base: `if not element.for_id: return` (`chainlit/data/sql_alchemy.py:588-589`); Aria's `SQLiteSQLAlchemyDataLayer.create_element` override carries the **same** guard (`src/aria/db/layer.py:435-436`, its only deviation resolving the user from the session context). A plain `cl.TaskList` (always `for_id=""`) therefore **writes no `elements` row at all**: live rendering works via the websocket `send_element` event (`element.py:252`), but the element is absent from the thread's resume data (`SELECT * FROM elements WHERE "threadId" = :id`, `sql_alchemy.py:303` — no type filter). When `create_element` *does* run (non-empty `for_id`), Aria's override uploads the content to `{user_id}/{element.id}/{name}` with `overwrite=True` (`layer.py:383,446-449`) and upserts the row `ON CONFLICT (id) DO UPDATE` (`layer.py:413-417`) — one row per element id, refreshed by every re-send.
- **Durable tasklists therefore need a non-empty `for_id`.** The `PersistedTaskList` subclass in §5.4 sends with the spawning message id, so the row exists, survives reload, and is re-upserted on every render. `name` carries the worker id so resume can match row → worker and reuse the row's element id + `forId` (§4.3.1); resume data is `ThreadDict.elements` (`chainlit/types.py:49-51`, camelCase row keys).

So: Aria can show a live **and reload-durable** task list, and the natural model is *one `PersistedTaskList` per supervised worker, Tasks = plan steps, the `elements` row keyed by the element id*.

### Our worker architecture (verified in code)

- `worker(action="spawn")` (`src/aria/tools/worker/functions.py:87-95`) dispatches to `_spawn` (`functions.py:127-222`), which launches an **OS process** (`python -m aria.cli.worker._runner …`, `functions.py:162-188`) and writes an audit JSON (`Data.path / "workers" / f"{wid}.json"` = `~/.aria/workers/<wid>.json`, `functions.py:26,34`; fields: `worker_id`, `pid`, `status`, `created_at`, `completed_at`, `thread_id`, `prompt`, `reason`, `expected_results`, `extra_instructions`, `output_dir`, `result`, `error`, `tool_calls`, `functions.py:193-208`).
- The audit `thread_id` is stored at spawn (`functions.py:199`) but is **not** passed to the runner subprocess — the runner cmd (`functions.py:162-178`) carries only `--worker-id --prompt --output-dir --reason --expected [--instructions]`.
- The worker runs a `WorkerAgent` (`src/aria/agents/worker.py`) with `plan`, `scratchpad`, shell, file tools, and a restricted `worker_ax` dispatcher; it has no reasoning tool, persistent memory, or worker delegation.
- The planner (`src/aria/tools/planner/`) persists plans and steps in the **shared tools SQLite** (`~/.aria/db/tools.db`, `database.py`, `get_tools_database()`). Tables `plans` / `plan_steps` (`models.py:11-77`); `PlanModel.is_active` gates reads; `PlanStepModel.status` is a free `String(20)`; `StepStatus` enum (`functions.py:24-30`): `pending / in_progress / completed / failed`. Step ids in the plan tool are `uuid.uuid4().hex[:8]` (`functions.py:196`). The DB is written per tool call and is the only live channel between the two processes.
- `PlannerDatabase` is a process-local singleton (`__new__`, `database.py:20-24`); each process (web + worker) holds its own engine to the same `tools.db` file. `save_plan(self, plan_id, agent_id, task, steps: list[dict], created_at: str)` expects each step dict to have keys `id`, `description`, and optionally `status`/`result`/`created_at`/`updated_at` (`database.py:39-75`).
- Today a worker gets a free-form *prompt*, not a plan, and its progress is invisible until completion (`tool_calls` is written into the audit only at the end, `_record_completion`, `_runner.py:67-80`). This plan **removes** that unsupervised mode: `spawn` will require `steps`, always seed a plan, and the runner will always receive `--plan-id`.
- **Spawn paths.** `tools/worker/functions._spawn` (reached via `ax worker spawn`) is the primary spawn path. The `ax` CLI also exposes `src/aria/cli/worker/__init__.py`; it delegates to the same worker function and requires `prompt`, `reason`, `expected`, and ordered `steps`. Both paths reject worker-to-worker spawning.

Everything needed exists; the feature is wiring: *require `steps` at spawn, seed the plan, let the worker self-report through the planner DB, render that DB live.*

---

## 2. Requirements

1. `spawn` **requires** `steps` (a non-empty `list[str]`) — there is no unsupervised mode. The worker executes steps in order and reports progress per step. Existing callers must supply `steps`; no backward-compatibility shims are kept.
2. The Chainlit UI shows one `TaskList` per worker, live-updating, including after chat reload/resume.
3. **No `chainlit` imports outside `aria.web`** — the supervision core must be UI-agnostic so a future CLI adapter can consume the same snapshots.
4. Terminal workers write a validated `result.json` manifest beside `result.md`; the manifest is authoritative for summary, terminal status, step counts, and report metadata.

---

## 3. Non-goals

- No changes to the `ax` dispatcher contract beyond `steps` being a required kwarg that survives `_strip_unknown_kwargs` (it will, because the kwarg is added to the `worker()` signature — `dispatcher.py:519-541` keeps any kwarg whose name is a declared parameter).
- No nesting into llama_index's in-process sub-agents; this is about the OS-process `worker` tool only.
- No CLI adapter implementation now — only the design point that makes it possible.

---

## 4. Architecture

```
┌─ Aria main agent (web process) ───────────────────────────────────┐
│ ax ▸ worker(spawn, prompt, expected, steps=[…], thread_id)        │
│   └─ workers/functions._spawn                                     │
│        ├─ plan: PlannerDatabase().save_plan(agent_id=wid, …)      │
│        ├─ audit JSON gains plan_id (always)                      │
│        └─ Popen: _runner --worker-id W --plan-id P … ─────────┐   │
│                                                                │   │
│ aria.supervision (UI-AGNOSTIC core — no chainlit imports)      │   │
│   snapshot.py: WorkerView ← plans table + audit JSON           │   │
│   watch.py:    async generator (poll, yield-on-change)          │   │
│                                                                │   │
│ aria.web (chainlit ADAPTER — only chainlit-aware part)         │   │
 │   tasklist.py:   WorkerView → PersistedTaskList render         │   │
 │   supervisor.py: per-(thread,wid) watcher lifecycle            │   │
 │                (resume re-uses row element id + forId)         │   │
│   message_pipeline/hooks: trigger after turn & on resume       │   │
│   └──────────────────────────────────────────┬──────────────────┘   │
└─────────────────────────────────────────────┼──────────────────┘
                                  ▲ shared SQLite │
                                  │ (plans/plan_steps, ~/.aria/db/tools.db)
┌─ worker process ───────────────┴────────────────────────────────┐
│ _runner (plan section in _build_prompt: execute steps in order; │
│          plan(update) in_progress→completed each)                │
│ WorkerAgent (plan tool present via CORE) → writes step statuses   │
│ settle_unfinished_step(plan_id, …) on failure/zombie             │
└──────────────────────────────────────────────────────────────────┘

future: aria CLI adapter ── reads the same WorkerView snapshots ──▶ text table
```

**Why the planner DB and not the audit JSON for step progress:** the audit file is written only at start (`_update_audit` sets `started_at`, `_runner.py:103`) and completion (`_record_completion`/`_record_failure`); the planner DB is written *per tool call*. It is the only live channel that exists today, and the worker already owns the tool that drives it. The audit JSON remains the channel for worker-level `status` (`running / completed / partial / failed / cancelled / zombie`).

---

## 4.1 End-to-end workflow

This is the human-facing flow the feature produces. It names **who** owns each phase and what crosses the process boundary.

```
User ──prompt──▶ Aria (web process)
                  │
                  │ 1. GATHER: research/clarify until the goal is unambiguous
                  │    (read-only tools, ≤15 calls; ask one question if high-stakes+ambiguous)
                  │
                  │ 2. DECOMPOSE: write an ordered, measurable plan
                  │    - each step = one concrete action with a verifiable outcome
                  │    - last step is the success criterion (deliverable path + acceptance check)
                  │    - hold the plan in reasoning/scratchpad, NOT the plan tool
                  │
                  │ 3. SPAWN:
                  │    ax(worker, spawn, args={
                  │        prompt, expected, steps=[...], thread_id
                  │    })
                  │    └─ _spawn seeds the plan in the planner DB (agent_id=wid)
                  │    └─ audit JSON gains plan_id; runner gets --plan-id
                  │    └─ Aria's turn ENDS (report worker_id, stop)
                  │
                  ▼ ┌────────────── process boundary ──────────────┐
                  │ ▼ Worker process                                │
                  │   _build_prompt prepends a Plan section telling │
                  │   the worker: execute steps IN ORDER,           │
                  │   plan(update) in_progress→completed per step.  │
                  │   WorkerAgent owns the plan tool → writes the    │
                  │   planner DB on every step transition.          │
                  │   On exit: settle_unfinished_step + manifest.   │
                  │ └───────────────────────────────────────────────┘
                  │
                  ▼ ┌────────────── web process (async) ───────────┐
                  │ watch_worker(wid) polls the planner DB + audit  │
                  │ every 1.5s; on change, WorkerTaskList.render    │
                  │ re-sends the PersistedTaskList (side panel;    │
                  │ its elements row is upserted per re-send).     │
                  │ Stops when worker_status is terminal.          │
                  │ └───────────────────────────────────────────────┘
                  │
                  ▼ Aria is NOT re-engaged automatically (see §4.2 #2, §4.3)
                  │
User ──next prompt──▶ Aria reads result.md / audit, evaluates, replies.
```

**Key points the diagram encodes:**

1. **Aria authors the plan content, the worker does not.** Aria holds the decomposition in `reasoning`/`scratchpad` and passes `steps` (a `list[str]`) at spawn. `_spawn` creates the DB plan and hands the worker a **reference** (`--plan-id`). The worker **executes and updates** the existing plan; it does not author one (this reverses today's `worker.md` "Start with plan" instruction — see §5.7). Aria never calls the `plan` tool herself (§4.2 #1).
2. **Aria's turn ends at spawn.** No blocking wait; the live `TaskList` is driven by the background watcher (§4.3), not by Aria tool calls. Aria is never re-engaged at completion.
3. **The worker self-reports per step** via the `plan` tool it already has (`CORE` registry). The only new runner behavior is the Plan-section prompt injection and `settle_unfinished_step` + manifest write at exit.
4. **Evaluation is user-triggered, not automatic.** When the user next prompts Aria, she reads `result.md` (or the audit) and evaluates in her own voice — per `aria.md:51` ("Present the conclusion in your own natural voice").

---

## 4.2 Design decisions

These are committed. Implement exactly as described; do not re-introduce the rejected behaviors.

1. **Aria passes `steps` content; she does not call the `plan` tool.** Aria passes `steps: list[str]` at spawn; `_spawn` creates the DB plan row (`agent_id=wid`) and passes `--plan-id` to the worker. Aria holds her decomposition in `reasoning`/`scratchpad`. One plan, one owner (`wid`), one process boundary.
2. **Monitoring is a background watcher; Aria is never re-engaged at completion.** A per-worker `asyncio` task polls the planner DB + audit JSON every 1.5 s and re-sends the `cl.TaskList` on change. Aria's turn ends at spawn (`aria.md:74`). When the worker finishes, the watcher renders the terminal `TaskList` and exits — nothing wakes Aria. Evaluation happens on the user's next prompt, where Aria reads `result.md` / the audit (`aria.md:51-52`). There is no completion callback, no synthetic user message, no turn re-injection.
3. **The worker executes a seeded plan; it does not author one.** The plan is created by `_spawn`; the runner injects the plan id + agent id into the worker's prompt; the worker calls `plan(get)`/`plan(update)` only. This reverses today's `worker.md` "Start with plan. Create…" instruction (§5.7).

---

## 4.3 Silent-watcher monitoring — implementation walkthrough

This is the full lifecycle of one worker's monitoring, the chosen model. It is the normative description of `§5.3`–`§5.6`; if prose and code snippets disagree, the code snippets win.

**Lifecycle phases (one worker, one thread):**

```
spawn turn (Aria)            resume turn (user reopens thread)
   │                              │
   ▼                              ▼
ensure_watching ──► arm watcher   ensure_watching ──► arm watcher
   │                              │ (only for still-running workers)
   ▼                              ▼
[watcher task runs in background, independent of Aria's turns]
   │
   ├── poll 1: immediate yield ──► WorkerTaskList.render(view₁) ──► cl.TaskList.send()
   ├── poll 2..N-1: yield only on (steps, worker_status) change ──► render ──► send()
   └── poll N: terminal worker_status ──► render(final view) ──► send() ──► task exits
        │
        ▼
    PersistedTaskList's elements row (type="tasklist", id=element id) is
    upserted on every re-send; reload/resume re-renders the final state from it.
   Aria's NEXT user-prompted turn reads result.md/audit and evaluates.
```

**Per-phase detail:**

1. **Arming (`ensure_watching`, §5.5).** Called from `message_pipeline._stream_and_finalize` after `output.send()` (§5.6) with `for_id=output.id`, and from `on_chat_resume_handler` (§5.6) with `elements=thread.get("elements")`. It:
   - Calls `snapshot.find_supervised_workers(thread_id)` → list of running worker ids for this thread. Fast no-op (one directory scan, no DB hit) when empty.
    - Reads `cl.user_session.get("_supervision_watchers")` (a `dict[tuple[str,str], asyncio.Task]`); for any supervised worker not already in that dict, resolves its persistence identity (below) and creates `WorkerTaskList(worker_id, for_id=…, element_id=…)`; launches `asyncio.create_task(_run_watch(wid, renderer))`. Stores the task back on `cl.user_session`. Idempotent: duplicate calls for the same `(thread_id, wid)` do not start a second watcher, including for finished workers whose entry lingers as a completed task (§4.3.4). The watcher task is created inside a Chainlit handler, so it inherits the `context.session` ContextVar snapshot — `PersistedTaskList.send` → `persist_file`/`send_element` resolve the right session on every poll.
    - **Persistence identity is captured once at arm time** (§1, §5.4). The element is built with `name=worker_id` (row ↔ worker key) and `for_id=<message id>`:
      - **Spawn turn:** `for_id=output.id` (§5.6); the element gets a fresh uuid id, and the first render's `create_element` writes the `elements` row.
      - **Resume:** `ensure_watching` receives the thread's persisted elements (`thread["elements"]`, §5.6); for each re-armed worker it looks up the row with `type=="tasklist"` and `name==worker_id` and **reuses the row's element `id` and `forId`** for the new element instance. Reusing the id keeps *one panel per worker across sessions*: the reload already rendered the persisted row as a panel, and the re-arm's first (immediate) `send_element` carries the same element id, so the frontend refreshes that panel in place (the same-id merge assumption is a live-validation item — §10). Reusing `forId` keeps the in-chat navigation chips. Already-terminal workers are touched by no watcher; their panels stay the persisted rows, rendered by the frontend from the row's storage data (§1), unchanged by the re-arm.
      - **Row-miss fallback** (the spawn session's fire-and-forget `create_element` lost a shutdown race and no row exists): the re-armed element gets a fresh id and `for_id=None` → `""` → the row is **not** (re-)written; the panel is live-only for this session (accepted — §7).

2. **Polling (`watch_worker`, §5.3).** The watcher task iterates the async generator:
   - First yield is **immediate** (no `asyncio.sleep` first) so the panel appears in the spawn turn, not 1.5 s later.
   - Each subsequent iteration: `await asyncio.sleep(interval)` (default 1.5 s), then `snapshot.load_worker_view(worker_id)`. The generator yields a new `WorkerView` only when it differs from the previous one (frozen-dataclass `!=` compares `tuple[StepView]` element-wise). Unchanged views are swallowed; transient load errors are caught and swallowed (next poll retries) — the generator never raises.
   - The generator terminates after yielding the **final** view once, when `worker_status` ∈ `{completed, partial, failed, cancelled, zombie}`. No total poll budget: a worker may run for hours; liveness comes from the terminal status (audit JSON rewrite by `_record_completion`/`_record_failure`, or `is_process_running`→false for zombies).

3. **Rendering (`WorkerTaskList.render`, §5.4).** Per yielded view:
    - Skip if `view == self._last` (frozen-dataclass equality) — no spurious `send()`.
    - Apply the §6 terminal-override **before** mapping to `cl.TaskStatus` (zombie/failed/cancelled with unfinished steps → first unfinished step `FAILED`, render-only).
    - First call constructs `self._list = PersistedTaskList(status=<§6 header>, name=worker_id, for_id=self._for_id)`; when `self._element_id` was supplied (resume), assign `self._list.id = self._element_id` **before** the first send (row identity, §4.3.1).
    - Structural change (step-id set/order/count differ from last) → `self._list.tasks.clear()` + re-add `cl.Task(title=step.title, status=mapped, forId=self._for_id)` on the same `PersistedTaskList` instance.
    - Status-only change → mutate `task.status` in place on the existing `cl.Task` objects (also `task.title`, so `plan replace`-style description edits that keep the step id show up).
    - Set `self._list.status` to the §6 header string.
    - `await self._list.send()`. `PersistedTaskList.send()` serializes `status`+`tasks` into `content` and calls `Element.send(for_id=self.for_id or "")`: with a message id the elements row is upserted (reload-durable, §1); with `""` (row-miss fallback) it behaves exactly like a plain `cl.TaskList` (live-only). Per-`Task` `forId` chips are unaffected either way.
    - Store `self._last = view`.

4. **Termination.** When the generator returns (terminal view yielded), the watcher task stores nothing further; the `cl.TaskList` is left in its final state. Its rows persist via the elements table (`type="tasklist"`, same storage path as citations). The `(thread_id, wid)` entry stays in `_supervision_watchers` as a *completed* task (not removed) so a duplicate `ensure_watching` call does not re-arm a finished worker.

5. **Cancellation (`on_chat_end_handler`, §5.5).** On chat end, iterate `_supervision_watchers` and `.cancel()` each task before draining memory. Cancelled mid-poll watchers leave the `TaskList` at its last-rendered state.

6. **Resume (`on_chat_resume_handler`, §5.6).** After `restore_chat_history`, call `ensure_watching(thread["id"], elements=thread.get("elements"))`. `find_supervised_workers` returns **only** workers whose audit is `status=="running"` *and* whose pid is alive (`is_process_running`); those get a fresh watcher (the old task was cancelled on chat end), each re-armed element **reusing its persisted row's id + `forId`** (§4.3.1) so the panel the reload just rendered from that row is updated in place. Everything else — already-terminal workers *and* dead-pid (zombie) workers — is **not** armed. Their `TaskList` is shown by the frontend from the persisted element row + storage data (§1), not by a watcher. There is no "final render" watcher for a worker found dead on resume; the last persisted state (which may be mid-`running` if the worker died before settling) is what the user sees, plus the render-only terminal override does **not** apply on the persisted-content path (the frontend renders the stored JSON as-is). This is an accepted limitation: a zombie discovered only on resume may display an optimistic last state until the user prompts Aria, who then reads the audit and corrects it.

**What this model deliberately does not do:**
- No polling by Aria. Aria never calls `worker status` to drive the `TaskList`; the watcher owns all UI updates.
- No wake-on-completion. When the worker finishes, the `TaskList` shows `Done`/`Failed` and the watcher exits. Aria is not notified and does not run. The user must send the next prompt; Aria then reads `result.md`/audit and evaluates. This is final — adding a completion callback is not a deferred item, it is out of scope for this feature.

---

## 5. Detailed changes

### 5.1 Spawn with a plan — `src/aria/tools/worker/functions.py`

- Add required-for-spawn param `steps: list[str] | None = None` to `worker()` (line 42; declared after `expected`, before `instructions`) and forward it into `_spawn()` (call site line 87 / signature line 127). The Python default **must** stay `None` because the non-spawn actions (`list`/`status`/`logs`/`cancel`/`clean`) are called without `steps`; required-ness is enforced at spawn: `None` **or** empty list → `tool_response(..., data={"error": {"code": "missing_steps", "message": "steps is required (ordered execution steps)"}})` (same shape as `missing_prompt`/`missing_expected`, `functions.py:135-156`) before `wid`/plan/`Popen`/audit. No spawn ever proceeds without steps — the `None` default is not a backward-compat path, there is no unsupervised branch. The ax parity test `test_reference_required_args_survive_dispatch` (`test_dispatcher.py:169-204`) dry-runs `_strip_unknown_kwargs` per Required arg, so `steps` being a declared param of `worker()` keeps it from being stripped at dispatch.
- In `_spawn`, after the `prompt`/`expected`/`steps` validation (lines 135-156) and `wid`/`out_dir` setup (lines 158-160), **always create the plan before `Popen`**:
  ```python
  import uuid
  from datetime import UTC, datetime
  from aria.tools.planner.database import PlannerDatabase

  plan_id = str(uuid.uuid4())
  now_iso = datetime.now(UTC).isoformat()
  step_dicts = [
      {
          "id": uuid.uuid4().hex[:8],
          "description": desc,
          "status": "pending",
          "created_at": now_iso,
          "updated_at": now_iso,
      }
      for desc in steps
  ]
  PlannerDatabase().save_plan(
      plan_id=plan_id,
      agent_id=wid,
      task=prompt[:500],
      steps=step_dicts,
      created_at=now_iso,
  )
  ```
  `PlanModel.id` is `String(36)` (`models.py:17`) — `str(uuid.uuid4())` (36 chars) fits. `agent_id` is `String(255)` (`models.py:20`) — `wid` (`worker_<8hex>`) fits. The step-dict keys match what `save_plan` reads (`database.py:62-71`).
- On `save_plan` failure → return a `tool_response(..., data={"error": {...}})` (same shape as the existing `missing_prompt`/`missing_expected` errors, `functions.py:135-156`), do **not** spawn (fail fast).
- Extend the runner cmd (`functions.py:162-176`) with `["--plan-id", plan_id]` (always).
- Extend the audit dict (`functions.py:193-208`) with `"plan_id": plan_id` (always).
- Extend the spawn response (`functions.py:213-222`) with `"plan_id": plan_id` (always).
- Docstring (line 54): document `steps` as **required for spawn**, in the same `(spawn)`-prefixed style as the other args: "steps: (spawn) Required. Ordered execution steps; the worker tracks them as a plan visible in the UI."
- CLI path: `src/aria/cli/worker/__init__.py` delegates to `tools/worker/functions.worker`, so it shares plan creation, audit, validation, and nested-worker protection with the dispatcher path.
- Update the ax reference `src/aria/agents/instructions/reference/ax_commands.md` worker section: move `steps` into the `spawn` row's **Required** column (with `prompt`, `expected`). The parity test `test_reference_required_args_survive_dispatch` (`test_dispatcher.py:169-204`) will then guard it — it dry-runs `_strip_unknown_kwargs` per Required arg, so `steps` being a declared `worker()` param keeps it passing.
- Add a dispatcher test: `ax(family="worker", command="spawn", args={..., "steps": ["a","b"]})` forwards `steps` to the (mocked) target and is **not** stripped by `_strip_unknown_kwargs`. Mirror `test_dispatches_memory_with_action` (`test_dispatcher.py:250-266`).

### 5.2 Worker executes and self-reports — `src/aria/cli/worker/_runner.py`

- Add `--plan-id` arg to the parser (`main()`, `_runner.py:145-152`), **`required=True`** (every spawn now supplies one).
- `_build_prompt` (`_runner.py:28-36`) **always** appends a **Plan section** to the prompt:
  ```
  <system_controlled_execution_plan>
  You have plan <plan_id> registered under agent_id "<wid>".
  Work through its steps IN ORDER using the plan tool:
  first plan(action="get", execution_id="<plan_id>", agent_id="<wid>"), then for each step
  plan(action="update", execution_id="<plan_id>", step_id=<id>, status="in_progress") before acting,
  and plan(action="update", execution_id="<plan_id>", step_id=<id>, status="completed", result="<summary>") after.
  On an unrecoverable step, set status="failed" with the reason in result.
  </system_controlled_execution_plan>
  ```
  (`<plan_id>` = `args.plan_id`; `<wid>` = `args.worker_id`.) Passing `agent_id` in the `plan` calls is harmless: `plan()` declares the parameter and `get`/`update` key only on `execution_id` (`planner/functions.py:837-902`); `PlanSchema`'s "Auto-set. Do not provide." note is LLM-facing guidance, not a rejection mechanism for programmatic call wording.
  - Finalize step statuses so the panel never lies. Shared helper in `src/aria/tools/worker/results.py`:
    ```python
    def settle_unfinished_step(plan_id: str, reason: str) -> None:
        """Mark the first unfinished plan step failed so the panel never lies.

        Best-effort attribution: the crashed step is approximated as the
        in_progress step, else the first pending step. No-op when the plan is
        missing or every step is already terminal. Safe on crash/zombie paths:
        uses only PlannerDatabase (a fresh session on the singleton engine).
        """
    ```
    There is **no "completed" promotion**: a worker is never marked completed merely because the subprocess exited. `_record_completion` builds the manifest from live Planner DB state; `build_manifest(status="completed")` degrades to `partial` (steps unfinished) or `failed` (report missing) with a warning. The audit `status` mirrors `manifest.status`, so the panel, audit, and manifest agree.
  - On **failure** (`_record_failure`): `settle_unfinished_step(plan_id, str(exc))` marks the current `in_progress` step — **else the first `pending` step** if there is no `in_progress` (the worker may crash before it calls `plan(update, in_progress)`) — as `failed`. This is **best-effort attribution**: it fails one step so the panel shows a concrete failure point rather than a sea of `pending`, but it does not guarantee the failed step is the one that actually crashed. Do not attempt to detect "the real failing step" — there is no signal for it after a crash.
  - On **zombie detection** (`_mark_zombie`, `functions.py`): a worker whose pid dies without writing a terminal audit leaves `pending`/`in_progress` steps behind. All four detection sites (`_list_workers`, `_status`, CLI `list`, CLI `status`) call `_mark_zombie(audit)`, which flips the audit to `zombie` **and** calls `settle_unfinished_step(plan_id, "worker process died")` so the Planner DB stops claiming live progress.
  - `_record_completion`/`_record_failure` take a `plan_id: str` param, always provided by `_run`. `settle_unfinished_step` runs before the manifest write, so the manifest reflects the settled DB state; the audit write follows with `status = manifest.status`. A poll never sees "audit terminal + unsettled steps" for long; the transient gap is covered by the render-only override (§6). `settle_unfinished_step` early-returns if `load_plan(plan_id)` is `None` (defensive — the plan should always exist since spawn created it).
  - **Crash-path safety**: `_record_failure` runs inside the bare `except Exception` in `_run`, reached after an arbitrary workflow crash. `settle_unfinished_step` is safe there: it uses only `PlannerDatabase()` (a fresh session per call on the singleton engine — the workflow holds no planner session to reuse), and the `plans`/`plan_steps` tables are guaranteed present in the shared `tools.db` because the web process ran `PlannerDatabase().save_plan` (hence `create_tables`) **before** `Popen` (§7). A crash before `get_worker_agent` just means step statuses were never updated — settle still reads the seeded plan and settles it.

### 5.3 Supervision core — `src/aria/supervision/` (new, UI-agnostic)

**`snapshot.py`** (~100 lines)

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class StepView:  # mirrors a planner step — no chainlit types
    id: str
    title: str
    status: str  # "pending" | "in_progress" | "completed" | "failed"
    result: str | None


@dataclass(frozen=True)
class WorkerView:  # one renderable unit
    worker_id: str
    plan_id: str
    task: str
    steps: tuple[StepView, ...]
    worker_status: (
        str  # "running" | "completed" | "partial" | "failed" | "cancelled" | "zombie"
    )


def load_worker_view(worker_id: str) -> WorkerView | None:
    """audit JSON (status/task/plan_id) + PlannerDatabase (steps, ordered).
    Returns None only when the audit file is missing/unreadable or its
    plan_id has no plan row in the DB (corrupt/orphaned) — every well-formed
    spawn has a plan_id now. Zombie detection uses
    aria.server.process_utils.is_process_running, identical to
    workers/functions._list_workers (functions.py:236-240) and _status
    (functions.py:273-275): running audit + dead pid → "zombie"."""


def find_supervised_workers(thread_id: str) -> list[str]:
    """Worker ids from Data.path/workers/*.json (glob "worker_*.json",
    same pattern as functions.py:230,349) where:
      audit["thread_id"] == thread_id
      AND audit["status"] == "running"
      AND is_process_running(audit["pid"]) is True.
    Dead-pid audits (would-be "zombie") are EXCLUDED — they are not armed.
    This function is the **sole gate for arming watchers on resume**: a worker
    whose audit says "running" but whose process died is not returned, so
    no watcher is armed for it. Its final state is shown by the frontend
    from the persisted element row + storage data (§1), not by a watcher —
    there is no "already-armed watcher" on a fresh resume to do a final
    render. (Every audit now carries a plan_id, so no separate plan_id
    check.) Terminal audits (completed/failed/cancelled) are also excluded —
    same reason: the frontend renders them from the persisted row on resume.
    Returns [] when Data.path/workers does not exist."""
```

`load_worker_view` reads steps from `PlannerDatabase().load_plan(plan_id)` (`database.py:77-110`), mapping each step dict to `StepView(id=step["id"], title=step["description"], status=step["status"], result=step.get("result"))`. Steps arrive in `step_number` order (`database.py:89-101`, `order_by` in `models.py:41`).

**Implementation notes.**

- `WORKERS_DIR` is read from the `aria.tools.worker.functions` module **at call time** (e.g. `import aria.tools.worker.functions as worker_tool` at module level, then `worker_tool.WORKERS_DIR` inside the functions) — never bound to a local at import time. `WORKERS_DIR` is a module constant of `functions.py` bound from `Data.path` at import (`functions.py:26`), and the §8.3 tests patch exactly `aria.tools.worker.functions.WORKERS_DIR`; an import-time binding in `snapshot.py` would point at the stale directory and make the patch — and the tests relying on it — vacuous.
- `load_worker_view` is strictly read-only: zombie detection does **not** rewrite the audit to `status="zombie"` (that persistence side-effect stays with `_list_workers`/`_status`, `functions.py:236-240,273-275`); the view simply reports `"zombie"` without persisting it.
- Read-only polling plus one session per poll (`load_plan`'s `with self.get_session()`) keeps the web process clear of SQLite write locks while the worker writes plan steps (`§7`, pool_pre_ping handles stale connections, `database.py:49`).

**`watch.py`** (~90 lines)

```python
from collections.abc import AsyncIterator
from aria.supervision.snapshot import WorkerView, load_worker_view

_TERMINAL = {"completed", "partial", "failed", "cancelled", "zombie"}


async def watch_worker(
    worker_id: str, interval: float = 1.5
) -> AsyncIterator[WorkerView]:
    """Poll every `interval`; yield only when (steps, worker_status) changed;
    terminate (after yielding the final view once) when worker_status is
    terminal. First yield is immediate. Never raises — transient load errors
    are swallowed and the next poll retries. No total poll budget (workers
    may run for hours); liveness comes from terminal status."""
```

Equality check for "changed": compare the previous `WorkerView` (a frozen dataclass) to the new one with `!=` — `tuple` of `StepView` compares element-wise.

### 5.4 Chainlit adapter — `src/aria/web/tasklist.py` (new)

```python
import chainlit as cl
from chainlit.element import Element

_STEP_TO_TASK = {
    "pending": cl.TaskStatus.READY,
    "in_progress": cl.TaskStatus.RUNNING,
    "completed": cl.TaskStatus.DONE,
    "failed": cl.TaskStatus.FAILED,
}


class PersistedTaskList(cl.TaskList):
    """cl.TaskList that keeps its constructor for_id when sending.

    Plain cl.TaskList hard-codes for_id="" (element.py:351-353), and both
    create_element implementations skip elements with a falsy for_id
    (chainlit data/sql_alchemy.py:588-589, src/aria/db/layer.py:435-436),
    so a plain TaskList never writes an elements row and vanishes on
    reload. Sending with a real for_id makes the row persist; the
    updatable re-sends upsert the same row (layer.py:413-417).
    for_id=None degrades to exactly the plain-TaskList behavior (live-only).
    """

    async def send(self) -> None:
        await self.preprocess_content()
        await Element.send(self, for_id=self.for_id or "")


class WorkerTaskList:
    """One PersistedTaskList bound to one worker."""

    def __init__(
        self, worker_id: str, for_id: str | None = None, element_id: str | None = None
    ) -> None:
        self._worker_id = worker_id
        self._for_id = for_id
        self._element_id = element_id  # cross-session reuse (§4.3.1)
        self._list: PersistedTaskList | None = None
        self._last: WorkerView | None = None
        self._step_ids: list[str] | None = None  # None → structural rebuild

    async def render(self, view: WorkerView) -> None:
        """Re-send only if `view != self._last`. First call constructs
        PersistedTaskList(status=<§6 header>, name=worker_id, for_id=...)
        and, when `_element_id` is set, assigns the element id before any
        send. On structural change (step-id set/order/count differ) rebuild
        the cl.Task list on the same instance; on status-only change mutate
        in place. Applies the terminal-override (see §6) before mapping
        step statuses to TaskStatus."""
```

- Element construction: `PersistedTaskList(status=<§6 header>, name=worker_id, for_id=self._for_id)` — `name=worker_id` is the row ↔ worker discriminator used by resume's row lookup (row key `name`, §4.3.1); `for_id` is the element-level persistence linkage (§1). A supplied `element_id` is assigned to the element's `id` before its first `send` (row identity across sessions, §4.3.1). `Task` titles are the step description (Markdown supported); each `Task` is built with `forId=self._for_id` (per-`Task` `forId` is what drives the in-chat navigation chips — the element-level `for_id` exists only to pass the `create_element` guard and has no visible effect on the side-panel element).
- **List status (header) string**: see the §6 mapping table — `"Ready"` · `"Running {i}/{n}"` · `"Done"` · `"Failed"` · `"Cancelled"`.
- **Step-status lookup** uses `_STEP_TO_TASK.get(step.status, cl.TaskStatus.READY)` — `plan_steps.status` is a free `String(20)` column (`models.py:63`); an unexpected value degrades to `READY` instead of killing the watcher mid-poll.
- **Terminal-override render rule** (§6): when `view.worker_status` is terminal and ≠ `"completed"`, mark the first unfinished step (`in_progress`, else first `pending`) as `cl.TaskStatus.FAILED` **in the render only** — do not write to the DB. This is a display safety net; the DB is settled by `settle_unfinished_step` on the runner failure path and by `_mark_zombie` on the zombie path, so an unfinished step at terminal time is the exception, not the norm.

### 5.5 Watcher lifecycle — `src/aria/web/supervisor.py` (new)

```python
async def ensure_watching(
    thread_id: str,
    *,
    for_id: str | None = None,
    elements: list[dict] | None = None,
) -> None:
    """For each supervised worker (snapshot.find_supervised_workers) without
    an active watcher, create a WorkerTaskList, launch an asyncio task that
    iterates watch_worker and calls renderer.render(view) per yield, and
    store the task on cl.user_session. Persistence identity per worker:
    spawn turn uses `for_id` (the spawning message id); when `elements`
    (the thread's persisted element rows, camelCase keys) is given, the
    row with type=="tasklist" and name==worker_id supplies
    element_id=row["id"], for_id=row["forId"] — reused so the reload panel
    updates in place (§4.3.1). No row / no elements → (element_id=None,
    for_id=None), live-only. On terminal view the watcher leaves the
    TaskList in its final state (the elements row then holds the last
    render)."""


def cancel_all_watchers() -> None:
    """Cancel every stored watcher task (chat end). Entries stay in
    _supervision_watchers (as cancelled tasks) so re-arming stays
    idempotent."""
```

- **Watcher state lives on `cl.user_session`, not `_state`, not a module dict.** Decided: watcher state is per-session (one user's running workers must not leak to another user's session). `cl.user_session` is session-scoped and is the existing home for per-session handles (`memory`, `thread_titled` in `hooks.py`). A module-level `_watchers = {}` is banned by AGENTS.md ("no mutable module-level globals"); `_state` is app-wide (shared `db_engine`, `agents_workflow`), so it is the wrong scope. Use `cl.user_session.set("_supervision_watchers", …)`. Note `cl.user_session` is JSON-serialized into thread metadata, so only serializable data belongs there — live `ClientSession` objects once stored under `_mcp_sessions` broke thread resume and were moved to Chainlit's in-memory `context.session.mcp_sessions`.
- **`cl.user_session` is a `UserSession` proxy, not a dict** (`chainlit/user_session.py`): `get`/`set` early-return `None` when `context.session` is unset, then read/write a backing dict keyed by `context.session.id`. At runtime (inside a Chainlit handler) `context.session` is always set, so production code is fine. **Tests must not substitute a bare `dict` for `cl.user_session`** — its `get` would return the default and `set` would be a no-op, making `ensure_watching` silently do nothing and tests pass vacuously (the "test that always passes" dead-weight AGENTS.md forbids). In tests, `monkeypatch.setattr("aria.web.supervisor.cl.user_session", <MagicMock>)` where the mock's `get`/`set` back a real dict, or `patch` the module attribute. The §8.6 tests are written against this mock shape.
- Watcher state key: `"_supervision_watchers"` → `dict[tuple[str, str], asyncio.Task]` keyed by `(thread_id, worker_id)`. `ensure_watching` reads it, arms missing entries, and is a fast no-op when `find_supervised_workers(thread_id)` returns `[]` (one directory scan).
- Cancellation: `cancel_all_watchers()` cancels every task in `cl.user_session.get("_supervision_watchers")`. It is the **first** statement of `on_chat_end_handler` (`hooks.py:162-175`) — before the `memory is None` early-return — so any session whose watchers outlived its memory still gets its tasks cancelled before the session's context goes away.
- Re-arming on resume: `on_chat_resume_handler` (`hooks.py:178-206`) calls `ensure_watching(thread["id"], elements=thread.get("elements"))` after `restore_chat_history`. Only alive-running workers (`find_supervised_workers`) get a fresh watcher, each re-armed element reusing its persisted row's id + `forId` (§4.3.1). Terminal and zombie workers are **not** armed — no final render, no watcher; their panels are the persisted rows (the draft's "already-terminal workers get one final render then exit" wording here contradicted §4.3.6 and is superseded by §4.3.6).

### 5.6 Trigger points

- `message_pipeline._stream_and_finalize` (`message_pipeline.py:131-177`): in the success branch, after `await output.send()` (line 162) and `_mark_message_processed` (line 163-165), call `await ensure_watching(message.thread_id, for_id=output.id)`. `output` is a `cl.Message` with an `.id` attribute — pass it as `for_id` so each `Task` links to the assistant message that spawned the worker **and** so the element row passes the `create_element` `for_id` guard (persistence, §1). Guarded to no-op when no supervised workers exist. Only the success branch: a failed turn never spawns a worker (the `worker` tool runs inside the workflow, so a crashed turn left no spawn) and a partial-send path would not have a meaningful message to link.
- `hooks.on_chat_resume_handler` (line 178): after `restore_chat_history` (line 202) and the memory set, call `ensure_watching(thread["id"], elements=thread.get("elements"))`. There is no `for_id` argument here: per-worker `for_id`/`element_id` come from the persisted rows (§4.3.1); workers whose row is absent fall back to live-only (`for_id=None`).
- `hooks.on_chat_end_handler` (line 162): `cancel_all_watchers()` as the first statement (§5.5).
- `hooks.on_chat_start_handler` (line 128): a new chat has no existing workers, so `ensure_watching` is a no-op there; skip it (do not call) to avoid an unnecessary directory scan on every new chat start.

### 5.7 Instructions updates

Two instruction files change. Both are required for the feature to behave (without them the model will either hit `missing_steps` on every spawn, or the worker will re-author a plan it was handed).

#### `src/aria/agents/instructions/aria.md` — the "Spawning Workers" block (lines 54-74)

Today the spawn example (lines 58-70) shows `prompt / expected / instructions / output_dir` and **no `steps`**. Since `steps` is now required (`§5.1`), every spawn without it returns `missing_steps`. Rewrite the block to:

1. **Precede spawn with a Decomposition step.** Before the `ax(worker, spawn, …)` call, Aria must gather context (read-only tools, `≤15` calls per `aria.md:86`) and produce an ordered, measurable plan. Concretely, before spawning:
   - State the goal and acceptance criterion in one line.
   - Produce `steps`: an ordered `list[str]`, each step one concrete action with a verifiable outcome; the **last** step is the success check (e.g. "Verify `<path>` exists and passes `<check>`"). Hold this in `reasoning`/`scratchpad`, **not** the `plan` tool (Aria does not own the plan — §4.2 #1).
2. **Update the spawn example to include `steps`:**
   ```python
   ax(
       reason="...",
       family="worker",
       command="spawn",
       args={
           "prompt": "...",
           "expected": "...",
           "steps": ["...", "...", "..."],  # required, ordered, measurable
           "instructions": "...",
           "output_dir": "...",
           "thread_id": "...",
       },
   )
   ```
3. **Keep "Stop your turn immediately" (line 74).** The live `TaskList` is driven by the background watcher (`§5.5`); Aria does not poll. On the user's *next* prompt, Aria reads `result.md` / the audit and evaluates (`aria.md:51-52` already covers this — no change needed there).
4. **Do not** add an instruction telling Aria to call the `plan` tool to create the plan. Per §4.2 #1, Aria passes `steps` strings; `_spawn` owns plan creation. Adding a `plan(create)` step for Aria would create an `agent_id` mismatch and a redundant two-call spawn.

Reference pointer: the `ax_commands.md` worker section lists `steps` under Required (`§5.1`); Aria fetches that table via `ax(family="help", command="lookup", args={"topic": "worker"})` when unsure (`base/tools.md`, Resolution Order). No separate Aria-side reference file is needed.

#### `src/aria/agents/instructions/worker.md` — the "Planning (mandatory)" section (lines 39-45)

This is the **conflict**: today it tells the worker to **create** a plan ("Start with `plan`. Create concrete steps AND a completion condition."). Under the new flow the plan is **pre-created by `_spawn` and handed in via `--plan-id`**; the worker must **execute and update** it, not author one. Leaving the old instruction in place would have the worker call `plan(create)` and orphan the seeded plan, or fork a second plan under its own `agent_id`.

Rewrite the section to:

1. **Replace "Start with `plan`. Create concrete steps…" (bullet 1, line 41) with an Execute-an-existing-plan directive:**
   > A plan has been created for you and registered under your agent id (the runner injects its `execution_id` and your `agent_id` in the prompt). Do **not** create a new plan. Work through the existing steps **in order** using the `plan` tool: `plan(get)` to read it, then for each step `plan(update, …, status="in_progress")` before acting and `plan(update, …, status="completed", result="…")` after. On an unrecoverable step, set `status="failed"` with the reason in `result`.
2. **Fix the `Additional Tools` bullet (line 20)** — **"plan — Create before any work. Update after each step."** contradicts the no-reauthor flow and must change with the section to: "**`plan`** — A plan is handed in with the prompt (see the Execution Plan section); execute its steps in order and update after each step. Never create a new plan. The plan is how the user tracks your progress." Without this, the worker gets two contradictory instructions (create at line 20, don't-create at line 41) and the old behavior wins.
3. **Keep the section heading `### Planning (mandatory)`** — content changes, heading stays: `test_load_agent_instructions.py:63` pins that literal for the worker prompt, so keeping it avoids a test change; the heading remains descriptive ("planning" now means executing the handed-in plan, and the budget/progress rules keep it planning-adjacent).
4. **Keep the budget/progress-gate rules (lines 42-44)** — they apply unchanged to executing a plan, not just authoring one.
 5. **Keep the completion-reasoning block (lines 47-57)** — "Did every step succeed? …" now reads the *handed-in* plan's statuses, which is exactly what `settle_unfinished_step` guarantees are terminal.

**Single-source rule (prompt drift) — decided.** Create `src/aria/agents/instructions/_worker_plan_section.py` (the draft's `src/agents/…` path was a typo; the instructions package is `src/aria/agents/instructions/`) exporting `PLAN_SECTION_TEMPLATE: str` (the literal Plan section from §5.2, with `{plan_id}` / `{agent_id}` placeholders). `_runner._build_prompt` imports it and does `PLAN_SECTION_TEMPLATE.format(plan_id=args.plan_id, agent_id=args.worker_id)`. `worker.md`'s "Planning" section states the **same behavior in prose** — it does *not* import the Python constant (markdown cannot import); it reuses the wording verbatim where possible and is kept in lockstep by the instructions test (§8.9: assert the template renders, and assert `worker.md` no longer contains the old re-author wording — the draft's proposed literal `"Start with plan. Create"` never matched `worker.md` verbatim because of the markdown backticks/asterisks around `` `plan` `` (the actual text is "Start with `plan`.** Create concrete steps"); the testable stable substrings are `"Create concrete steps"` and `"Create before any work"`). The template lives under `instructions/` (not `supervision/`) because it is prompt content, not UI-agnostic core. Drift between the two is caught at test time, not runtime.

#### `worker()` docstring + ax reference

- `worker()` docstring (`§5.1`) is the main-agent contract for the required `steps` arg.
- `ax_commands.md` worker section lists `steps` under Required (`§5.1`); the parity test `test_reference_required_args_survive_dispatch` (`test_dispatcher.py:169-204`) then guards it.

### 5.8 Future CLI adapter (design point only)

`watch_worker()` + `WorkerView` contain everything a text UI needs: a CLI watcher prints a live table (`step | state | result`) from the same snapshots. **Zero `chainlit` types cross `aria/supervision`** — enforce with a test that asserts no `chainlit` import appears in `src/aria/supervision/` (walk the package, `ast.parse` each `.py`, fail on any `Import`/`ImportFrom` node whose module starts with `chainlit`).

---

## 6. Status mapping

| planner `StepStatus` | `cl.TaskStatus` | render rule |
|---|---|---|
| `pending` | `READY` | as-is |
| `in_progress` | `RUNNING` | as-is |
| `completed` | `DONE` | as-is |
| `failed` | `FAILED` | as-is |
| worker terminal ≠ completed (partial/failed/cancelled/zombie) with unfinished steps | first unfinished step → `FAILED` | render-only override (DB untouched) |

**List header (`TaskList.status`) mapping** — with `n = len(view.steps)` and `i` = 1-based index of the first step whose status is not `"completed"` (capped at `n`):

| condition | header |
|---|---|
| `worker_status == "completed"` | `"Done"` |
| `worker_status == "partial"` | `"Partial"` |
| `worker_status == "failed"` or `"zombie"` | `"Failed"` |
| `worker_status == "cancelled"` | `"Cancelled"` |
| `running`, `n > 0`, all steps completed | `"Done"` |
| `running`, no steps | `"Ready"` |
| `running`, `n > 0`, some step not completed | `"Running {i}/{n}"` |

`"Ready"` is only reachable for a zero-step plan (spawn rejects empty `steps`, so this is a data-boundary case, not a normal state). A zombie header is `"Failed"` (not `"Running …"`) because the worker can no longer advance — consistent with the render-only override above, which already marks the first unfinished step `FAILED` for zombies.

---

## 7. Edge cases

- **Worker edits its own plan** (`plan(add/remove/reorder)`) → renderer rebuilds the task list on structural diff (step-id set/order/count change). `settle_unfinished_step` reads the current plan at finalize, so it settles whatever steps exist then.
- **Empty `steps` rejected at spawn** → `missing_steps` error response, no plan, no Popen, no audit written (fail fast, same shape as `missing_prompt`).
- **Zombie worker** (web restarted, worker died) → `load_worker_view`/`find_supervised_workers` detect via `is_process_running(pid)` (same check as `functions.py:236-240`); the armed watcher's first poll yields the terminal `"zombie"` view with the render override.
- **Multiple workers per thread** → one `TaskList` per worker (keyed `(thread_id, worker_id)` on `cl.user_session`).
- **Long-lived worker / web restart mid-run** → resume path re-arms the watcher; the re-armed `PersistedTaskList` reuses the persisted row's id + `forId` (§4.3.1), so the panel the reload rendered from the row is updated in place — one panel, no duplicate — and the row upserts through to the terminal render's content.
- **Elements row lost before resume (fire-and-forget race)** → `create_element` runs as a detached task (`element.py:210`); if the web app shut down before it executed (or it errored — chainlit logs and swallows, `element.py:212-214`), no row exists. Resume row-miss ⇒ re-armed element with fresh id + `for_id=None` ⇒ panel is live-only (no row written, no chips for this session). The worker's progress remains available as before via the audit / `worker status` / `result.md`. No compensating logic — accepted.
- **SQLite concurrent writes** (web polls, worker writes plans): two processes, each with its own `ToolsDatabase` engine to the same `~/.aria/db/tools.db`. `pool_pre_ping=True` (`database.py:49`) handles stale connections. Polls are read-only and use one session per poll (`with db.get_session() as session`, the existing pattern in `planner/database.py`).
- **Planner tables exist in both processes (verified, load-bearing on import order).** `PlannerDatabase.__init__` calls `self._tools_db.create_tables()` → `Base.metadata.create_all` (`database.py:32,53-56`), which only creates tables whose models are **imported** in that process. The web process imports planner models via `aria.tools.registry` → `aria.tools.planner` (lazily, when `get_tools([CORE,…])` runs at startup). The worker process imports them via the same `aria.tools.registry` path inside `_run` (`_runner.py:108` → `get_worker_agent` → `get_tools([CORE, FILES, AX])`). So both processes have the models registered before any first plan write. **Critically, `_spawn` runs in the web process and calls `PlannerDatabase().save_plan(...)` *before* `Popen`** — so the web process's `create_tables` has run and `plans`/`plan_steps` exist in `tools.db` by the time the worker subprocess starts and reads. An agent "optimizing" imports (e.g. lazy-importing planner models out of the registry path) would silently break this: the worker's first `plan(get)` would hit a missing table. Do not decouple the planner model import from the registry path without re-verifying table creation in both processes. Add a test: spawn (with a fresh temp `tools.db` that has *no* `plans` table) → assert the table is created and the plan row is readable.
- **Plan-creation failure at spawn** → no worker launched, explicit error to the model (fail fast).

---

## 8. Test plan

Co-located with each module (repo convention: `src/aria/<mod>/tests/`). `asyncio_mode="auto"` (`pyproject.toml`) — async tests are bare `async def`, no decorator. Shared `test_tools_db` fixture (`conftest.py:229`) resets DB singletons and yields a temp `ToolsDatabase`; depend on it for any test that touches the planner DB. Mock `chainlit` via `AsyncMock`/`MagicMock` — never spin the real frontend. Only **behavior that can regress** is pinned (AGENTS.md); no tests that restate the code.

### 8.1 `src/aria/tools/worker/tests/test_spawn.py` (new)
Fixture: `test_tools_db`; mock `subprocess.Popen` to capture `cmd` and return a fake pid.

- `test_spawn_with_steps_creates_plan` — `_spawn(steps=["a","b","c"], …)` → `PlannerDatabase().load_plan(<id>)` returns a plan with `agent_id == wid`, 3 steps in order, all `pending`. Assert the captured `cmd` contains `--plan-id <id>` and the audit JSON (read via `load_state`) has `plan_id`.
- `test_spawn_response_includes_plan_id` — the `tool_response` JSON `data` contains `plan_id`.
- `test_spawn_empty_steps_returns_missing_steps` — `steps=[]` **and** `steps=None` (parametrized) → `data.error.code == "missing_steps"`, `PlannerDatabase.save_plan` not called, no `Popen` call (assert mock not called), no audit file written (fail fast before any side effect).
- `test_spawn_save_plan_failure_aborts` — `monkeypatch` `PlannerDatabase.save_plan` to raise; `_spawn` returns an error response, `Popen` not called, no audit written (fail fast).
- `test_spawn_creates_plans_table_if_absent` — point `ToolsDatabase` at a temp `tools.db` with **no** `plans`/`plan_steps` tables (reset singletons, instantiate `ToolsDatabase` but do **not** call `create_tables`); `_spawn(steps=[…])` → `save_plan` creates the tables (via `PlannerDatabase.__init__` → `create_tables`) and the plan row is readable via `load_plan`. Pins the §7 import-order guarantee so an import-graph refactor can't silently drop table creation.
- `test_spawn_without_steps_still_works_legacy` — **delete this**: no legacy mode. (Left as an explicit note so an agent does not re-add a backward-compat test the feature explicitly removed.)

### 8.2 `src/aria/cli/worker/tests/test_runner.py` (new, extend existing module)
Fixture: `test_tools_db` for `settle_unfinished_step`.

- `test_parse_plan_id_required` — `argparse` with no `--plan-id` → `SystemExit` (argparse `required=True`).
- `test_build_prompt_contains_plan_section` — `_build_prompt(args)` (args with `plan_id="P", worker_id="W"`) contains `"P"`, `"W"`, and `"plan(action=\"get\""` (the step-order instruction). Assert it for the **always-appended** case (no `if plan_id` branch to test).
- `test_settle_does_not_promote_unfinished` — seed 1 `completed`, 1 `in_progress`, 2 `pending`; `settle_unfinished_step(plan_id, "…")` → the `in_progress` step fails, the rest stay as-is (no "completed" promotion).
- `test_settle_fails_in_progress_step` — seed 1 `in_progress`, 2 `pending`; `settle_unfinished_step(plan_id, "boom")` → the `in_progress` step is `failed` with `result == "boom"`; the 2 `pending` stay `pending`.
- `test_settle_no_in_progress_fails_first_pending` — seed 3 `pending`, no `in_progress`; `settle_unfinished_step(plan_id, "…")` → first `pending` is `failed`, rest `pending`. (Best-effort attribution — see §10 risk note.)
- `test_settle_no_plan_returns_silently` — `settle_unfinished_step("nonexistent-id", "…")` returns without raising (no DB row).

### 8.3 `src/aria/supervision/tests/test_snapshot.py` (new)
Fixture: `test_tools_db`; write audit JSONs directly via `save_state` into a tmp `WORKERS_DIR` (patch `aria.tools.worker.functions.WORKERS_DIR` to a tmp path, or pass an injectable dir — prefer patching the module attr for parity with the real glob).

- `test_load_worker_view_returns_ordered_steps` — audit with `plan_id` + a 3-step plan in DB → `WorkerView` with `worker_status == "running"` and `steps` in `step_number` order.
- `test_load_worker_view_orphan_plan_returns_none` — audit has `plan_id` but no plan row in DB → `None`.
- `test_load_worker_view_missing_audit_returns_none` — no audit file → `None`.
- `test_load_worker_view_zombie_when_dead_pid` — audit `status == "running"`, `monkeypatch` `is_process_running` → `False` → `worker_status == "zombie"`.
- `test_find_supervised_workers_filters_by_thread` — 3 audits: 2 with `thread_id == T` (one running+alive, one completed), 1 with `thread_id == "other"`. → returns only the running+alive `wid` for `T`.
- `test_find_supervised_workers_excludes_dead_pid_and_terminal` — three audits for the same thread: (a) running+alive → included; (b) running but `is_process_running → False` (zombie-on-resume) → excluded; (c) `status=="completed"` → excluded. Pins the §5.3 contract that resume arms only alive-running workers; zombies and terminal workers render from persisted content (§10), not a watcher.
- `test_find_supervised_workers_empty_when_no_dir` — patch `WORKERS_DIR` to a non-existent path → `[]` (no raise).

### 8.4 `src/aria/supervision/tests/test_watch.py` (new)
Fixture: `test_tools_db`; drive the generator with `anext` / `async for` and mutate the DB between iterations.

- `async test_first_yield_is_immediate` — seed a view; `await anext(watch_worker(wid))` returns without an `asyncio.sleep` (mock `asyncio.sleep` to detect the call; first iteration must not await it). Use a short `interval` to keep the test fast.
- `async test_yields_only_on_change` — seed a 2-step plan; consume first view; flip one step to `in_progress` in the DB; `anext` returns the new view; flip nothing; `anext` again — assert it does **not** return (use `asyncio.wait_for(anext(...), timeout=0.2)` → `TimeoutError`).
- `async test_terminates_after_final_yield` — set audit `status="completed"`; `anext` returns the terminal view once; the next `anext` raises `StopAsyncIteration`.
- `async test_swallows_transient_load_error` — `monkeypatch` `load_worker_view` to raise once then return a view; the generator does not raise, yields the view on the next poll.

### 8.5 `src/aria/web/tests/test_tasklist.py` (new)
Mock `chainlit` (`cl.TaskList`, `cl.Task`, `cl.TaskStatus`) with `AsyncMock`/`MagicMock`; assert on `.tasks` list and `.send` call count.

- `test_step_to_task_mapping_covers_all_statuses` — `_STEP_TO_TASK` has keys `{pending, in_progress, completed, failed}` mapping to the 4 `cl.TaskStatus` members.
- `async test_render_first_view_builds_tasks` — first `render(view)` creates `len(view.steps)` `cl.Task` objects on the `TaskList`, sets `.status`, calls `send()` once.
- `async test_status_only_change_mutates_in_place` — render view₁, then view₂ with same step ids but a status flip → no `tasks.clear()`, the existing `Task.status` is updated, `send()` called again (count = 2 total).
- `async test_structural_change_rebuilds_tasks` — view₂ with different step ids → `tasks.clear()` called, new tasks added, `send()` count increments.
- `async test_no_resend_when_unchanged` — render the same view twice → `send()` called once total (second `render` is a no-op).
- `async test_terminal_override_marks_first_unfinished_failed` — view with `worker_status="zombie"`, steps `[completed, in_progress, pending]`; `render` → the `in_progress` `Task` becomes `cl.TaskStatus.FAILED` in the render, **and** `db.update_step` is **not** called (assert the mock `PlannerDatabase.update_step` was not invoked — render-only override).
- `test_persisted_tasklist_forwards_for_id` — `PersistedTaskList(for_id="M").send()` with `Element.send` mocked-as-AsyncMock → awaited with `for_id="M"`; `for_id=None` → `for_id=""` (the plain-TaskList, non-persisting path). This is the behavioral difference the whole persistence design rests on.
- `test_element_identity_set_before_first_send` — `WorkerTaskList("W", for_id="M", element_id="E").render(view)` → the element has `.id == "E"` and `.name == "W"` and `.for_id == "M"` (row identity for the resume reuse, §4.3.1); with `element_id=None`, `.id` is the element's own uuid (not `"E"`), `.name == "W"`.
- `test_status_header_mapping` — pin the §6 header table per state: `worker_status="completed"` → `"Done"`; `"zombie"` → `"Failed"` (the bug this mapping pins — a zombie must not read as still `"Running"`); `"cancelled"` → `"Cancelled"`; running + all steps completed → `"Done"`; running + 3 pending steps → `"Running 1/3"`.

### 8.6 `src/aria/web/tests/test_supervisor.py` (new)
Mock `find_supervised_workers`, `watch_worker` (an async generator yielding a fixed view sequence), `WorkerTaskList`. **Mock `cl.user_session` as a `UserSession`-shaped `MagicMock` whose `get`/`set` back a real dict — never a bare dict** (see §5.5: `cl.user_session` is a proxy, not a dict; a bare dict makes `ensure_watching` silently no-op and tests pass vacuously). Use `monkeypatch.setattr("aria.web.supervisor.cl.user_session", mock)` where `mock.get.side_effect = lambda k, d=None: store.get(k, d)` and `mock.set.side_effect = lambda k, v: store.__setitem__(k, v)` over a local `store = {}`.

- `async test_ensure_watching_arms_one_watcher_per_worker` — `find_supervised_workers` returns `[w1, w2]`; two `asyncio.Task`s created, stored under distinct `(thread, wid)` keys.
- `async test_ensure_watching_idempotent` — call twice with the same thread; second call adds no new task (same key present).
- `async test_ensure_watching_noop_when_no_workers` — `find_supervised_workers → []`; no task created, no `WorkerTaskList` constructed.
- `async test_final_render_leaves_tasklist` — mock `watch_worker` to yield one running then one terminal view; the watcher calls `render` twice and the task completes (assert `render` call count == 2, second view was terminal).
- `async test_cancellation_on_chat_end` — arm a watcher; call the `on_chat_end` cancel path; assert the stored `asyncio.Task` had `.cancel()` called.
- `async test_resume_re_arms_only_running_and_alive` — on resume, `find_supervised_workers` returns only alive-running workers; `ensure_watching` arms exactly those and no others (the test pins that the supervisor trusts the `find_supervised_workers` filter — it does not re-check pid liveness itself). Cover the zombie-on-resume case: a dead-pid worker in the thread is not armed.
- `async test_resume_reuses_persisted_element_row` — `find_supervised_workers → [w1]`; `ensure_watching("T", elements=[{"id": "E1", "type": "tasklist", "name": "w1", "forId": "M1"}])` → the `WorkerTaskList` for `w1` gets `for_id="M1"`, `element_id="E1"`. With `elements=None`, or with a rows list that has no row for `w1`, → `for_id=None, element_id=None` (row-miss fallback, §4.3.1). Also pins the row-match rule (`type=="tasklist"` **and** `name==worker_id` — a tasklist row named after another worker does not match).

### 8.7 `src/aria/supervision/tests/test_decoupling.py` (new)
Static guard, no fixtures.

- `test_no_chainlit_import_in_supervision_core` — walk `src/aria/supervision/*.py`, `ast.parse` each, fail if any `Import`/`ImportFrom` node's module starts with `chainlit`. (Mirrors the existing `ast`-based approach used in dispatcher reference parity tests.)

### 8.8 `src/aria/tools/ax/tests/test_dispatcher.py` (extend)
Modeled on `test_dispatches_memory_with_action` (`test_dispatcher.py:250-266`).

- `async test_dispatches_worker_spawn_with_steps` — `patch` `aria.tools.worker.functions.worker`; `ax(family="worker", command="spawn", args={prompt, expected, steps=["a","b"]})` → the mock is called with `reason, action="spawn", prompt=…, expected=…, steps=["a","b"]` (assert `steps` survives `_strip_unknown_kwargs`).
- `async test_worker_spawn_strips_truly_unknown_kwarg` — pass `args={..., "bogus": 1}`; the mock is called **without** `bogus` (regression guard that adding `steps` did not widen the strip filter).

### 8.9 `src/aria/agents/instructions/tests/` (extend)
Static, no model calls.

- `test_aria_md_spawn_example_includes_steps` — read `aria.md`, assert the `worker/spawn` code block contains a non-empty `"steps":` key.
- `test_worker_md_no_longer_says_create_plan` — read `worker.md`, assert it contains **neither** `"Create concrete steps"` **nor** `"Create before any work"` (regression guard against the old re-author instruction, including the line-20 `Additional Tools` bullet; the draft's proposed literal `"Start with plan. Create"` never matched `worker.md` verbatim because of the markdown backticks/asterisks — the stable substrings above are what the file actually says today; mirrors the repo's instruction-content test style in `test_load_agent_instructions.py`).
- `test_ax_reference_worker_spawn_lists_steps_required` — read `ax_commands.md`, assert the `worker` `spawn` row lists `steps` in the Required column. (Aligns with the existing `TestReferenceParity` class.)
- `test_plan_section_template_renders` — import `PLAN_SECTION_TEMPLATE`, format with `{plan_id="P", agent_id="W"}` → contains `"P"` and `"W"` and the step-order verb; `_runner._build_prompt` uses it (assert the prompt output equals the template rendered, not a separate literal).

### 8.10 Manual e2e smoke (not automated)
- Spawn a 3-step worker from the UI; observe `READY → RUNNING → DONE` live in the task list panel.
- Reload the chat: the final `TaskList` state shows from the persisted `elements` row + storage content (no watcher running) — this is the path that relies on the verified frontend behavior (§10). Also reload *while a worker is still running*: re-arm refreshes the same panel (element-id reuse), no duplicate panel.
- On the next user prompt, Aria reads `result.md` and evaluates without re-spawning.

**File budget:** biggest new file ≈ 120 lines (`web/tasklist.py` with `PersistedTaskList`); next ≈ 100 lines (`snapshot.py`); biggest new test file ≈ 80 lines (`test_snapshot.py`). All far under the 600-line cap.

**What is deliberately NOT tested** (would restate the code or pin implementation trivia — AGENTS.md):
- The 1.5 s poll interval value (an implementation constant, not behavior).
- The `"Running {i}/{n}"` progress-branch grammar beyond the §8.5 pin (`"Running 1/3"`) — the per-state values (`Ready`/`Done`/`Failed`/`Cancelled`) are behavior (the zombie-`Failed` mapping is the whole point) and stay pinned; only the arithmetic formatting of the running case is not further pinned.
- That `settle_unfinished_step` iterates `step_number` order (that's the DB's `order_by`, not our logic — `load_plan` already guarantees it).
- Internal `_run_watch` coroutine structure — test through `ensure_watching` + mocked `watch_worker`.

---

## 9. Sequencing

1. **Core**: `aria/supervision/` (`snapshot.py`, `watch.py`) + tests (pure; no UI).
2. **Spawn/runner + instructions (atomic)**: worker `steps` param, plan seeding, runner `--plan-id` + Plan section + `settle_unfinished_step` + manifest; **plus** `aria.md` spawn example, `worker.md` Planning rewrite, `ax_commands.md` Required-`steps`, and `PLAN_SECTION_TEMPLATE`. These four edits **must land in the same commit** as the `steps` param: `aria.md:72` instructs Aria to fetch the worker contract via `ax(family="help", command="lookup", args={"topic": "worker"})` — if `ax_commands.md` still lists `steps` as Optional (or omits it) while `worker()` requires it, Aria following her own lookup instruction hits `missing_steps` on every spawn. The dispatcher parity test (`test_reference_required_args_survive_dispatch`) enforces the reference matches the signature, so a split commit would be red at CI between the two commits. Ship the param, the reference, and both instruction files together.
3. **Adapter**: `web/tasklist.py` (`PersistedTaskList` + `WorkerTaskList`), `web/supervisor.py` (`ensure_watching` + `cancel_all_watchers`), hooks (`on_chat_end` cancel first-statement, `on_chat_resume` re-arm with row reuse) + `message_pipeline` trigger; tests.
4. **Live validation** against the real UI: (a) `READY → RUNNING → DONE` transitions in the side panel while the worker runs; (b) **reload while the worker still runs** — exactly one panel (row id reuse, no duplicate), live updates continue; (c) **reload after completion** — final state rendered from the persisted row; (d) the task chips navigate to the spawning assistant message; (e) inspect the `elements` table between the spawns and the reload to confirm one row per worker, upserted (same `id`) per render.
5. **Docs**: update `AGENTS.md` (note the new `aria/supervision` core module) and `docs/tools-inventory.md` (worker `steps` param under the worker/spawn row).

---

## 10. Risks & mitigations

- **Worker ignores plan-tool instructions** (LLM behavior) → `settle_unfinished_step` on the failure path plus the manifest's DB-derived status (§5.2) guarantee terminal coherence even if mid-run statuses were sloppy; the panel may jump READY→DONE but never lies at the end. `_mark_zombie` settles the zombie case where the runner never runs its own settle.
- **Worker re-authors a plan instead of executing the seeded one** (the `worker.md` "Start with plan. Create…" conflict, §5.7) → the rewritten instruction + runner Plan section both say "execute the existing plan"; `settle_unfinished_step` still settles whatever plan the worker ends up touching, so even a misbehaving worker cannot leave the panel incoherent. The `worker.md` regression test (§8) guards against the old wording returning.
- **Aria omits `steps` and hits `missing_steps`** → `missing_steps` error is the same shape as `missing_prompt` (§5.1), so Aria already knows how to recover; the `aria.md` spawn example (§5.7) makes `steps` visible in the canonical call.
- **Polling cost**: 1 worker = one lightweight `SELECT` (plans + plan_steps) every 1.5 s on local SQLite — negligible; one session per poll avoids file-lock contention.
- **Chainlit `TaskList` persistence** (verified against installed source; the draft's claim that plain `send()` persists the row is **corrected** — this is the mechanism that actually holds): `TaskList` is `type="tasklist"`, but `TaskList.send()` hard-codes `for_id=""` (`element.py:351-353`) and **both** `create_element` implementations skip elements with a falsy `for_id` (chainlit `data/sql_alchemy.py:588-589`; Aria override `src/aria/db/layer.py:435-436`) — a plain `cl.TaskList` writes **no `elements` row** and would be gone on reload. `PersistedTaskList` (§5.4) sends with the spawning message id instead: `Element._create` (`element.py:206-226`) fires `create_element` (Aria's override uploads the `preprocess_content` JSON to storage at `{user_id}/{element.id}/{name}` with `overwrite=True`, re-uploading on every re-send, `layer.py:383,446-449`, and upserts the row `ON CONFLICT (id) DO UPDATE`, `layer.py:413-417`, so one row per element id carries the latest render) and **awaits** `persist_file`, so `send()` never hits its no-url/no-chainlitKey raise (`element.py:249-250`). The row carries pointers only (`objectKey`/`url`/`chainlitKey` — `Element.to_dict` has no `content` field, `element.py:107-124`); the JSON itself lives in the storage provider. On resume, the thread fetch runs `SELECT * FROM elements WHERE "threadId" = :id` with **no `type` filter** (`sql_alchemy.py:303`), so tasklist rows arrive in `ThreadDict.elements` (camelCase keys: `id`, `type`, `name`, `forId`, `objectKey`, `url`, ...; `types.py:49-51`); the Chainlit **frontend** (`frontend/dist/assets/index-*.js`) filters by `type==="tasklist"` and renders the element from the row's storage data — it does **not** rely on a live `cl.TaskList` Python instance (`Element.from_dict` has no `tasklist` branch, falling through to `File`, which the frontend ignores). Net: the final `TaskList` state is shown on resume from the persisted row + storage content, no re-send needed. Two caveats: the `create_element` write is fire-and-forget (a hard shutdown can lose the row — resume row-miss fallback, §4.3.1/§7), and the row is only created when the element is sent with a non-empty `for_id` — the resume row-miss path (`for_id=""` → plain-TaskList behavior) never (re-)creates a lost row.
- **Frontend element merge across sessions** (live-validation only): cross-session re-arming reuses the persisted row's element id (§4.3.1) on the assumption that the frontend's element store merges a `send_element` event carrying an id already present in the thread's elements into one panel (updating it, not appending). Not statically verifiable from the bundled JS with confidence; confirmed in live validation step §9.4(b). If it appends instead, the resume window shows the stale persisted panel plus a live one — cosmetic only, and the row still upserts to the final state.
- **Prompt drift between runner's Plan section and `worker.md`**: single source — `PLAN_SECTION_TEMPLATE` constant used by `_runner._build_prompt` and referenced by `worker.md` (§5.7). The instructions test (§8) asserts the constant exists and the runner renders it.
- **`forId` at Task level + `for_id` at element level**: the in-chat navigation chips come from the per-`Task(forId=output.id)` links; the element-level `for_id=output.id` carried by `PersistedTaskList` exists **solely** to pass the `create_element` `for_id` guard (persistence, §1) and has no visible effect on the side-panel element (the frontend keys tasklists by element, not by message). The plain-`cl.TaskList` behavior (`for_id=""`, `element.py:351-353`, no row) is preserved exactly in the row-miss fallback path, so the two modes differ only in persistence, never in live rendering.
- **Resume of a zombie shows optimistic state**: a worker that died while the web was down is not armed on resume (`find_supervised_workers` excludes dead pids, §5.3); the frontend renders its persisted `TaskList` `content` as-is, which may be the last mid-`running` snapshot (no render-only terminal override on the persisted-content path). The user sees an unfinished panel until they prompt Aria, who reads the audit and corrects the assessment. Accepted — detecting-and-re-rendering zombies on resume would require arming a one-shot watcher for every non-running worker, which is scope creep. The zombie **is** correctly reflected in `worker status`/`worker list` (existing `_list_workers` path, `functions.py:236-240`) when Aria is asked.
- **Evaluation latency**: because the watcher is silent (§4.2 #2, §4.3), the user must send the next prompt for Aria to evaluate a finished worker. If a worker fails while the user is away, the failure is visible in the persisted `TaskList` on the next chat open, but Aria's assessment only runs on the next user message. This is the accepted trade-off for not building a turn-re-injection subsystem.
