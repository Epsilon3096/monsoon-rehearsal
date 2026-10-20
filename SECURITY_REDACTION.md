# Public-evidence redaction — 20 October 2026

An archived JPS webpage contained a Google Maps API key in a third-party script URL. The initial publication scan missed this credential pattern. GitHub detected it after publication.

The key has been replaced with a redaction marker in the published HTML and rewritten repository history. Three other captured-page browser identifiers (telemetry key, CAPTCHA site identifier and page token) have also been redacted. These are external webpage contents, not Monsoon Rehearsal configuration.

**Monsoon Rehearsal does not require a Google API key.** The archived HTML is inert evidence, not an executed application page. Rehearsal, SWMM calculations, scheduling, comparisons, ticket controls and the guided demonstration work locally without it. The rainfall CSV, station values, hydraulic models and application code were not changed by this cleanup.

`data/public_evidence/manifest-jps-epa.json` records the original response hashes, the new published-copy hashes and each transformation. Original acquisition timestamps remain acquisition timestamps. The published HTML must now be described as a **sanitised copy**, not an exact byte copy of the source response.

The 652-test product result and 23-test fresh-snapshot result remain records of the verified application. The original package-comparison statement predates these public-evidence redactions; the two archived HTML files and their acquisition manifest are additional intentional changes. New cleanup tests separately verify the redactions, current source hashes and unchanged CSV.

Repository cleanup does **not** revoke a credential. Ownership and validity of the external website's key have not been established. No Google credential was used, tested, rotated or revoked, and no alert was marked as revoked. Revocation and provider log review require the actual key owner's access.

Git history was rewritten. Re-clone this repository if you obtained an earlier copy; do not merge old history back into it. The release tag and downloadable source package are refreshed to the sanitised snapshot. Old local research archives remain historical private inputs and must not be redistributed without sanitisation.

GitHub may retain old commit views or copies outside these branch/tag references. Complete removal of those copies can require GitHub Support; this repository does not claim that rewriting history eliminates all prior exposure. See [GitHub's removal guidance](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository).

## Post-cleanup verification

All 31 focused cleanup, public-weather, demonstration and navigation tests passed. They independently confirm that application source hashes, rainfall CSV bytes, original decision evidence and native benchmark bindings are unchanged. The first cleanup attempt caught an incomplete published-copy checksum after a repeated identifier was removed; its failed report is retained as `evidence/v0.9/publication-cleanup-attempt-01.xml`. The manifest was corrected against the original response bytes, and the same checks then passed. No hash check or numerical tolerance was relaxed.
