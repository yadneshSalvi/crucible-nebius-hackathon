"""Explicit detector device, precision and resumable runtime contracts.

This module imports no numerical library and probes no hardware at import time.
CUDA inspection occurs only when an explicitly selected CUDA worker executes.
"""
import os
import platform
import re

from .common import ScienceError, digest, immutable_json

CUDA_PACKAGE_VERSIONS = {"torch": "2.14.1+cu132", "torchvision": "0.29.2+cu132",
                         "numpy": "2.5.4", "pillow": "13.0.0", "sahi": "0.12.8"}


def device_name(name):
    if name in ("cpu", "mps"):
        return name
    if name == "cuda":
        return "cuda:0"
    if isinstance(name, str) and re.fullmatch(r"cuda:(0|[1-9][0-9]*)", name):
        return name
    raise ValueError("Select cpu, mps, cuda or cuda:N explicitly; automatic device fallback is unavailable")


def select_device(torch, name):
    try:
        selected = device_name(name)
    except ValueError as exc:
        raise ScienceError("WHEAT_HARDWARE", str(exc), True) from exc
    if selected == "mps":
        if not torch.backends.mps.is_available():
            raise ScienceError("WHEAT_HARDWARE", "Requested MPS device is unavailable; no device fallback", True)
    elif selected.startswith("cuda:"):
        index = int(selected.split(":")[1])
        if platform.system() != "Linux" or not torch.version.cuda or getattr(torch.version, "hip", None):
            raise ScienceError("WHEAT_HARDWARE", "Requested CUDA requires Linux and a CUDA-enabled Torch build; no device fallback", True)
        try:
            if not torch.cuda.is_available() or index >= torch.cuda.device_count():
                raise RuntimeError("selected CUDA index is unavailable")
            device = torch.device(selected)
            torch.cuda.set_device(device)
        except RuntimeError as exc:
            raise ScienceError("WHEAT_HARDWARE", "Requested " + selected + " is unavailable; no device fallback", True) from exc
        return device
    return torch.device(selected)


def precision_policy(torch, device):
    torch.set_default_dtype(torch.float32)
    policy = {"parameters": "float32", "inputs": "float32", "autocast_enabled": False,
              "gradient_scaler_enabled": False, "tf32_enabled": False,
              "scope": "Full FP32 execution; no AMP, quantization or compiled-model substitution"}
    if device.type == "cuda":
        # Use only the new, pinned Torch 2.14 precision API. Mixing its legacy
        # allow_tf32 flags with fp32_precision is unsupported upstream.
        try:
            if any(os.environ.get(key) == "1" for key in ("NVIDIA_TF32_OVERRIDE", "TORCH_ALLOW_TF32_CUBLAS_OVERRIDE")):
                raise RuntimeError("environment forces TF32")
            torch.backends.fp32_precision = "ieee"
            torch.backends.cuda.matmul.fp32_precision = "ieee"
            torch.backends.cudnn.fp32_precision = "ieee"
            torch.backends.cudnn.conv.fp32_precision = "ieee"
            torch.backends.cudnn.rnn.fp32_precision = "ieee"
            torch.backends.cudnn.benchmark = False
            observed = [torch.backends.fp32_precision, torch.backends.cuda.matmul.fp32_precision,
                        torch.backends.cudnn.fp32_precision, torch.backends.cudnn.conv.fp32_precision,
                        torch.backends.cudnn.rnn.fp32_precision]
            if observed != ["ieee"] * 5:
                raise RuntimeError("IEEE FP32 backend setting did not hold")
        except (AttributeError, RuntimeError) as exc:
            raise ScienceError("WHEAT_PRECISION", "Pinned CUDA runtime cannot enforce IEEE FP32; execution blocked", True) from exc
        policy["cuda_backend_fp32_precision"] = "ieee"
        policy["cudnn_benchmark"] = False
    return policy


def synchronize(torch, device):
    if device.type == "mps":
        torch.mps.synchronize()
    elif device.type == "cuda":
        torch.cuda.synchronize(device)


def runtime_identity(torch, device, environment, precision):
    if device.type == "cuda" and any(environment.get(key) != version for key, version in CUDA_PACKAGE_VERSIONS.items()):
        raise ScienceError("WHEAT_DEPENDENCY", "CUDA execution requires the exact requirements-wheat-linux-cuda.lock direct package builds; no substitute runtime", True)
    identity = {"format": "crucible.wheat-runtime/v1", "selected_device": str(device),
                "environment": dict(environment), "precision": precision,
                "device_fallback": "none",
                "mps_operator_fallback_enabled": device.type == "mps" and os.environ.get("PYTORCH_ENABLE_MPS_FALLBACK") == "1",
                "torch_build_sha256": digest(torch.__config__.show()),
                "deterministic_algorithms_enabled": torch.are_deterministic_algorithms_enabled()}
    if device.type == "cuda":
        properties = torch.cuda.get_device_properties(device)
        if (properties.major, properties.minor) < (7, 5):
            raise ScienceError("WHEAT_HARDWARE", "Pinned CUDA 13.2 build requires Turing (compute capability 7.5) or newer; no device fallback", True)
        identity["cuda"] = {"runtime_version": torch.version.cuda, "cudnn_version": torch.backends.cudnn.version(),
            "device_index": device.index, "name": properties.name, "uuid": str(properties.uuid),
            "device_environment": {key: os.environ.get(key) for key in ("CUDA_VISIBLE_DEVICES", "CUDA_DEVICE_ORDER")},
            "total_memory_bytes": properties.total_memory, "compute_capability": [properties.major, properties.minor],
            "compiled_architectures": torch.cuda.get_arch_list(),
            "driver_version": None, "driver_version_scope": "Not supplied by the public Torch runtime identity API; no compatibility qualification claimed"}
    return identity


def bind_runtime(directory, identity):
    # immutable_json rejects changed device/build/precision before model fitting.
    immutable_json(directory / "runtime-binding.json", identity)
    return digest(identity)


def seed_rng(torch, device, seed):
    torch.manual_seed(seed)
    if device.type == "mps":
        torch.mps.manual_seed(seed)
    elif device.type == "cuda":
        torch.cuda.manual_seed(seed)


def capture_rng(torch, device):
    return {"cpu_rng": torch.get_rng_state(),
            "mps_rng": torch.mps.get_rng_state() if device.type == "mps" else None,
            "cuda_rng": torch.cuda.get_rng_state(device) if device.type == "cuda" else None}


def restore_rng(torch, device, resume, runtime_sha256):
    if resume.get("runtime_binding_sha256") != runtime_sha256:
        raise ScienceError("WHEAT_RUNTIME_CHANGED", "Resume checkpoint does not bind this selected device/runtime/precision; no fit resumed", True)
    backend_key = {"mps": "mps_rng", "cuda": "cuda_rng"}.get(device.type)
    if resume.get("cpu_rng") is None or (backend_key and resume.get(backend_key) is None):
        raise ScienceError("WHEAT_RNG_MISSING", "Resume checkpoint lacks the selected backend RNG state; no fresh-seed fallback", True)
    torch.set_rng_state(resume["cpu_rng"])
    if device.type == "mps":
        torch.mps.set_rng_state(resume["mps_rng"])
    elif device.type == "cuda":
        torch.cuda.set_rng_state(resume["cuda_rng"], device)
