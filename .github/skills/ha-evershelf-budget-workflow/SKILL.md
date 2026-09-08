---
name: ha-evershelf-budget-workflow
description: Thin budget-aware Home Assistant EverShelf integration workflow preserving complete service wiring, backend ownership, capability/idempotency tests and HACS release requirements.
---

# Integration budget workflow

Use global `budget-workflow` and `.github/agent-budget.json` when available.
Shared tools live under `$HOME/.copilot/skills/budget-workflow/scripts/`.
If unavailable, use direct symbols/ranges and the same bounded workflow.

Use `evidence/research.mjs plan` with the adapter's `evidencePolicy`. Existing
schema/handler questions are repository-only; external HA semantics with local
wiring are hybrid; unrelated public questions are neutral external-only.
Prefer current-owner `init`/`evidence`. Inspect both registered schema and shared
builder before a hybrid contract; they can differ on null/key-presence rules.
Open authoritative external gap evidence before returning for applicability.
No automatic reader agent or inferred backend execution guarantee.

1. Read the root service/release contract. Follow the entire service boundary,
   not just the visible handler. Use `test_recipe_api.py` and
   `test_recipe_services.py` as focused behavioral evidence.
2. Mechanical wiring may use one standard implementation owner. Novel
   capability, authorization, error, or idempotency behavior requires stronger
   reasoning and explicit state/outcome cases.
3. Keep catalog business logic in EverShelf. Keep responses bounded and
   credentials out of URLs, logs, prompts, and evidence.
4. Run affected pytest files/selectors together. Include unload/registration,
   capability failure, replay, transient backend, and todo-mirror behavior
   when affected. Revise once from failures; escalate once if necessary.
5. No live HA service calls as a unit-test shortcut. Release only when
   explicitly approved; a tag alone is not a completed HACS release.

No implicit tandem and no second HydraFusion layer under the coordinator.
