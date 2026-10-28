from __future__ import annotations

import html
import hashlib
import io
import json
import zipfile
from pathlib import Path

from .config import PROJECT
from .store import Conflict, Store, canonical, now


def report(folio: dict) -> str:
    esc = lambda x: html.escape(str(x))
    conclusion = folio.get("conclusion") or {}
    source = folio.get("source") or {}
    contract = folio["contract"]
    scope = conclusion.get("scope")
    if isinstance(scope, dict):
        condition = next((c["label"] for c in contract.get("allowed_conditions", []) if c["id"] == scope.get("condition_id")), scope.get("condition_id", "Unspecified"))
        scope_text = f"{condition}. {'Within the original scope' if scope.get('classification') == 'in_scope' else 'Applicability test outside the original scope'}. {scope.get('population', '')} Registered superiority margin: {contract.get('practical_delta', 0) * 100:.2f} percentage points."
    else:
        scope_text = scope or ""
    candidate_name = (contract.get("candidate") or {}).get("name", "Candidate")
    baseline_name = (contract.get("baseline") or {}).get("name", "Baseline")
    method_sections = []
    parameter_labels = {"n_estimators": "Trees", "max_depth": "Maximum depth", "min_samples_leaf": "Minimum leaf samples", "max_features": "Feature sampling", "class_weight": "Class weights", "n_jobs": "Worker threads", "max_iter": "Maximum iterations", "tol": "Tolerance", "fit_intercept": "Fit intercept", "C": "Regularization C"}
    for method in (contract.get("candidate") or {}, contract.get("baseline") or {}):
        parameters = "".join(f"<dt>{esc(parameter_labels.get(key, key.replace('_', ' ').capitalize()))}</dt><dd>{esc(value)}</dd>" for key, value in (method.get("parameters") or {}).items())
        method_sections.append(f"<h3>{esc(method.get('name', 'Method'))}</h3><dl class='parameters'>{parameters}</dl>")
    registration = folio.get("registration") or {}
    replay_html = ""
    if registration.get("holdout_status") == "reproducibility_replay":
        prior = str(registration.get("prior_folio_id") or "previously registered folio")
        from urllib.parse import quote
        replay_html = f"<p class='replay-note'><strong>Registered reproducibility replay.</strong> These labels were already registered in folio {esc(prior)}. This run checks agreement with the original condition; it is not fresh confirmation. <a href='http://127.0.0.1:4201/?folio={quote(prior, safe='')}&amp;stage=folio'>Open the prior folio in the local workbench</a>.</p>"
    rows = []
    def measurement(value, difference=True):
        return "Not estimable" if value is None else f"{value * 100:.2f}{' pp' if difference else '%'}"
    for o in folio["observations"]:
        block_counts = f"{o.get('blocks', '—')} / {o.get('total_blocks', '—')}"
        row_counts = f"{o.get('analyzed_rows', '—'):,} / {o.get('rows', 0):,}" if isinstance(o.get('analyzed_rows'), int) else f"Not reported / {o.get('rows', '—')}"
        rows.append("<tr>" + "".join(f"<td>{esc(v)}</td>" for v in [o.get("phase"), o.get("condition_label"), measurement(o.get("candidate"), False), measurement(o.get("baseline"), False), measurement(o.get("effect")), f"{measurement(o.get('ci_low'))} to {measurement(o.get('ci_high'))}", block_counts, row_counts]) + "</tr>")
    checks = "".join(f"<li><strong>{esc(c.get('name'))}</strong>: {'Passed' if c.get('passed') else 'Rejected'} — {esc(c.get('detail', ''))}</li>" for c in (folio.get("verification") or {}).get("checks", []))
    receipts = "".join(f"<tr><td>{esc(r.get('purpose'))}</td><td>{esc(r.get('provider'))}</td><td>{esc(r.get('model') or '—')}</td><td>{esc(r.get('status'))}</td><td>{esc(r.get('input_tokens') if r.get('input_tokens') is not None else 'Unknown')}</td><td>{esc(r.get('output_tokens') if r.get('output_tokens') is not None else 'Unknown')}</td><td>{esc(r.get('request_id') or 'Not supplied')}</td></tr>" for r in folio.get("receipts", []))
    limitations = "".join(f"<li>{esc(x)}</li>" for x in list(dict.fromkeys(folio.get("limitations", []) + conclusion.get("limitations", []))))
    concise_limits = ["Authored comparison only; the original paper protocol, external methodologist qualification and a frozen benchmark study are not completed.",
                      "Separate trusted predictor/verifier processes share one OS identity. Arbitrary imported code is disabled; a hardened security sandbox is not claimed.",
                      "Seeds describe training variability. Descriptive intervals are not Holm-adjusted simultaneous intervals; inconclusiveness is not equivalence.",
                      "UCI calendar-day independence is unestablished, and public labels may be historically known." if folio["adapter_id"] == "occupancy" else "Controlled synthetic groups exercise a known generator. They do not establish validity on real-world research populations."]
    concise_html = "".join(f"<li>{esc(value)}</li>" for value in concise_limits)
    evidence = folio.get("evidence_change")
    evidence_html = "<p>No runtime evidence change was recorded.</p>"
    if evidence:
        e_source = evidence.get("source") or {}
        evidence_html = f"<p><strong>{esc(evidence['status'])}</strong>. {esc(evidence['explanation'])}</p><p>Query: {esc(evidence['query'])}</p><p>Before: {esc(', '.join(evidence['before']))}<br>After: {esc(', '.join(evidence['after']))}</p>"
        if e_source.get("url"):
            evidence_html += f"<p><a href='{esc(e_source['url'])}'>{esc(e_source.get('title'))}</a>: {esc(e_source.get('excerpt'))}</p>"
    source_link = f"<a href='{esc(source['url'])}'>{esc(source.get('title'))}</a>" if source.get("url") else esc(source.get("title", "Authored controlled source"))
    return f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(folio['title'])} · Crucible evidence folio</title>
<style>body{{margin:0;background:#F5F1E8;color:#172D38;font:16px/1.65 Georgia,serif}}main{{max-width:1000px;margin:0 auto;padding:48px 24px}}header{{border-top:4px solid;padding-top:16px}}.eyebrow,th,small{{font-family:system-ui,sans-serif}}.eyebrow{{letter-spacing:.12em;text-transform:uppercase;font-size:12px}}h1{{font-size:46px;line-height:1.12;max-width:760px}}h2{{border-top:1px solid #CBD0CC;padding-top:28px;margin-top:36px}}a{{color:#244CB1}}table{{border-collapse:collapse;width:100%;font:13px/1.5 system-ui,sans-serif}}td,th{{text-align:left;padding:10px 8px;border-bottom:1px solid #CBD0CC;vertical-align:top}}.table{{overflow:auto}}code,pre{{font:12px/1.6 monospace;overflow-wrap:anywhere;white-space:pre-wrap}}.verdict{{font-size:23px;border-left:4px solid #147066;padding:12px 24px}}dt{{font-weight:bold}}dd{{margin:0 0 14px}}@media print{{body{{background:white}}main{{padding:0}}a{{color:inherit}}}}</style>
<main><header><div class="eyebrow">Crucible / Portable evidence folio / {esc(folio['case_kind'].replace('_',' '))}</div><h1>{esc(folio['title'])}</h1><p>{esc(folio['claim'])}</p><small>Exported {esc(now())}. Folio {esc(folio['id'])}; contract revision {contract.get('revision',1)}.</small></header>
<h2>Bounded conclusion</h2><p class="verdict">{esc(conclusion.get('statement', 'No independently verified conclusion is available.'))}</p><p>Outcome: <strong>{esc(conclusion.get('outcome', 'not_testable').replace('_', ' '))}</strong>. {esc(scope_text)}</p>
<h2>Source and registered protocol</h2><p>{source_link}. {esc(source.get('attribution', ''))} · {esc(source.get('license', ''))}</p><dl><dt>Population</dt><dd>{esc(contract.get('population'))}</dd><dt>Methods</dt><dd>{esc(candidate_name)} versus {esc(baseline_name)}. Exact fixed parameters are retained in evidence.json.</dd><dt>Split</dt><dd>{esc(contract.get('split'))}</dd><dt>Analysis</dt><dd>{esc(contract.get('analysis'))}</dd><dt>Preprocessing</dt><dd>{esc(contract.get('preprocessing'))}</dd></dl><p>Contract digest <code>{esc(contract.get('sha256'))}</code></p>
<details><summary>Fixed method parameters and seeds</summary>{''.join(method_sections)}<p>Training seeds: {esc(', '.join(str(s) for s in contract.get('seeds', [])))}</p></details>
<h2>Measured evidence</h2><p>Effect = candidate − baseline; positive favors the candidate. Balanced accuracy is higher-is-better. Seeds describe training variability, not independent datasets. Intervals are descriptive, not Holm-adjusted confidence intervals.</p><div class="table"><table><thead><tr><th>Phase</th><th>Condition</th><th>Candidate</th><th>Baseline</th><th>Effect</th><th>95% interval</th><th>Usable / total blocks</th><th>Analyzed / predicted rows</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<h2>Retrieval → reviewed experiment change</h2>{evidence_html}
<h2>{'The original question, registered for replay' if replay_html else 'Registered confirmation'}</h2>{replay_html}<details><summary>Full immutable registration record</summary><pre>{esc(json.dumps(folio.get('registration'), indent=2))}</pre></details>
<h2>Independent computation</h2><ul>{checks}</ul><p>{esc((folio.get('verification') or {}).get('independence', ''))}</p>
<h2>Provider and execution receipts</h2><div class="table"><table><thead><tr><th>Purpose</th><th>Provider</th><th>Exact model</th><th>Status</th><th>Input tokens</th><th>Output tokens</th><th>Request ID</th></tr></thead><tbody>{receipts}</tbody></table></div>
<h2>What this evidence does not establish</h2><ul>{concise_html}</ul><details><summary>Full recorded limitations</summary><ul>{limitations}</ul></details><p>Local operator review: {esc((conclusion.get('review') or {}).get('reviewer_name', 'Pending'))}. External methodologist qualification remains pending. Model-supplied assumptions are advisory; locking approves the authored claim and trusted specification, not those assumptions.</p>
<h2>Reproduce without inference</h2><p>The ZIP contains the exact evidence, hashed data, trusted numerical source and a portable reproduction entry point. Follow README-REPRODUCE.md. Neither a model key nor a retrieval key is needed. Check manifest.json before running; hashes are tamper evidence, not proof that inputs are true.</p></main></html>"""


def export_bundle(store: Store, folio: dict) -> tuple[bytes, str]:
    if not folio.get("verification"):
        raise Conflict("verification_required", "Portable evidence releases sealed labels only after the registered verification has completed.")
    root = store.root / "cases" / folio["id"]
    files: dict[str, bytes] = {"report.html": report(folio).encode(), "evidence.json": canonical(folio)}
    # Only these deliberate scientific inputs are eligible. No recursive archive
    # of the project, parent .env, runtime database, plans or credentials.
    frozen_source = root / "frozen_source" / "science"
    if not frozen_source.is_dir():
        raise Conflict("source_snapshot_missing", "This folio lacks its exact frozen numerical source. Export cannot silently substitute the current implementation.")
    for path in sorted(frozen_source.rglob("*")):
        if path.is_file() and not path.is_symlink() and path.suffix in {".py", ".md", ".json"} and "__pycache__" not in path.parts:
            files["science/" + path.relative_to(frozen_source).as_posix()] = path.read_bytes()
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink() and path.suffix in {".json", ".csv", ".txt", ".npz", ".npy", ".zip", ".py"} and path.stat().st_size < 50_000_000:
            rel = path.relative_to(root)
            if any(part.startswith(".") for part in rel.parts) or "export" in rel.parts:
                continue
            files["case/" + rel.as_posix()] = path.read_bytes()
    for artifact in folio["artifacts"]:
        path, _ = store.get_artifact(artifact["sha256"])
        files["artifacts/" + artifact["sha256"]] = path.read_bytes()
    for name in ("requirements.txt", "requirements.lock", "LICENSE", "docs/scientific-methods.md", "docs/data-provenance.md", "docs/case-registry.md"):
        path = PROJECT / name
        if path.is_file():
            files[name] = path.read_bytes()
    script = '''#!/usr/bin/env python3
"""Validate every exported byte, then rerun/reverify the trusted numerical protocol."""
from pathlib import Path
import argparse, hashlib, json, subprocess, sys
root=Path(__file__).resolve().parent
parser=argparse.ArgumentParser()
parser.add_argument("--verify-only", action="store_true")
args=parser.parse_args()
manifest=json.loads((root/"manifest.json").read_text())
for name, expected in manifest["files"].items():
    path=(root/name).resolve()
    if not path.is_relative_to(root) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
        raise SystemExit("INTEGRITY FAILURE: "+name)
print("All", len(manifest["files"]), "exported files match their manifest.")
if args.verify_only: raise SystemExit(0)
evidence=json.loads((root/"evidence.json").read_text())
request={"root":str(root/"case"),"contract":evidence["contract"],"registration":evidence["registration"],"reproduction_accepted":evidence["reproduction_accepted"],"active_conditions":(evidence.get("exploration_plan") or {}).get("conditions",evidence["contract"]["active_conditions"])}
request_path=root/"replay-request.json"
request_path.write_text(json.dumps(request))
for stage in ("rerun", "reverify"):
    subprocess.run([sys.executable,"-m","science.cli",stage,"--input",str(request_path),"--output",str(root/("replay-"+stage+".json"))],cwd=root,check=True)
print("Replay complete. Inspect replay-rerun.json and replay-reverify.json; this is a reproducibility replay, not a fresh untouched holdout.")
'''
    files["reproduce.py"] = script.encode()
    files["README-REPRODUCE.md"] = ("# Portable Crucible evidence\n\nThis package releases the registered heldout labels after verification. It is a reproducibility replay, not new confirmatory inference.\n\n1. Create a Python 3.11 environment and install the fully pinned `requirements.lock` using `pip install --require-hashes -r requirements.lock` (or `uv pip sync requirements.lock`).\n2. Run `python reproduce.py --verify-only` to check all hashes.\n3. Run `python reproduce.py` to retrain both trusted pipelines, repeat discovery, predict the registered condition and independently recompute the decision. No provider keys, inference, or network access are needed after dependency installation.\n\nRead `report.html`, `evidence.json` and `docs/scientific-methods.md`. Source and data rights are separately attributed in the provenance document. The paper and original R code are not redistributed. This authored protocol does not reproduce that paper's full protocol.\n\nModel proposals are retained as receipts, not rerun or needed for numerical reproduction. The same-OS predictor/verifier boundary is architectural; this release is not an arbitrary-code sandbox.\n").encode()
    manifest = {"schema_version": "crucible.export.v1", "created_at": now(), "folio_id": folio["id"], "contract_sha256": folio["contract"].get("sha256"), "verification_sha256": folio["verification"].get("sha256"), "holdout_release": "Registered verification completed; use only as a reproducibility replay", "files": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())}}
    files["manifest.json"] = canonical(manifest)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name, data in sorted(files.items()):
            archive.writestr(name, data)
    return output.getvalue(), f"crucible-{folio['id']}-evidence.zip"
