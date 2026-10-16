"""Select the pinned, project-built Fast DDS runtime when it is installed."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping
from pathlib import Path

FAST_DDS_VERSION = "2.6.12"
FAST_DDS_PREFIX_ENV = "MARSDOG_FASTDDS_PREFIX"
FAST_DDS_DISABLE_ENV = "MARSDOG_FASTDDS_DISABLE_OVERLAY"
DEFAULT_PREFIX = Path.home() / ".local" / "opt" / "marsdog-fastdds-2.6.12"


def _library_directory(prefix: Path) -> Path | None:
    for candidate in (prefix / "lib", prefix / "lib64", prefix / "lib" / "aarch64-linux-gnu"):
        if (candidate / "libfastrtps.so.2.6").is_file():
            return candidate
    return None


def fastdds_overlay_environment(
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return environment updates that prefer the patched 2.6.12 library.

    The default overlay is optional until installed. An explicitly selected
    prefix must contain the expected Fast DDS 2.6 shared library so a typo
    cannot silently leave a process on the unfixed system runtime.
    """

    values = os.environ if environ is None else environ
    explicit_prefix = values.get(FAST_DDS_PREFIX_ENV)
    prefix = Path(explicit_prefix).expanduser() if explicit_prefix else DEFAULT_PREFIX
    existing = values.get("LD_LIBRARY_PATH", "")
    entries = existing.split(":") if existing else []

    if values.get(FAST_DDS_DISABLE_ENV) == "1":
        library_directory = _library_directory(prefix) if prefix.exists() else None
        if library_directory is None:
            return {}
        library_path = str(library_directory)
        filtered_entries = [entry for entry in entries if entry != library_path]
        if filtered_entries != entries:
            return {"LD_LIBRARY_PATH": ":".join(filtered_entries)}
        return {}

    if not explicit_prefix and not prefix.exists():
        return {}

    library_directory = _library_directory(prefix)
    if library_directory is None:
        if explicit_prefix:
            raise FileNotFoundError(
                f"{FAST_DDS_PREFIX_ENV}={prefix} does not contain Fast DDS {FAST_DDS_VERSION}"
            )
        raise FileNotFoundError(
            f"Fast DDS overlay exists at {prefix} but libfastrtps.so.2.6 is missing"
        )

    library_path = str(library_directory)
    entries = [entry for entry in entries if entry != library_path]
    entries.insert(0, library_path)
    return {"LD_LIBRARY_PATH": ":".join(entries)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--print-library-path",
        action="store_true",
        help="print LD_LIBRARY_PATH after applying the optional Fast DDS overlay",
    )
    args = parser.parse_args()
    try:
        updates = fastdds_overlay_environment()
    except FileNotFoundError as error:
        print(error, file=sys.stderr)
        return 2

    if args.print_library_path:
        print(updates.get("LD_LIBRARY_PATH", os.environ.get("LD_LIBRARY_PATH", "")))
    else:
        os.environ.update(updates)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
