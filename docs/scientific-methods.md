# Crucible's authored numerical protocol

The protocol below was chosen on 28 October 2026 before the first Crucible fit or inspection of method outcomes. `science/spec.py` is the trusted numerical specification; its canonical digest is retained in every prepared case, training receipt and confirmation registration. Model proposals cannot edit this oracle. A local operator reviews the claim and practical margin; external methodologist qualification remains pending.

Crucible currently implements two authored binary classification comparisons: UCI Occupancy Detection and an explicitly controlled nonlinear synthetic case. Neither reproduces the original occupancy paper's full protocol. The paper's work already includes feature-subset analysis: sensor availability is an interpretability exercise here, not a novelty claim. No arbitrary repository, paper code, uploaded Python, or user-selected metric implementation executes.

## Methods fixed before outcomes

Both methods use the same five ordered columns: Temperature, Humidity, Light, CO2, HumidityRatio. IDs, dates, group IDs and the target never enter predictors. Both fit median imputation using training rows only. Logistic regression additionally fits standard scaling using training only. The probability threshold is fixed at 0.5. There is no parameter search, validation-based threshold selection, feature selection, or outcome-dependent stopping.

| Method | Fixed parameters |
| --- | --- |
| Candidate | RandomForestClassifier: 96 trees, max_depth 8, min_samples_leaf 3, max_features sqrt, class_weight balanced, bootstrap true, gini, n_jobs 1 |
| Baseline | LogisticRegression: C 1, lbfgs, class_weight balanced, max_iter 1000, tol 0.0001, intercept true |
| Seeds | 11, 29, 47 for both methods; all completed or the attempt fails |
| Shared tuning allowance | Zero trials; same source rows, features, threshold, seeds and per-process resource ceiling |
| Resource bounds | One numerical thread, 180 CPU seconds, 240 wall seconds, 32 MiB per output file; actual fit time, process CPU time and peak RSS are retained |

Different algorithms use different actual compute; equal tuning allowance and a shared upper envelope do not mean equal realized CPU expenditure. Two clean subprocess fits must reproduce identical original-condition predictions and fitted-state digests under the same installed environment before local acceptance. This is not evidence from two independently provisioned environments. Version/hardware differences can cause replay disagreement; disagreement is an execution/reproducibility issue, never a refutation.

Training-only fitting follows scikit-learn's [leakage guidance](https://scikit-learn.org/stable/common_pitfalls.html). The independent verifier recomputes medians and scaling statistics directly from training values and checks each worker's declaration, exact fitted parameters, all six seed/method receipts, row counts and input hashes. Parameters and behavior follow the [RandomForestClassifier documentation](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.RandomForestClassifier.html).

## Splits and the first audit

The official UCI files remain byte-for-byte preserved and hashed. Preparation audits exact timestamps, row counts, missing values, duplicate IDs/timestamps and cross-file timestamp overlap before any fit. Original numeric IDs repeat across files, so IDs are file-qualified.

| Role | Official file | Rows | Recorded timestamps | Calendar days |
| --- | --- | ---: | --- | ---: |
| Training | datatraining.txt | 8,143 | 2015-02-04 17:51:00 – 2015-02-10 09:33:00 | 7 |
| Discovery | datatest.txt | 2,665 | 2015-02-02 14:19:00 – 2015-02-04 10:43:00 | 3 |
| Confirmation | datatest2.txt | 9,752 | 2015-02-11 14:48:00 – 2015-02-18 09:19:00 | 8 |

Discovery precedes training. Training and discovery include different observations on February 4; there is no exact timestamp overlap. The official file assignment is preserved, not recast as a pure forward-validation study. The date strings have no timezone, so recorded calendar dates are used without an invented timezone conversion. Adjacent days in one room are not established independent sampling units.

The first numerical test audits source preparation while RandomForestClassifier.fit is patched to fail if called. No fitting is needed to validate file/timestamp provenance. Preparation writes an immutable identity first, so a crash between source-manifest creation and final publication can resume with the same timestamps and hashes. Exact trusted Python files are frozen in the case alongside their digests.

The synthetic generator is `authored-xor-groups-v1`, specified in source before fitting. Separate split seeds are 103001, 103002 and 103003; they spawn independent per-group random streams. There are 16 training, 12 discovery and 24 confirmation groups of 64 rows each. Independent uniform centered Light and CO2 signs determine XOR labels; labels flip independently with probability 0.05. Other columns contain independent noise and a group nuisance offset. No group occurs in two partitions. These are synthetic controls, not empirical office measurements or a planted discovery about another paper. Inference conditions on the fixed training set.

## Fixed finite challenge lattice

The seven possible cells are `original`, `co2_25`, `co2_50`, `co2_100`, `light_25`, `light_50`, `light_100`. Default discovery evaluates the original cell and all three CO2 cells. A reviewed EvidenceChange can add Light cells within this predeclared allowance; the locked analysis and numerical specification remain unchanged. The reviewed control plane, not retrieved prose, authorizes the schedule.

A dropout condition replaces one evaluation sensor with NaN for a fixed row-hash mask salted `crucible-sensor-mask-v1`, then uses the unchanged training median. Masks are label-independent and identical across methods and seeds. Rates 25% and 50% are hash-selection probabilities; actual masked-row counts need not equal precisely those fractions. The masks are nested within a feature. There are no combined-axis cells and no interpolation between untested cells. Training features are unchanged. The original superiority claim covers complete sensors only: all dropout cells are applicability tests. A conditional difference under missing sensors cannot refute the complete-sensor claim.

Every active cell and all three seeds run once, without optional stopping. The planner can rank discovery aggregates only. One condition is registered before confirmation prediction. The control plane additionally enforces a global holdout registry across folios by split, condition and analysis/source signature; the numerical worker enforces a once-only registration within each case root. Exact replays are labeled replay. A changed confirmation condition, margin or analysis cannot be accepted as another untouched test of the same holdout.

## Estimator, uncertainty and decisions

The oracle calculates binary balanced accuracy directly as half the sum of sensitivity and specificity. A block with only one observed class has undefined block-level balanced accuracy and is excluded from the estimator by this prespecified definition. All rows still receive predictions; excluded block IDs, reasons and row counts remain visible. The reported population is therefore the file's days/groups containing both target classes, not every calendar day. Each usable block has equal weight, regardless of row count.

For each block, candidate minus baseline balanced accuracy is computed for every seed and then averaged across the three seeds. The reported effect is the mean of those block effects. Method scores use the same block/seed weighting. Seed spread is shown separately. Rows and seeds never inflate the independent sample count B.

The interval is a two-sided **descriptive 95% Student t interval** over block effects, conditional on these trained models. Its endpoints are restricted to the mathematically possible effect range [-1,1]. It is not a simultaneous interval and is not adjusted by Holm. At least six usable blocks and finite, nondegenerate uncertainty are required for a directional conclusion. Null/undefined intervals stay null, not zero.

The confirmatory family has two preregistered one-sided paired-block t tests: mean effect greater than practical_delta, and mean effect less than practical_delta. The margin defaults to 0.02 and may be locally reviewed between 0 and 0.10 before locking. Both directions enter one Holm family at alpha 0.05. This tests the **mean block effect**, rather than substituting a sign/median test for the stated estimand. The t assumptions and limits follow [SciPy's independent-observations definition](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.ttest_1samp.html). A low less-than-margin p-value can challenge a 2 percentage point superiority claim even if the point estimate remains positive; it is not automatically a reversal.

| Mechanical finding, with accepted reproduction and all validity gates | Bounded outcome |
| --- | --- |
| Adjusted greater-than-margin test passes | Supported within that tested setting |
| Adjusted less-than-margin passes, original condition | Evidence against the registered superiority margin in its tested scope |
| Adjusted less-than-margin passes, dropout condition | Applicability boundary; original complete-sensor claim unchanged |
| Too few usable blocks, unestablished independence, undefined uncertainty, or neither direction passes | Inconclusive; no equivalence claim |
| Installation, execution, resource, integrity or replay failure | Operational failure; no scientific refutation |

**UCI Occupancy cannot receive a confirmatory directional verdict in this release.** Eight adjacent calendar days in one room do not establish independence, and usable two-class blocks can be fewer. Its intervals and conditional p-values remain inspectable diagnostics, with an inconclusive verdict. The independent synthetic groups can exercise the full inferential decision path. A synthetic result is not validation across real datasets.

## Architectural separation and evidence

The predictor subprocess gets a capsule containing training labels, unlabeled evaluation features and a fixed manifest. It does not import the verifier or receive sealed label filenames. Only the separate trusted verifier process joins labels. No provider credentials are inherited, numerical libraries are restricted to one thread, and CPU/wall/output bounds apply. Predictor/verifier children remain in the API's process group so cancellation cannot leave an orphan fitting process. Failed attempts retain their inputs and bounded execution logs.

This is **code and process separation under one OS identity**, not kernel isolation, an arbitrary-code sandbox, a different security identity, an independent methodologist or proof of malicious-code resistance. The same account can read public source data on disk; an attacker able to rewrite the whole provenance chain is outside this local trust boundary. Hashes expose changed retained bytes relative to their envelope, not truthfulness of data or immunity to historical public-benchmark contamination. Imported code and undeclared adapters are unsupported.

Artifacts retain original source bytes, sanitized inputs, sealed-label hashes, split maps, the exact numerical/source snapshots, full predictions, fitted-state digests, actual training/resource receipts, block metrics and verifier checks. Before verification, raw source files and sealed labels are private; neither is a client artifact because official archives include targets. After verification the portable package deliberately releases the registered holdout labels for reproducibility. The frozen source can retrain all fixed plans and reverify metrics without model inference or network access after pinned dependencies are installed. Such a replay is never a new untouched confirmation.

Adversarial tests cover source tampering, duplicate prediction identities despite rehashing, changed sealed labels/counts, false declared sample sizes, target-bearing evaluation inputs, preprocessing leakage despite rehashing, altered numerical parameters, changed holdout registration, interrupted preparation, and actual portable retraining/reverification. These tests establish specific implementation properties, not universal scientific correctness.
