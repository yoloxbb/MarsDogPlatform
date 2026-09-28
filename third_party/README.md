# Fixed external sources

The lock pins exact local Git trees and verified all-ref bundles. Original histories
remain intact outside the platform; implementations materialize under ignored .external.
Run python3 tools/materialize_vendors.py --archive-dir /path/to/archives.
The archive directory is an explicit portable input; no original checkout is required.
Existing trees are verified, never overwritten. Preserve/export these bundles with a release.

OpenVINS, VINS-Fusion, Ubitraq UWB, and the complete modified RTAB-Map tree retain
their original license files and package names. UWB ARM64 proprietary-library details
remain UNKNOWN; CPU tests use the existing test stub only. Voice also retains its
historical ARM64 librkllmrt.so; redistribution provenance is UNKNOWN and it is never
executed by the x86 profile. No unknown legacy implementation is retired.
