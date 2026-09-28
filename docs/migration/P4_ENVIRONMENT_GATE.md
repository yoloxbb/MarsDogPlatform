# P4 environment gate

Status: BLOCKED on dependency availability; Vision and Voice have not been imported.
Date: 2026-09-28. Originals and their locks are unchanged.

The original pure source snapshots are under the retained migration workspace.
ROS CMake builds alone passed in P1, but they do not install the Python inference
dependencies or certify complete unit/model behavior.

| Module | Locked environment command | Observed blocker |
| --- | --- | --- |
| Vision | uv sync --locked --no-install-project --extra dev --python /usr/bin/python3.10 | Uncached torch==2.13.0 required through ultralytics==8.4.118 |
| Voice | uv sync --locked --no-install-project --extra dev --python /usr/bin/python3.10 | Uncached sherpa-onnx-core==1.13.3 |

Offline attempts failed explicitly, with logs under validation/p4-environment.
Online uv for the separate Action editable build also timed out; Action could use
its cached ordinary-wheel build instead. Five-second urllib probes to pypi.org,
pypi.tuna.tsinghua.edu.cn and mirrors.tuna.tsinghua.edu.cn PyPI endpoints each timed
out during TLS handshake. The previously fetched Nav2 artifact does not imply these
Python sources are reachable now. Exact network root cause UNKNOWN.

The host has system cv2/scipy/numpy, but lacks FastAPI, httpx, Torch, sherpa_onnx and
pypinyin. Using that unrelated system environment would not verify original locks.
No pins were weakened, no packages installed system-wide, and no models were invented.

Resume with accessible original lock artifacts or a hash-verified offline cache,
then run baseline tests before any module import. Full models/NPU/audio/camera
acceptance remains a separate hardware gate after software regression. Production
profile facts requested from the user are still needed for final system acceptance.
