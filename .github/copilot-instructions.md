# Repository instructions

## Release process

- When pushing a version bump or release tag for this HACS integration, also create the matching GitHub Release in `SFenton/ha-evershelf`.
- HACS indexes available versions from GitHub Releases, not pushed tags alone. A pushed tag without a GitHub Release will not appear as an available HACS update.
- After publishing the release, confirm HACS sees the new version before considering the release complete.

## Service surface

- Dashboard-facing catalog queries use Home Assistant response services and compact
  payloads. Never expose paginated recipe data as entity attributes.
- New services require a handler, strict voluptuous schema, registration and unload
  entry, coordinator method, `services.yaml`, `strings.json`, and every translation.
- Send the EverShelf token only through `X-API-Token`; never place credentials in
  query strings or log them.
- Recipe query services must pass ranking, filtering, deduplication, and pagination
  through to EverShelf rather than recreating catalog business logic in Home Assistant.
- Recipe detail and grocery services must capability-gate on `recipe_detail_v1`
  and `recipe_grocery_v1`, preserve structured backend errors, and keep responses
  bounded. Treat only a recent successful probe as proof of unsupported status;
  transient probe failures must not erase known-good capabilities.
- Recipe detail must pass backend grocery state/counts and additive ingredient
  fields through unchanged. Home Assistant may only lower
  `detail.capabilities.grocery_add` based on effective `recipe_grocery_v1`
  support, with bounded unsupported/unavailable annotations.
- `recipe_grocery_add` is the single Home Assistant command boundary for both
  EverShelf's internal shopping mutation and the user-facing todo mirror. Trust
  backend outcomes, pre-read and case-fold pending todo names, and never convert
  source amount text into a numeric todo quantity.
- Persist bounded, TTL-limited successful todo mirror outcomes by config entry,
  todo entity, and idempotency key so backend replays remain safe across reloads.
