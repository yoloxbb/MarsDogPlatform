"""Bootstrap a hash-pinned uv executable inside migration only (Linux x86_64)."""
from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path
import platform
import urllib.request
import zipfile

ROOT = Path(os.environ.get("MARSDOG_MIGRATION_WORKSPACE", Path(__file__).resolve().parents[1])).resolve()
VERSION = "0.12.19"
SHA256 = "a63d18a0aa38ee9f21a5406afbbaeb41303bcd954be9d6b7c1b95ac275e53958"
URL = (
    "https://files.pythonhosted.org/packages/76/71/"
    "b47cec536d8ee7b09017c1d9db211dfc2e7ce5c87d0482918d8b3411ec48/"
    "uv-0.12.19-py3-none-manylinux_2_17_x86_64.manylinux2014_x86_64.whl"
)


def main() -> None:
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise SystemExit("This bootstrap is pinned for the P1 Linux x86_64 host only.")
    destination = ROOT / ".tools" / "uv"
    with urllib.request.urlopen(URL, timeout=60) as response:
        payload = response.read()
    if hashlib.sha256(payload).hexdigest() != SHA256:
        raise SystemExit("uv wheel checksum mismatch")
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        candidates = [n for n in archive.namelist() if n.endswith("/scripts/uv")]
        if len(candidates) != 1:
            raise SystemExit("Expected exactly one uv executable in pinned wheel")
        executable = archive.read(candidates[0])
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp")
    temporary.write_bytes(executable)
    temporary.chmod(0o755)
    temporary.replace(destination)
    print(f"Installed uv {VERSION}: {destination}; verified wheel sha256={SHA256}")


if __name__ == "__main__":
    main()
