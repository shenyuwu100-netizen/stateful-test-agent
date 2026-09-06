# Stateful Test Agent

A small, runnable lab for feedback-driven test generation: generate command sequences and metamorphic relations, validate them against a local reference, use development-fixture feedback to add tests, and evaluate on withheld synthetic defects. Includes failure reduction and offline replay.

## Quick start — no API key required

Requires Python 3.10+; uses only the standard library.

```bash
python -m unittest discover -q
python replay_lab.py examples/recorded-run.json
python agent_lab.py
```

The default run reuses **recorded model-generated suites** and creates JSON/HTML reports under a new `results/lab-*` directory. It does not generate new LLM responses or spend API credits. The public package passes 17 tests and 21 result/reproducer replay checks.

## How it works

```text
Specification → constrained JSON tests → reference validation
                                      → development-fixture evaluation
                                      → feedback → additional tests
Frozen suites → withheld-fixture evaluation → failure reduction → report
```

- 28 command categories in a locally reconstructed key/value target.
- 12 development and 8 additional synthetic defects; withheld defects do not enter model feedback.
- Invalid metamorphic relations do not count as detected defects.
- Fresh state for each sequence and each relation side; relations compare final outputs.
- Command and API-call limits, sanitized usage records, target hashes, HTML/JSON reports.
- Failure reduction retains a reproducible mismatch and reports whether it reached 1-minimality.

## Recorded result

| Method | Actual commands / cap | Development defects | Withheld defects |
| --- | --- | --- | --- |
| Single generation | 97 / 120 | 4 / 12 | 7 / 8 |
| Agent first round | 59 / 60 | 5 / 12 | 5 / 8 |
| Two-round agent | 61 / 120 | 5 / 12 | 6 / 8 |

The two-round agent did **not** beat single generation in this run. Its second round added only two commands. One invalid relation from single generation was excluded. The recording contains three successful model requests with 4,990 service-reported total tokens; charges and upstream model identity were not independently verified.

This is a single small synthetic experiment, not a statistically controlled performance claim. Command caps match but actual commands and API costs differ. The reference and defects share an author, so withheld fixtures are not external independent validation. No course grades, source line/branch coverage or production deployment is claimed.

## Optional live experiment

Configure your own compatible HTTPS API using environment variables in your shell:

- `LLM_BASE_URL`: API base, with or without `/v1`.
- `LLM_API_KEY`: your key. Do not commit it.
- `LLM_MODEL`: optional, defaults to `gpt-5.6-luna`.

Then run `python agent_lab.py --live`. This sends the synthetic specification/tests to your provider and can incur charges. Maximum three calls, up to 3,000 completion tokens per call, low reasoning effort. No automatic retry or provider/account switching. The provider must accept these options. Environment-based live setup is unit-tested with mocked responses; the supplied real recording predates this public credential-adapter refactor.

## Local-model assumptions

The target is a reconstruction, **not the original course MiniRedis or a full Redis clone**. It uses arbitrary-precision integers with truncation-toward-zero division, lazy `if`, schema deletion with `DEL`, inclusive ranges, atomic `MSET`/`SETV`, retained empty-list keys, and schema checks on numerical writes/APPEND/CALC. These choices may differ from other implementations.

Generated input is validated JSON command data, not executable Python/shell. The interpreter is not an operating-system sandbox for running arbitrary code. No browser state or local personal documents are included in the package. Course handouts, original course submissions and private workspace snapshots are omitted.

## Files

- `agent_engine.py`: constraints, execution feedback, API transport.
- `agent_lab.py`: experiment orchestration, reduction, reports.
- `local_target.py`, `heldout_target.py`: reference and defect fixtures.
- `replay_lab.py`: zero-API verification of recorded results.
- `examples/recorded-run.json`: redacted recording with course baseline metadata omitted.
