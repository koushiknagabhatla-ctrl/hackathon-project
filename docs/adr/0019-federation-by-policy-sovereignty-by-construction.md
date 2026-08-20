# 0019 — Federation by policy, sovereignty by construction

**Status:** Accepted in design; single-tenant in this build

## Context
Vijayawada does not act alone. A Budameru event involves the NTR district
administration, the Krishna district administration, APSDMA, the irrigation
department operating the Velagaleru regulator, and CWC forecasts for the Krishna
at Prakasam Barrage. Sharing is necessary. Sharing everything is not, and in
India the data-residency and purpose-limitation constraints are statutory (see
`docs/compliance-map.md`).

## Decision
Two separate mechanisms, deliberately not merged:

**Sovereignty is structural.** Every row that matters carries `tenant_id`.
`tenant` carries `jurisdiction` and `data_region`. `repo.py` takes `tenant_id`
as a **required positional argument** on every list function — there is no
default tenant, so a missing tenant is a `TypeError` at the call site rather
than a silent cross-tenant read. `bundle::TENANT_MATCH` denies when principal
tenant, resource tenant or target asset tenant disagree. Cross-tenant read is
not a permission that can be granted; it is a shape the code does not have.

**Federation is a policy decision, evaluated per action.**
`bundle::GEOFENCE` compares `asset_jurisdiction` against the principal's
`principal_jurisdictions` list and denies action outside it, naming both. A
principal with no jurisdiction restriction is unrestricted — restriction is
opt-in per principal, which is the right default for a single-city deployment
and the wrong one for a federation (see trigger).

The distinction matters: sovereignty answers "may this data leave", federation
answers "may this actor act here". Merging them produces the common failure
where a sharing agreement quietly becomes an authority grant.

## What this build actually does
The tenancy model, `TENANT_MATCH` and `GEOFENCE` are implemented and enforced.
`data_region` defaults to `'eu-west'` in `schema.sql` — for a Vijayawada
deployment that is wrong and must be set to an India region; it is currently a
column with no enforcement behind it (no storage routing, no egress control).

The seed is a **single tenant**. Cross-tenant federation, share agreements,
per-share redaction and residency enforcement are designed, not built.

## Consequences
- Cross-tenant leakage requires a code change, not a misconfiguration.
- Jurisdiction is enforced at the action, so a mutual-aid principal from a
  neighbouring district can read shared evidence without gaining the authority
  to act on assets outside their geofence.
- Cost: `tenant_id` threads through every signature and every query. That
  verbosity is the guarantee.
- `data_region` is presently documentation, not a control. Stated so nobody
  cites it as one.

## Earned-complexity trigger
Build real federation at the **second tenant**. That is the trigger, and it is
binary. Minimum required at that point:
- explicit share agreements as data (which tenant, which subject classes, which
  purpose, which expiry) evaluated by a policy rule, not a join;
- per-share redaction on read, not on write;
- `principal_jurisdictions` sourced from the identity provider rather than a
  principal column, and **default-deny** instead of the current default-allow
  when the list is empty;
- `data_region` backed by actual storage placement and an egress control, with
  the DPDP Act cross-border transfer position resolved in writing.
