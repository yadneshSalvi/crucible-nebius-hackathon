# Data and source provenance

The real-data adapter uses [UCI Occupancy Detection, ID 357](https://archive.ics.uci.edu/dataset/357/occupancy-detection), DOI [10.24432/C5X01N](https://doi.org/10.24432/C5X01N). UCI lists 20,560 observations and distributes three files under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Attribution: **Candanedo, L. (2016). Occupancy Detection [Dataset]. UCI Machine Learning Repository.** The source data are office-room sensors with binary occupancy targets, not Crucible participant data. UCI describes ground truth from timestamped photographs; Crucible distributes only the released numeric files and does not acquire the photographs.

Official archive: `https://archive.ics.uci.edu/static/public/357/occupancy+detection.zip`. Retrieval uses verified TLS or an explicitly supplied copy of the pinned archive. TLS checks are never disabled. The exact source was audited before fitting. The archive must contain only the three expected files; changed bytes, unexpected members or oversized inputs are rejected.

| Preserved artifact | SHA-256 |
| --- | --- |
| occupancy.zip | `4ae3f46aa98eedff564a9f6924d1635173e2fd2c816004342a9be93076d3a81a` |
| datatraining.txt | `b2c4d0ce2b9e4e453c476f7125ef31aeec2d1f5c7f5572d0e80de3df6521ab56` |
| datatest.txt | `1b92c7c1b2838963464fa891a610cf3c5db4becb7189189b29b330107a584c7f` |
| datatest2.txt | `d026d1bd5aeccd4aff4f3b3710d48e40613bd5fc370db7e61bbdcaa50d985095` |

The immutable source manifest records row counts, exact timestamp spans, data shape, split assignment, missingness, duplicate timestamps, cross-file overlap, retrieval/preparation identity, numerical-spec digest, and confirmation-split digest. No record is silently deduplicated or reallocated. Numeric file-local row IDs repeat, so row identity is `<official filename>:<original ID>`. Training and discovery share a calendar date but no timestamp. Original source bytes remain intact alongside derived sanitized feature CSVs.

Transformations are authored and disclosed: exclude date and ID from model inputs; preserve the official train/discovery/confirmation file assignments; fit training-only median imputation and optional scaling; inject explicit deterministic sensor dropout only in evaluation challenges. Evaluation feature files contain no target column. Sealed label files are separate from the predictor input capsule. Original archives themselves contain labels, so they remain private during the active workflow and are released with the registered evidence only after verification. Public availability of the benchmark means this is architectural separation, not proof of historical model ignorance.

UCI links the original publication and [R processing repository](https://github.com/LuisM78/Occupancy-detection-data). The repository's code license has not been established; no R scripts are copied, executed or redistributed. The paper is not bundled. The authored claim sentence is marked authored, not presented as a quote or a reproduced published numerical claim. Data licensing, code rights and paper rights are separate.

The second adapter uses **authored-xor-groups-v1**, generated locally from the fixed, source-recorded NumPy seeds and equations in `science/prepare.py` and `science/spec.py`. Its data are explicitly synthetic and dedicated under CC0-1.0 for reuse. It has no invented public repository URL. Generated source files are hashed, with 16/12/24 disjoint independent groups in training/discovery/confirmation. It is a controlled test of computation, not an empirical research discovery.

At preparation, every trusted Python file is copied into `frozen_source/science/` and hashed. Immutable source snapshots, source bytes, sanitized datasets, sealed labels, numeric configuration, split manifests, model/training receipts, predictions and metric outputs make a portable offline rerun possible. Secrets, the parent environment file, ignored plans, participant material, node modules and arbitrary project files are excluded by export allowlists. The exact environment and actual resource use are retained; dependency installation may require network once, but replay itself uses no inference or retrieval.

Hashes provide tamper evidence relative to the retained manifest, not a cryptographic guarantee against an attacker who can rewrite the entire same-OS evidence chain. Only trusted authored adapters execute in this release. Human scientific review, independent environments and broad empirical validation remain explicitly incomplete.
