"""Install the version-matched RKNN runtime beside rknnlite on Linux AArch64."""

from __future__ import annotations

import hashlib
from importlib import metadata
import platform
from pathlib import Path
import sys
from urllib.error import URLError
from urllib.request import urlopen


RKNN_LITE_VERSION = "2.3.2"
RUNTIME_URL = (
    "https://raw.githubusercontent.com/airockchip/rknn-toolkit2/v2.3.2/"
    "rknpu2/runtime/Linux/librknn_api/aarch64/librknnrt.so"
)
RUNTIME_SHA256 = "d31fc19c85b85f6091b2bd0f6af9d962d5264a4e410bfb536402ec92bac738e8"


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    if sys.platform != "linux" or platform.machine().lower() not in {"aarch64", "arm64"}:
        print("Skipping RKNN runtime install: this environment is not Linux AArch64.")
        return 0

    try:
        installed_version = metadata.version("rknn-toolkit-lite2")
    except metadata.PackageNotFoundError as exc:
        raise SystemExit(
            "rknn-toolkit-lite2 is not installed in this Python environment; "
            "run the locked Vision environment sync first."
        ) from exc
    if installed_version != RKNN_LITE_VERSION:
        raise SystemExit(
            f"Expected rknn-toolkit-lite2 {RKNN_LITE_VERSION}, found {installed_version}; "
            "update the pinned runtime installer together with the module lock."
        )

    try:
        import rknnlite
    except ImportError as exc:
        raise SystemExit(
            "rknn-toolkit-lite2 metadata exists, but rknnlite cannot be imported"
        ) from exc

    destination = Path(rknnlite.__file__).resolve().parent / "api" / "librknnrt.so"
    if destination.is_file():
        existing_hash = sha256_bytes(destination.read_bytes())
        if existing_hash == RUNTIME_SHA256:
            print(f"RKNN runtime already installed: {destination} (sha256 verified)")
            return 0
        raise SystemExit(
            f"Refusing to replace an existing RKNN runtime with an unexpected hash: "
            f"{destination} ({existing_hash}). Check it against the board SDK."
        )

    try:
        with urlopen(RUNTIME_URL, timeout=60) as response:
            payload = response.read()
    except (OSError, URLError) as exc:
        raise SystemExit(
            f"Could not download the pinned RKNN {RKNN_LITE_VERSION} runtime from "
            f"{RUNTIME_URL}: {exc}"
        ) from exc

    downloaded_hash = sha256_bytes(payload)
    if downloaded_hash != RUNTIME_SHA256:
        raise SystemExit(
            "Downloaded RKNN runtime failed SHA256 verification: "
            f"expected {RUNTIME_SHA256}, got {downloaded_hash}"
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    try:
        temporary.write_bytes(payload)
        temporary.chmod(0o644)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)

    print(
        f"Installed RKNN runtime {RKNN_LITE_VERSION}: {destination}; "
        f"sha256={downloaded_hash}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
