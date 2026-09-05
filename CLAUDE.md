# CLAUDE.md — HydraSense Hard Constraints

**This file is the single source of truth for all coding-session constraints.**
Every session that touches this repo must read this file before writing any code.
If anything in chat history or another document conflicts with this file, this file wins.
SRS.md (in /docs/) supersedes even this file on factual/specification matters.

---

## Hard Constraints (Section 26 of SRS.md — verbatim)

- Pilot scope: Wayanad only, 4 named villages (Mundakkai, Chooralmala, Attamala,
  Punjirimattom), H3 resolution 8-9. Hex count is whatever the grid generator produces for
  those 4 villages — never hardcode "4 hexes." Never expand scope to another region without
  explicit team sign-off.

- Model: XGBoost only. Never suggest or implement PSO-BP, under any circumstances.

- Frontend map: Leaflet only. Terrain library: pysheds only. No alternatives, no debate.

- Never build: exposure/population/routing layer, real GSI/SAsiaFFGS API integration, NASA
  SMAP integration, district/state-wide coverage, a live-recomputed LOEO validator.

- Soil moisture: NASA POWER only. soil_saturation_ratio = GWETROOT directly.

- Feature naming: antecedent_precipitation_index, never api_score.

- risk_score = P(Green)*15 + P(Yellow)*42 + P(Orange)*64 + P(Red)*88 (from XGBoost
  predict_proba); tier is derived from risk_score, never predicted separately.

- Lead-time horizons: hourly only (t+1h, t+2h, ...). Never sub-hour interpolation.

- Alert dedup: fire only on tier increase past the last alert, or after a 30-min cooldown at
  the same tier. Downgrades log an event, never a new alert, and require 2 consecutive
  below-Orange cycles before "resolved."

- Any external API call needs a timeout + fallback, visibly labeled in code and (where
  user-facing) in the UI — never a silent mock standing in for real data.

- Wording: "soil saturation proxy" (never "village-level measurement"), "external-data-only
  estimate" (never "satellite-only").

- Schema (SRS.md Section 14) and API contracts (SRS.md Section 15) are frozen — do not alter
  field names or add/remove tables without flagging it for team review first.

- SRS.md is the single source of truth. If any other document or chat history conflicts with
  it, SRS.md wins and the other document should be corrected to match.

---

## Additional Team Rules (2-person build)

- Never commit directly to `main`. Branch naming: `phase-<n>-<short-desc>`.
- `git pull origin main` before starting any branch. Confirm no uncommitted changes first.
- Dev A owns Phases 1, 3, 5, 8, 9, 11. Dev B owns Phases 2, 4, 6, 7, 10, 12.
- Phase 8 depends on Phase 6 (Dev B). Phase 9 depends on Phase 7 (Dev B).
  If those are not merged to main, stop and flag — do not stub/mock missing models.
- Never touch /ml/models/train_fusion_model.py, /ml/validation/, or /frontend/ unless you
  are explicitly assigned to that phase.
- Commit messages must reference phase number and SRS.md section.
  Example: "Phase 5: implement infinite-slope FS equation per SRS.md Sec 10.1"
- Never modify schema (SRS §14) or API contracts (SRS §15) without flagging to the team first.
- On merge conflict or a file that looks like the other dev changed it: STOP, report, do not
  auto-resolve.
- Open a PR into main when the phase's acceptance criteria (SRS §25) are met. Do not
  self-merge — the other dev reviews first.
