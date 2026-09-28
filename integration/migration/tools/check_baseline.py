"""Verify files, modes, HEADs, index and worktree status without changing Git."""
import json
from baseline_lib import verify_sources

if __name__ == "__main__":
    result = verify_sources()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] == "PASS" else 1)
