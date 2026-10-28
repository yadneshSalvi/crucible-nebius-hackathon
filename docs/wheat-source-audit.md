# Wheat source and asset qualification

28 October 2026. This records source inspection, not a detector result, a paper reproduction, independent methodological review, or a field deployment.

## Primary assets actually retrieved

The [GWHD 2021 Zenodo record](https://zenodo.org/records/5092309) publishes `gwhd_2021.zip`, 10,215,190,132 bytes, MD5 `22b4b542c9ae7e056d7fcdeae9ecaed5`. Bounded HTTPS range reads inspected its actual ZIP directory: 6,515 PNG entries and four CSV files, among 6,521 entries including directories. The CSVs are the **competition** train/validation/test partitions and `metadata_dataset.csv`. The archive does not contain the official WILDS partitions named by its dataset adapter.

The retrieval script refuses a server response that ignores the requested range, limits bytes, verifies each retrieved member's ZIP CRC, and pins its SHA-256. It has **not** downloaded or verified the full archive's published checksum. Original bytes remain under ignored `runtime/wheat-assets/primary/`; immutable range/receipt manifests remain beside them.

- Competition training CSV: 3,657 rows across 18 named acquisition sessions, but 3,655 distinct filenames; SHA-256 `1af1d8e386643afe8cd1b41d89ca2634d3212908bdbe58a9d7cd5b32e4048176`.
- Session metadata: semicolon-delimited; SHA-256 `1fb0a498a4a2d3fff2424b65ecbc41f0ca10d5fc26137b09ffc42c8f3f92d49a`.
- Competition validation and test CSV contents have not been requested by the audit script.
- The discovery illustration was selected before viewing images or detector outcomes: lexicographically first filename in `Rres_1`, `0077c64686e9712d9b8efcd930ce5b0d68c72d8fb50ee99ed01ff2fd73e6d1d2.png`. Its primary PNG SHA-256 is `2454d9090c4fafadd7c7d24840eb1d2e049b7c9fc2f7f4fb3fb78a84ad0fa917`. The selection receipt precedes its retrieval. It is never a final-evaluation illustration selected for a favorable effect.

## Rights and attribution

The [Zenodo metadata API](https://zenodo.org/api/records/5092309) identifies `cc-by-4.0`. The [official WILDS dataset page](https://wilds.stanford.edu/datasets/#globalwheat) and [pinned dataset adapter](https://github.com/p-lambda/wilds/blob/472677590de351857197a9bf24958838c39c272b/wilds/datasets/globalwheat_dataset.py) describe MIT distribution. Preserve this discrepancy instead of silently choosing one label. Attribute Etienne David and the GWHD contributors, link the record and dataset papers, retain the source license metadata, and identify transformations/derived annotations. Both observed sources permit reuse with their respective notices; no exclusive ownership is claimed.

## Protocol correspondence

The upstream repository is pinned to `472677590de351857197a9bf24958838c39c272b`. The [published supplement](https://proceedings.mlr.press/v139/koh21a/koh21a-supp.pdf), SHA-256 `d00f0afa5e6422270a15ccd8d07871864f8629497762a0711f6949870d8c8403`, was inspected as text and a rendered page. PDF page 27 (printed page 26), section H.5.2, specifies Faster R-CNN, ImageNet initialization, batch size 4, learning rate 0.0001, weight decay 0.0001, ten epochs with early stopping, and three seeds.

The [pinned current defaults](https://github.com/p-lambda/wilds/blob/472677590de351857197a9bf24958838c39c272b/examples/configs/datasets.py#L424) specify Adam, batch 4, learning rate 0.00001, decay 0.001 and twelve epochs. The [README](https://github.com/p-lambda/wilds/blob/472677590de351857197a9bf24958838c39c272b/README.md) directs exact paper reproduction to the executable CodaLab record rather than treating current defaults as exact paper commands.

There is a second initialization ambiguity: the [pinned detector builder](https://github.com/p-lambda/wilds/blob/472677590de351857197a9bf24958838c39c272b/examples/models/detection/fasterrcnn.py#L277) loads COCO detector weights when `pretrained=True`; the supplement describes ImageNet initialization. This does not establish an author error or the exact original executable configuration.

The official v1.1 CodaLab bundle URL from the adapter currently fails HTTPS certificate validation with an expired-certificate error. Certificate validation was not disabled. Exact official partitions, original commands and original detector weights have therefore **not** been qualified. Zenodo competition partitions must not be renamed WILDS partitions.

Our available path is a **new source-informed finite-corpus experiment**, with its architecture, initialization, optimizer, epochs, seeds, selection and differences explicitly registered. Matching some paper fields does not convert it into a reproduction. MPS forward/backward capability is engineering evidence, separate from training or scientific outcomes.

## Bounded model source role

`docs/wheat-source-packet.json` retains two short paper excerpts and three exact pinned configuration lines, their document hashes and locators, and six requested field names. `scripts/qualify_wheat_sources.py` retrieves or verifies the full primary document bytes, verifies the code excerpt against lines 442–444, and publishes the packet for the API. The paper excerpt selection was checked against the rendered primary page; rerunning this script does not claim a fresh OCR or independent human review.

The first successful model call received the expected values in an authored source summary. It remains recorded as **audited-summary structuring**. The revised primary-excerpt call receives the excerpts and field/source identities; numeric expected answers remain only in the local validator. Both methods and the initial schema failure remain in history. Successful extraction is advisory source processing, not evidence that detector training, final evaluation or scientific reproduction succeeded.

## Metadata correction and proposed fixed roles

The raw metadata maps `Ethz_1` to location `Usask`. The supplement's Table 11 identifies the Swiss session as Eschikon and separately identifies Canadian Usask. The catalog will preserve the raw value and record the explicitly reviewed Eschikon correction with this locator. Session spelling/case normalization is also recorded; it is not an inferred new observation.

Two filenames occur under both `Arvalis_10` and `Arvalis_12` with differing annotations: `d88963636d49127bda0597ef73f1703e92d6f111caefc44902d5932b8cd3fa94.png` and `1961bcf453d5b2206c428c1c14fe55d1f26f3c655db0a2b6a83094476e8edb5b.png`. The catalog initially refused duplicate coverage. All four ambiguous rows (two images) are quarantined before fitting; it does not select one annotation or site. Every occurrence and original annotation-encoding hash remains in the role plan. This leaves 3,653 unambiguous candidate images.

Candidate roles are fixed by source session/site, before any fit or outcome:

| Role | Source sessions | Images |
| --- | --- | ---: |
| Training | French sessions and Swiss ETHZ, after the explicit identity quarantine | 3,011 |
| Discovery | UK `Rres_1`, Rothamsted | 432 |
| Final public-corpus evaluation | Norwegian `NMBU_1`/`NMBU_2` and Belgian `ULiège-GxABT_1` | 210 |

These are authored new partitions of publicly available competition training data. They are not the official WILDS split, newly collected images or independent external custody. The two final sites support descriptive corpus results only; images, boxes and training seeds do not create independent field replications. Country, crop stage, sensor and collection conditions may co-vary.

The trusted catalog builder normalizes source `xyxy` targets into separate `xywh` files per role, verifies geometry, and never prints final-role target values. This is deterministic ingestion of public labels, not independent blind custody. Adaptive planners and browser discovery views must not receive final targets. Full assets and their pixel hashes are not yet qualified. All exact duplicate pixel groups spanning candidate roles must be quarantined from execution before the executable manifest freezes; exclusions and reasons are retained. Metadata does not prove absence of overlapping plots or near duplicates. No sampling confidence interval or causal country claim is authorized.

Storage currently prevents retaining the full planned image set and training artifacts with a safe working margin. The selected PNG members total 6,452,120,850 bytes; 6,450,846,275 bytes are missing. `scripts/download_wheat_catalog.py` retrieves the predefined members in archive order through bounded range reads, avoiding a second full ZIP copy. Its default mode audits disk requirements without downloading images. `--download` requires every missing image plus a 2 GiB working reserve to fit; it never narrows the role plan. Approximately 9 GB free total is needed **for image ingestion**, compared with about 2 GiB currently free. Training checkpoints, inference records, portable export and independent replay need separate additional storage; the ingestion estimate does not promise that the entire workflow fits in 9 GB.

The user has been asked for additional local space or another drive. Source compilation, software and controlled engineering tests continue; no smaller scientific corpus is silently substituted and no unrun training is presented as completed. Resuming a download verifies previously recorded image SHA-256 values; new member bytes pass ZIP CRC checks before atomic writes. The full published archive MD5 remains unverified when only selected members are retrieved.
