"""Prepare a local, explicitly prompted YOLOE CPU checkpoint; no runtime downloads."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path

def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    args = parser.parse_args()
    assets = args.assets.resolve()
    labels = json.loads(args.labels.read_text())
    if not isinstance(labels, list) or len(labels) != 18 or len(set(labels)) != 18:
        raise ValueError("Expected the 18 ordered labels recorded in the supplied RKNN metadata")
    source = assets / "downloads/yoloe-26s-seg.pt"
    encoder = assets / "downloads/mobileclip2_b.ts"
    directory = assets / "derived"
    directory.mkdir(exist_ok=True)
    inputs = {str(p.relative_to(assets)): sha256(p) for p in (source, encoder, args.labels)}
    versions = {k: importlib.metadata.version(k) for k in ("ultralytics", "torch", "numpy")}
    binding = {"inputs": inputs, "versions": versions, "labels": labels,
               "script_sha256": sha256(Path(__file__)),
               "text_tools_lock_sha256": sha256(assets / "assets.lock.json")}
    receipt_path = directory / "yoloe-derivation.json"
    output = directory / "yoloe-26s-marsdog18.pt"
    if receipt_path.exists():
        previous = json.loads(receipt_path.read_text())
        if previous["binding"] != binding or sha256(output) != previous["output_sha256"]:
            raise ValueError("Existing derived model does not match inputs; use a fresh output directory")
        print(json.dumps({"status": "VERIFIED", "model": str(output)}))
        return
    if output.exists():
        raise FileExistsError(output)
    os.environ.update(CUDA_VISIBLE_DEVICES="", YOLO_AUTOINSTALL="false", YOLO_OFFLINE="true")
    os.chdir(assets / "downloads")  # The fixed text encoder is already present here.
    import torch
    from ultralytics import YOLOE
    torch.set_num_threads(2)
    model = YOLOE(str(source)).to("cpu")
    model.set_classes(labels)
    model.model.end2end = False  # Both supplied RKNN metadata files declare false.
    if list(model.names.values()) != labels:
        raise RuntimeError("Prompt class order changed")
    # Keep only the prompt embeddings in the checkpoint; the preparation-only text
    # encoder/tokenizer must not become an inference dependency.
    if hasattr(model.model, "clip_model"):
        model.model.clip_model = None
    model.save(str(output))
    loaded = YOLOE(str(output))
    if (list(loaded.names.values()) != labels or loaded.model.pe.shape[1] != len(labels)
            or loaded.model.end2end):
        raise RuntimeError("Saved checkpoint lost its prompt labels/embeddings")
    receipt = {"status": "PASS", "binding": binding, "output": str(output),
               "output_sha256": sha256(output), "device": "cpu",
               "scope": "Official same-scale base plus supplied 18 prompts; RKNN weight/quantization parity UNKNOWN"}
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": "PASS", "model": str(output)}))

if __name__ == "__main__":
    main()
