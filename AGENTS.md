# MarsDog platform working rules

- Read README.md and the relevant module migration record in docs/migration before changing implementation.
- Main-repository migration is established. New development belongs here; do not restart repository moves.
- Read CONTRIBUTING.md and docs/development/WORKFLOW.md. Do not invent hardware behavior.
- Preserve Python namespaces, ROS package/type/endpoint names, default configuration,
  cancellation lifecycle and demand settlement semantics.
- Do not import another module's private implementation or put business logic in common.
- Keep each Python module's pyproject/lock/environment independent.
- Do not upgrade algorithms, ROS, model runtimes or protocol versions as part of file moves.
- Tests must not connect to hardware or production ROS domains. Pure tests and real
  ROS transport tests have distinct reports; skips are not passes.
- Preserve original source repositories, archives and commit maps. Never filter/reset
  an original repository. Work on copies and record provenance.
- Use tools/dev.py check, affected module tests and the test matrix in docs/development/WORKFLOW.md.
- Versioned migration tooling lives in integration/migration. The sibling legacy
  migration directory is the retained verification workspace, not a second source
  of business logic. MARSDOG_MIGRATION_WORKSPACE applies only to historical migration tools;
  active preparation uses explicit --archive-dir / MARSDOG_ARCHIVE_DIR (default .cache/vendor-archives).
- Human confirmation is needed for incompatible interfaces, robot behavior changes,
  unknown production-code retirement, irreversible history/data removal, or new
  motion-control/embedded protocols. Ordinary engineering fixes do not need approval.
- Voice/Vision/Emotion/Behavior/Action compatibility refactoring R1–R4 is complete; see docs/architecture/COMPATIBILITY_REFACTOR.md and interfaces/application/README.md. Preserve frozen contracts and component boundaries in subsequent development. Navigation/avoidance internals remain with their owner. P7 developer/source delivery is complete.
- Model precision and absent hardware do not block software integration. Preserve honest acceptance limits.
