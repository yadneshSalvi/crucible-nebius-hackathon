"""CPU-only runtime contract fixtures. No Torch import, model or GPU execution."""
import json
from pathlib import Path
import re
import subprocess
import sys
from types import SimpleNamespace

import pytest

from science.common import ScienceError, digest
from science import wheat_runtime as runtime


class Device:
    def __init__(self, name):
        self.type, _, index = name.partition(":")
        self.index = int(index) if index else None

    def __str__(self):
        return self.type + (":" + str(self.index) if self.index is not None else "")


def fake_torch():
    calls = []

    def record(label, result=None):
        def call(*args):
            calls.append((label, args))
            return result
        return call

    torch = SimpleNamespace(device=Device, float32="float32", version=SimpleNamespace(cuda="13.2", hip=None),
        __config__=SimpleNamespace(show=lambda: "fixture build, not an installed CUDA runtime"),
        set_default_dtype=record("default_dtype"), manual_seed=record("cpu_seed"),
        get_rng_state=record("cpu_rng_get", "cpu-rng"), set_rng_state=record("cpu_rng_set"),
        are_deterministic_algorithms_enabled=lambda: False)
    torch.backends = SimpleNamespace(mps=SimpleNamespace(is_available=record("mps_available", True)),
        cuda=SimpleNamespace(matmul=SimpleNamespace(fp32_precision="tf32")),
        cudnn=SimpleNamespace(fp32_precision="tf32", conv=SimpleNamespace(fp32_precision="tf32"),
            rnn=SimpleNamespace(fp32_precision="tf32"), benchmark=True, version=lambda: 92400), fp32_precision="tf32")
    torch.mps = SimpleNamespace(manual_seed=record("mps_seed"), synchronize=record("mps_sync"),
        get_rng_state=record("mps_rng_get", "mps-rng"), set_rng_state=record("mps_rng_set"))
    properties = SimpleNamespace(name="fixture GPU", uuid="fixture-uuid", total_memory=10, major=9, minor=0)
    torch.cuda = SimpleNamespace(is_available=record("cuda_available", True), device_count=record("cuda_count", 2),
        set_device=record("cuda_select"), synchronize=record("cuda_sync"), manual_seed=record("cuda_seed"),
        get_rng_state=record("cuda_rng_get", "cuda-rng"), set_rng_state=record("cuda_rng_set"),
        get_device_properties=record("cuda_properties", properties), get_arch_list=lambda: ["sm_90"])
    return torch, calls


def test_runtime_import_does_not_import_torch_or_probe_gpu():
    script = """import builtins
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name.split('.')[0] in {'torch', 'torchvision', 'numpy', 'sahi'}:
        raise AssertionError('numerical library imported: ' + name)
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
import science.wheat_runtime
import api.config
import science.wheat_detector
"""
    completed = subprocess.run([sys.executable, "-c", script], cwd=Path(__file__).parents[1], capture_output=True, timeout=10)
    assert completed.returncode == 0, completed.stderr.decode()


def test_settings_keep_existing_devices_and_require_explicit_cuda(monkeypatch):
    from api import config
    monkeypatch.setattr(config, "dotenv_values", lambda _: {})
    monkeypatch.delenv("CRUCIBLE_WHEAT_DEVICE", raising=False)
    monkeypatch.delenv("CRUCIBLE_WHEAT_INFERENCE_DEVICE", raising=False)
    settings = config.Settings.read()
    assert (settings.wheat_device, settings.wheat_inference_device) == ("mps", "cpu")
    monkeypatch.setenv("CRUCIBLE_WHEAT_DEVICE", "cuda")
    monkeypatch.setenv("CRUCIBLE_WHEAT_INFERENCE_DEVICE", "cuda:1")
    settings = config.Settings.read()
    assert (settings.wheat_device, settings.wheat_inference_device) == ("cuda:0", "cuda:1")
    monkeypatch.setenv("CRUCIBLE_WHEAT_DEVICE", "auto")
    with pytest.raises(ValueError, match="explicitly"):
        config.Settings.read()


@pytest.mark.parametrize("name", ["auto", "gpu", "cuda:-1", "cuda:01", "cuda:0,1", "cpu:0", None])
def test_invalid_devices_do_not_probe_hardware_or_fall_back(name):
    torch, calls = fake_torch()
    with pytest.raises(ScienceError) as error:
        runtime.select_device(torch, name)
    assert error.value.code == "WHEAT_HARDWARE"
    assert calls == []


def test_cpu_and_mps_do_not_probe_cuda():
    torch, calls = fake_torch()
    assert str(runtime.select_device(torch, "cpu")) == "cpu"
    assert calls == []
    assert str(runtime.select_device(torch, "mps")) == "mps"
    assert calls == [("mps_available", ())]
    torch.backends.mps.is_available = lambda: False
    with pytest.raises(ScienceError, match="no device fallback"):
        runtime.select_device(torch, "mps")


def test_explicit_cuda_index_is_selected_before_use(monkeypatch):
    monkeypatch.setattr(runtime.platform, "system", lambda: "Linux")
    torch, calls = fake_torch()
    device = runtime.select_device(torch, "cuda:1")
    assert str(device) == "cuda:1"
    assert [name for name, _ in calls] == ["cuda_available", "cuda_count", "cuda_select"]
    assert calls[-1][1] == (device,)


@pytest.mark.parametrize("unavailable", ["platform", "cpu-build", "rocm-build", "driver", "index"])
def test_unavailable_cuda_fails_without_selecting_another_device(monkeypatch, unavailable):
    monkeypatch.setattr(runtime.platform, "system", lambda: "Darwin" if unavailable == "platform" else "Linux")
    torch, calls = fake_torch()
    if unavailable == "cpu-build":
        torch.version.cuda = None
    if unavailable == "rocm-build":
        torch.version.hip = "7.2"
    if unavailable == "driver":
        torch.cuda.is_available = lambda: False
    if unavailable == "index":
        torch.cuda.device_count = lambda: 1
    with pytest.raises(ScienceError) as error:
        runtime.select_device(torch, "cuda:1")
    assert error.value.code == "WHEAT_HARDWARE"
    assert not {"cuda_select", "mps_available"}.intersection(name for name, _ in calls)


def test_cuda_precision_uses_ieee_without_legacy_tf32_or_mixed_precision():
    torch, calls = fake_torch()
    policy = runtime.precision_policy(torch, Device("cuda:1"))
    assert policy["parameters"] == policy["inputs"] == "float32"
    assert policy["autocast_enabled"] is policy["gradient_scaler_enabled"] is policy["tf32_enabled"] is False
    assert torch.backends.fp32_precision == torch.backends.cuda.matmul.fp32_precision == "ieee"
    assert torch.backends.cudnn.fp32_precision == torch.backends.cudnn.conv.fp32_precision == torch.backends.cudnn.rnn.fp32_precision == "ieee"
    assert torch.backends.cudnn.benchmark is False
    assert not hasattr(torch.backends.cuda.matmul, "allow_tf32")
    assert calls == [("default_dtype", ("float32",))]


@pytest.mark.parametrize("override", ["NVIDIA_TF32_OVERRIDE", "TORCH_ALLOW_TF32_CUBLAS_OVERRIDE"])
def test_forced_tf32_environment_is_rejected(monkeypatch, override):
    monkeypatch.setenv(override, "1")
    torch, _ = fake_torch()
    with pytest.raises(ScienceError) as error:
        runtime.precision_policy(torch, Device("cuda:0"))
    assert error.value.code == "WHEAT_PRECISION"


def test_synchronization_targets_only_the_selected_backend_and_device():
    torch, calls = fake_torch()
    runtime.synchronize(torch, Device("cpu"))
    runtime.synchronize(torch, Device("mps"))
    cuda = Device("cuda:1")
    runtime.synchronize(torch, cuda)
    assert calls == [("mps_sync", ()), ("cuda_sync", (cuda,))]


def test_runtime_binding_rejects_changed_device_build_or_precision(tmp_path):
    torch, _ = fake_torch()
    device = Device("cuda:1")
    identity = runtime.runtime_identity(torch, device, runtime.CUDA_PACKAGE_VERSIONS, runtime.precision_policy(torch, device))
    assert runtime.bind_runtime(tmp_path, identity) == digest(identity)
    assert runtime.bind_runtime(tmp_path, identity) == digest(identity)
    assert json.loads((tmp_path / "runtime-binding.json").read_text())["cuda"]["uuid"] == "fixture-uuid"
    for changed in ({**identity, "selected_device": "cpu"}, {**identity, "torch_build_sha256": "changed"},
                    {**identity, "precision": {"parameters": "float16"}}):
        with pytest.raises(ScienceError) as error:
            runtime.bind_runtime(tmp_path, changed)
        assert error.value.code == "IMMUTABLE_CONFLICT"


def test_cuda_identity_rejects_unpinned_runtime_before_hardware_identity():
    torch, calls = fake_torch()
    with pytest.raises(ScienceError) as error:
        runtime.runtime_identity(torch, Device("cuda:0"), {"torch": "different-build"}, {})
    assert error.value.code == "WHEAT_DEPENDENCY"
    assert calls == []


def test_cuda_identity_rejects_unsupported_older_architecture():
    torch, _ = fake_torch()
    torch.cuda.get_device_properties = lambda _: SimpleNamespace(major=7, minor=0)
    with pytest.raises(ScienceError, match="compute capability 7.5"):
        runtime.runtime_identity(torch, Device("cuda:0"), runtime.CUDA_PACKAGE_VERSIONS, {})


@pytest.mark.parametrize("visible,order", [(None, None), ("", ""), ("GPU-fixture", "PCI_BUS_ID")])
def test_runtime_binds_exact_cuda_mapping_including_absent_and_empty(tmp_path, monkeypatch, visible, order):
    for key, value in {"CUDA_VISIBLE_DEVICES": visible, "CUDA_DEVICE_ORDER": order}.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    torch, _ = fake_torch()
    identity = runtime.runtime_identity(torch, Device("cuda:0"), runtime.CUDA_PACKAGE_VERSIONS, {})
    assert identity["cuda"]["device_environment"] == {"CUDA_VISIBLE_DEVICES": visible, "CUDA_DEVICE_ORDER": order}
    runtime.bind_runtime(tmp_path, identity)
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "changed-mapping")
    changed = runtime.runtime_identity(torch, Device("cuda:0"), runtime.CUDA_PACKAGE_VERSIONS, {})
    with pytest.raises(ScienceError, match="runtime-binding"):
        runtime.bind_runtime(tmp_path, changed)


@pytest.mark.parametrize("backend", ["cpu", "mps", "cuda:1"])
def test_selected_backend_rng_roundtrips_without_new_seed(backend):
    torch, calls = fake_torch()
    device = Device(backend)
    snapshot = {**runtime.capture_rng(torch, device), "runtime_binding_sha256": "bound-runtime"}
    calls.clear()
    runtime.restore_rng(torch, device, snapshot, "bound-runtime")
    expected = [("cpu_rng_set", ("cpu-rng",))]
    if device.type == "mps":
        expected.append(("mps_rng_set", ("mps-rng",)))
    if device.type == "cuda":
        expected.append(("cuda_rng_set", ("cuda-rng", device)))
    assert calls == expected


@pytest.mark.parametrize("invalid", ["runtime", "cpu_rng", "cuda_rng"])
def test_incomplete_or_changed_resume_is_rejected_before_rng_mutation(invalid):
    torch, calls = fake_torch()
    snapshot = {"cpu_rng": "cpu-rng", "cuda_rng": "cuda-rng", "runtime_binding_sha256": "bound-runtime"}
    snapshot["runtime_binding_sha256" if invalid == "runtime" else invalid] = None
    with pytest.raises(ScienceError) as error:
        runtime.restore_rng(torch, Device("cuda:1"), snapshot, "bound-runtime")
    assert error.value.code == ("WHEAT_RUNTIME_CHANGED" if invalid == "runtime" else "WHEAT_RNG_MISSING")
    assert calls == []


def test_training_freezes_runtime_before_model_construction(tmp_path, monkeypatch):
    from science import wheat_detector as detector
    torch, _ = fake_torch()
    plan = {"training": detector.TRAINING, "numerical_spec_sha256": digest(detector.SPEC), "seed": 11,
            "device": "cpu", "initialization": {"sha256": "initial-sha"}}
    monkeypatch.setattr(detector, "_libraries", lambda: (torch, None, None, {"torch": "fixture"}))
    monkeypatch.setattr(detector, "read_json", lambda _: {"plan": plan, "initialization": "fixture.pt", "resume_dir": str(tmp_path)})
    monkeypatch.setattr(detector, "file_hash", lambda _: "initial-sha")

    class BeforeModel(Exception):
        pass

    def no_model(*args, **kwargs):
        binding = json.loads((tmp_path / "runtime-binding.json").read_text())
        assert binding["selected_device"] == "cpu"
        assert binding["precision"]["autocast_enabled"] is False
        raise BeforeModel

    monkeypatch.setattr(detector, "_model", no_model)
    with pytest.raises(BeforeModel):
        detector.train_model("unused.json", tmp_path / "output")


def test_linux_lock_retains_direct_versions_and_existing_transitive_constraints():
    root = Path(__file__).parents[1]
    lock = (root / "requirements-wheat-linux-cuda.lock").read_text()
    original = (root / "requirements-wheat.lock").read_text()
    versions = lambda value: dict(re.findall(r"^([a-z0-9-]+)==([^\s\\]+)", value, re.M))
    selected, prior = versions(lock), versions(original)
    assert "--extra-index-url https://download.pytorch.org/whl/cu132" in lock
    assert "--python-platform x86_64-manylinux_2_28" in lock
    for name, version in prior.items():
        assert selected[name].split("+")[0] == version.split("+")[0]
    assert selected["torch"] == "2.14.1+cu132"
    assert selected["torchvision"] == "0.29.2+cu132"
    assert selected["nvidia-cuda-runtime"] == "13.2.86"
    assert selected["nvidia-cudnn-cu13"] == "9.24.0.43"
    for entry in re.split(r"\n(?=[a-z0-9-]+==)", lock)[1:]:
        assert re.search(r"--hash=sha256:[0-9a-f]{64}", entry)
