"""Stage 6 — export: the trained classifier as an openWakeWord-format ONNX file, checked against torch.

  uv run --no-project --python 3.11 --with numpy==2.4.6 --with onnxruntime==1.30.0 --with onnx==1.19.1 \
      --with torch==2.9.1 --extra-index-url https://download.pytorch.org/whl/cpu python tools/wakeword/export.py

Writes data/model/jarvis.onnx (input [batch, 16, 96] float32, output [batch, 1]) and jarvis.json with its SHA-256,
size, the validation threshold and the validation numbers it came from. (The inputs' pins are in pins.py, not in
jarvis.json.) The file is NEVER committed (R76): the owner publishes it.
"""

from __future__ import annotations

import sys

import numpy as np
import onnxruntime
import torch
from common import DATA, read_json, sha256_file, write_json
from train import EMBED_DIM, N_FEATURES, Classifier

OUT = DATA / "model"


def main() -> int:
    model = Classifier()
    model.load_state_dict(torch.load(OUT / "classifier.pt", weights_only=True))
    model.eval()
    path = OUT / "jarvis.onnx"
    torch.onnx.export(
        model, torch.zeros(1, N_FEATURES, EMBED_DIM), str(path), input_names=["input"], output_names=["output"],
        dynamic_axes={"input": {0: "batch"}, "output": {0: "batch"}}, opset_version=17, dynamo=False,
    )  # fmt: skip
    session = onnxruntime.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    x = np.random.default_rng(1).normal(size=(64, N_FEATURES, EMBED_DIM)).astype(np.float32)
    got = session.run(None, {"input": x})[0]
    want = model(torch.from_numpy(x)).detach().numpy()
    worst = float(np.abs(got - want).max())
    shape = session.get_inputs()[0].shape
    print(f"onnx vs torch max abs diff {worst:.2e}; input shape {shape}")
    if worst > 1e-5 or shape[1] != N_FEATURES:
        sys.exit("export check failed")
    train = read_json(OUT / "train.json")
    write_json(
        OUT / "jarvis.json",
        {
            "file": path.name,
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
            "n_features": N_FEATURES,
            "threshold": train["chosen"]["threshold"],
            "validation": train["chosen"],
        },
    )
    print(f"{path}  {path.stat().st_size} bytes  sha256 {sha256_file(path)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
