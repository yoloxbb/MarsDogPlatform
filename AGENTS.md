# MarsDog platform working rules

- Read README.md and docs/migration/P2_EMOTION.md before changing implementation.
- This is a partial migration. Do not invent missing modules or hardware behavior.
- Preserve Python namespaces, ROS package/type/endpoint names, default configuration,
  cancellation lifecycle and demand settlement semantics.
- Do not import another module's private implementation or put business logic in common.
- Keep each Python module's pyproject/lock/environment independent.
- Do not upgrade algorithms, ROS, model runtimes or protocol versions as part of file moves.
- Tests must not connect to hardware or production ROS domains. Pure tests and real
  ROS transport tests have distinct reports; skips are not passes.
- Preserve original source repositories, archives and commit maps. Never filter/reset
  an original repository. Work on copies and record provenance.
- Use the module tests and clean-install probe from README.md for Emotion changes.
- Human confirmation is needed for incompatible interfaces, robot behavior changes,
  unknown production-code retirement, irreversible history/data removal, or new
  motion-control/embedded protocols. Ordinary engineering fixes do not need approval.
