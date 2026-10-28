"""Bounded primary-byte retrieval and coordinate ingestion controls."""
import importlib.util
import io
import hashlib
import json
from pathlib import Path
import re
import zipfile

import httpx
import pytest


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / "scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RemoteZip = load_script("qualify_wheat_assets").RemoteZip
catalog = load_script("prepare_wheat_catalog")
parse_boxes = catalog.parse_boxes
retrieve_source = load_script("qualify_wheat_sources").retrieve


def archive_bytes():
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("images/first.png", b"A" * 2048 + bytes(range(256)) * 8)
        z.writestr("images/second.png", b"B" * 8192)
    return out.getvalue()


def ranged_client(data, *, honor=True, corrupt=False):
    def respond(request):
        match = re.fullmatch(r"bytes=(\d+)-(\d+)", request.headers["range"])
        start, end = map(int, match.groups())
        chunk = data[start:end + 1]
        if corrupt:
            chunk = chunk[:-1]  # An exact-range claim cannot excuse missing bytes.
        return httpx.Response(206 if honor else 200, content=chunk if honor else data, headers={"content-range": f"bytes {start}-{end}/{len(data)}"})
    return httpx.Client(transport=httpx.MockTransport(respond))


def test_buffered_random_access_preserves_archive_member_bytes():
    data = archive_bytes()
    with ranged_client(data) as client:
        remote = RemoteZip(client, "https://example.test/data.zip", len(data), budget=len(data) * 5)
        with zipfile.ZipFile(io.BufferedReader(remote, buffer_size=128)) as z:
            assert z.read("images/second.png") == b"B" * 8192
            assert z.read("images/first.png") == b"A" * 2048 + bytes(range(256)) * 8
        assert remote.received < len(data) * 5


@pytest.mark.parametrize("kwargs,reason", [({"honor": False}, "honor exact byte range"), ({"corrupt": True}, "Truncated")])
def test_full_or_truncated_response_is_rejected(kwargs, reason):
    data = archive_bytes()
    with ranged_client(data, **kwargs) as client:
        remote = RemoteZip(client, "https://example.test/data.zip", len(data))
        with pytest.raises(ValueError, match=reason):
            remote.read(20)


def test_read_budget_stops_before_an_unbounded_request():
    data = archive_bytes()
    with ranged_client(data) as client:
        remote = RemoteZip(client, "https://example.test/data.zip", len(data), budget=5)
        with pytest.raises(ValueError, match="budget"):
            remote.read(6)
        assert remote.received == 0


def test_author_targets_are_converted_without_eval_clipping_or_silent_loss():
    assert parse_boxes("2 3 12 15;0 0 1024 1024") == [[2, 3, 10, 12], [0, 0, 1024, 1024]]
    assert parse_boxes("no_box") == []
    for value in ("2 3 2 15", "-1 3 12 15", "0 0 1025 1024", "0 0 nan 2", "__import__('os') 1 2 3"):
        with pytest.raises(ValueError):
            parse_boxes(value)


@pytest.mark.parametrize("changed", [b"pinned sourcf", b"pinned source with extra content", b"short"])
def test_changed_primary_document_is_not_published(tmp_path, changed):
    expected = b"pinned source"
    source = {"name": "primary.txt", "download_url": "https://example.test/primary",
              "bytes": len(expected), "sha256": hashlib.sha256(expected).hexdigest()}
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=changed))) as client:
        with pytest.raises(ValueError):
            retrieve_source(client, tmp_path / "primary.txt", source)
    assert list(tmp_path.iterdir()) == []


def test_existing_primary_document_cannot_be_silently_replaced(tmp_path):
    expected = b"pinned source"
    destination = tmp_path / "primary.txt"
    destination.write_bytes(b"locally changed")
    source = {"name": destination.name, "download_url": "https://example.test/primary",
              "bytes": len(expected), "sha256": hashlib.sha256(expected).hexdigest()}
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(200, content=expected)
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(ValueError):
            retrieve_source(client, destination, source)
    assert calls == []
    assert destination.read_bytes() == b"locally changed"


def test_fixed_discovery_selection_preserves_earlier_receipt_and_rejects_reselection(tmp_path):
    rows = [{"image_name": "later.png", "domain": "Rres_1"},
            {"image_name": catalog.ILLUSTRATION + ".png", "domain": "Rres_1"},
            {"image_name": "000-final.png", "domain": "NMBU_1"}]
    catalog.select_illustration(tmp_path, rows)
    path = tmp_path / "illustration-selection.json"
    first = path.read_bytes()
    catalog.select_illustration(tmp_path, list(reversed(rows)))
    assert path.read_bytes() == first
    changed = json.loads(first)
    changed["image_id"] = "later.png"
    path.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match="retained illustration"):
        catalog.select_illustration(tmp_path, rows)
