# Optional Linux CUDA execution software

Status on 2026-10-28: the dependency recipe resolves and CPU-side contract fixtures pass. **Linux/CUDA execution remains unqualified.** No GPU probe, installation, model initialization, fitting, inference or final exposure was performed for this change. The current Mac environment's local Torch-cache `.pth` is not a portable Linux environment.

`requirements-wheat-linux-cuda.lock` targets standard CPython 3.13 on Linux x86_64, glibc 2.28 or newer. It preserves every version in `requirements-wheat.lock` and selects the official CUDA build variants `torch==2.14.1+cu132` and `torchvision==0.29.2+cu132`; NumPy 2.5.4, Pillow 13.0.0 and SAHI 0.12.8 stay fixed. The lock includes the transitive NVIDIA runtime and Triton hashes. Both exact base releases were also checked in official [Torch PyPI metadata](https://pypi.org/pypi/torch/2.14.1/json) and [TorchVision PyPI metadata](https://pypi.org/pypi/torchvision/0.29.2/json). The published [Torch cu132 index](https://download.pytorch.org/whl/cu132/torch/) and [TorchVision cu132 index](https://download.pytorch.org/whl/cu132/torchvision/) supplied the CUDA build hashes. Resolving cu130 failed for the exact TorchVision pin; no version was downgraded.

The lock was generated with uv 0.12.9 using registry/wheel metadata and published hashes, without installing packages or downloading large runtime wheels:

```sh
uv pip compile requirements-wheat.txt --constraint requirements-wheat.lock \
  --python-version 3.13 --python-platform x86_64-manylinux_2_28 \
  --torch-backend cu132 --index https://download.pytorch.org/whl/cu132 \
  --default-index https://pypi.org/simple --index-strategy unsafe-best-match \
  --generate-hashes --only-binary :all: --no-python-downloads --no-cache \
  --emit-index-url --emit-index-annotation \
  --output-file requirements-wheat-linux-cuda.lock
```

The two indexes are official sources. Best-match resolution is constrained by the existing full lock, preventing stale mirror entries from downgrading its packages. A future separately provisioned Linux environment can install with `python3.13 -m pip install --require-hashes --only-binary=:all: -r requirements-wheat-linux-cuda.lock`. Installation and its storage requirements have not been admitted or attempted here.

CUDA selection requires `CRUCIBLE_WHEAT_DEVICE=cuda:0` and, independently, `CRUCIBLE_WHEAT_INFERENCE_DEVICE=cuda:0` if CUDA inference is desired. `cuda` canonicalizes to index zero; `cuda:N` selects one visible device. Defaults remain MPS training and CPU inference. An unavailable CUDA build/device or a changed pinned direct package build stops execution; no replacement device is selected.

Before a future fit, the worker immutably records selected device/index/UUID, hardware capability, Torch build, package/platform identities, CUDA/cuDNN versions and precision in `runtime-binding.json`. It records exact effective `CUDA_VISIBLE_DEVICES` and `CUDA_DEVICE_ORDER` values, distinguishing absent from empty. Its digest accompanies resumable checkpoints, epoch diagnostics and final receipts. Resume requires that identity plus retained CPU and selected-backend RNG states. Old checkpoints missing these bindings fail explicitly. Full FP32 parameters/inputs, disabled autocast/scaling and IEEE matmul/cuDNN settings exclude AMP/TF32 substitution. Measured CUDA boundaries synchronize the selected device, as required by [PyTorch CUDA semantics](https://docs.pytorch.org/docs/2.14/notes/cuda.html). Fixed seeds do not promise bitwise-identical accelerator retraining.

Future host admission must establish all of the following before any scientific run:

- A clean supported Linux x86_64/CPython 3.13 environment with glibc >=2.28 and the hash-locked packages. [PyTorch Linux requirements](https://pytorch.org/get-started/locally/) describe the glibc boundary.
- A supported NVIDIA GPU, at least Turing/compute capability 7.5 for CUDA 13.x; the actual wheel's architectures and TorchVision native NMS/ROIAlign operations still need host qualification. See the [official PyTorch architecture matrix](https://github.com/pytorch/pytorch/blob/main/RELEASE.md#pytorch-cuda-support-matrix).
- A compatible installed NVIDIA driver. This lock's CUDA runtime 13.2.86 corresponds to CUDA 13.2 Update 2; NVIDIA lists Linux driver >=595.71.05 for that toolkit. Its >=580 minor-compatibility floor has restrictions and does not qualify this workflow. Driver version is not supplied by the public Torch identity API and must be separately retained in host qualification. See [NVIDIA's exact release notes](https://docs.nvidia.com/cuda/archive/13.2.2/cuda-toolkit-release-notes/index.html#cuda-driver).
- Existing full-pipeline/checkpoint/replay storage admission and adequate device memory. No storage gate, ResNet50-FPN model, cohort, three seeds, ten epochs or evaluation boundary is relaxed by selecting CUDA.
