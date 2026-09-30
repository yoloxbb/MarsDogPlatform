# Developer platform acceptance

Source: 2468639054763398882366bad7869236c0d2e68e. Result: PASS_WITH_EXPLICIT_LIMITS.

This snapshot records the actual P7 developer CLI and internal source handoff verification.
Read summary.json for scopes, counts, skip reasons, host assumptions and command receipts.
commands/*/execution.json records command, checkout, UTC time, commit, dirty state, exit and duration.
Existing-checkout validation preceded the source commit; the clean bundle clone re-ran the same tools.

Five independent setups/tests and clean wheel installs passed. Emotion reports 218 tests and
156 subtests (374 JUnit entries); do not sum that with the 218. Voice pure and Humble overlap.
Action retains 29 optional/ROS skips; Vision retains three RGA parity skips.
The 25 contract cases and six per-module interface cases also overlap, not extra business tests.

Both existing and freshly rebuilt default ROS profiles passed doctor/smoke. The fresh build
was created under /tmp/marsdog-developer-platform-2468639. This is a new checkout/build on
an already-provisioned x86_64 Humble host, not a new OS or board installation.
uv and hash-verified deb download caches were explicitly shared; no old source imports,
virtual environments or build/install trees were reused. The four pinned vendor source trees
were materialized from the two bundled archives. SLAM extensions were not rebuilt this time.

Lifecycle fault injection intentionally records a child_crash run as FAIL; the containing gate
passes only when that failure is propagated and owned PIDs are reaped. Platform unit-test logs
also contain intentionally rejected FAIL fixtures. These are expected assertions, not hidden failures.

No hardware, model quality, hosted CI, board ABI or external distribution approval is claimed.
Historical validation snapshots and all robot behavior/IDL/configuration remain unchanged.
source-bundle-manifest.json names the code baseline used for acceptance. A final local source
bundle can include this evidence/docs-only follow-up; compare its manifest for the delivery HEAD.
