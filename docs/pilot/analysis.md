# VerifyLoop pilot analysis

Run files:
- `docs/pilot/run-20261020-034833-5bcb12.results.jsonl`
- `docs/pilot/run-20261020-090734-fbc80c.results.jsonl`

Excluded tasks: exception_json_005

Total recorded cells: 30
Analyzed cells: 24 (excluding 6)

## run-20261020-034833-5bcb12

provider `ollama`, model `llama3.2:3b`, benchmark `v1`

### Outcomes

| strategy | cells | valid | verified | failed_tests | patch_rejected | infra | budget_exh | mean attempts | mean wall s | median wall s | mean gen s | mean test s | mean tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| oneshot | 4 | 4 | 1 | 1 | 2 | 0 | 1 | 1.00 | 46.7 | 44.8 | 29.6 | 3.0 | 486 |
| blind_retry | 4 | 3 | 0 | 0 | 3 | 1 | 0 | 2.00 | 37.6 | 33.6 | 25.7 | 0.0 | 760 |
| evidence_guided | 4 | 4 | 0 | 1 | 3 | 0 | 0 | 2.00 | 44.2 | 34.6 | 21.5 | 4.0 | 774 |

### Task by strategy

| task | oneshot | blind_retry | evidence_guided |
|---|---|---|---|
| return_missing_009 | verified_success | patch_rejected | patch_rejected |
| sorting_records_007 | patch_rejected | patch_rejected | patch_rejected |
| validation_age_003 | failed_tests | infrastructure_error | failed_tests |
| validation_csv_016 | patch_rejected | patch_rejected | patch_rejected |

### Patch applicability and evidence delivery

| strategy | cells with an attempt | first attempt applied | first attempt rejected | cells with any test report | evidence prompts recorded |
|---|---:|---:|---:|---:|---:|
| oneshot | 4 | 2 | 2 | 2 | 0 |
| blind_retry | 4 | 1 | 3 | 1 | 0 |
| evidence_guided | 4 | 1 | 3 | 1 | 1 |

### Failure categories (valid cells)

`none`=1, `patch_conflict`=8, `syntax_error`=1, `unknown`=1

## run-20261020-090734-fbc80c

provider `ollama`, model `llama3.2:3b`, benchmark `v1`

### Outcomes

| strategy | cells | valid | verified | failed_tests | patch_rejected | infra | budget_exh | mean attempts | mean wall s | median wall s | mean gen s | mean test s | mean tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| oneshot | 4 | 4 | 0 | 1 | 3 | 0 | 0 | 1.00 | 37.3 | 38.2 | 26.3 | 1.6 | 488 |
| blind_retry | 4 | 4 | 0 | 0 | 4 | 0 | 0 | 2.00 | 51.9 | 39.8 | 38.8 | 0.9 | 838 |
| evidence_guided | 4 | 4 | 0 | 0 | 4 | 0 | 0 | 2.00 | 37.0 | 36.3 | 24.3 | 0.9 | 788 |

### Task by strategy

| task | oneshot | blind_retry | evidence_guided |
|---|---|---|---|
| return_missing_009 | patch_rejected | patch_rejected | patch_rejected |
| sorting_records_007 | patch_rejected | patch_rejected | patch_rejected |
| validation_age_003 | failed_tests | patch_rejected | patch_rejected |
| validation_csv_016 | patch_rejected | patch_rejected | patch_rejected |

### Patch applicability and evidence delivery

| strategy | cells with an attempt | first attempt applied | first attempt rejected | cells with any test report | evidence prompts recorded |
|---|---:|---:|---:|---:|---:|
| oneshot | 4 | 1 | 3 | 1 | 0 |
| blind_retry | 4 | 1 | 3 | 1 | 0 |
| evidence_guided | 4 | 1 | 3 | 1 | 1 |

### Failure categories (valid cells)

`patch_conflict`=11, `unknown`=1

## Combined analyzed cells

| strategy | cells | valid | verified | failed_tests | patch_rejected | infra | budget_exh | mean attempts | mean wall s | median wall s | mean gen s | mean test s | mean tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| oneshot | 8 | 8 | 1 | 2 | 5 | 0 | 1 | 1.00 | 42.0 | 39.5 | 28.0 | 2.3 | 487 |
| blind_retry | 8 | 7 | 0 | 0 | 7 | 1 | 0 | 2.00 | 45.8 | 35.2 | 33.2 | 0.5 | 804 |
| evidence_guided | 8 | 8 | 0 | 1 | 7 | 0 | 0 | 2.00 | 40.6 | 34.6 | 22.9 | 2.5 | 781 |

### Combined task by strategy

| task | oneshot | blind_retry | evidence_guided |
|---|---|---|---|
| return_missing_009 | patch_rejected x1, verified_success x1 | patch_rejected x2 | patch_rejected x2 |
| sorting_records_007 | patch_rejected x2 | patch_rejected x2 | patch_rejected x2 |
| validation_age_003 | failed_tests x2 | infrastructure_error x1, patch_rejected x1 | failed_tests x1, patch_rejected x1 |
| validation_csv_016 | patch_rejected x2 | patch_rejected x2 | patch_rejected x2 |

### Combined patch applicability and evidence delivery

| strategy | cells with an attempt | first attempt applied | first attempt rejected | cells with any test report | evidence prompts recorded |
|---|---:|---:|---:|---:|---:|
| oneshot | 8 | 3 | 5 | 3 | 0 |
| blind_retry | 8 | 2 | 6 | 2 | 0 |
| evidence_guided | 8 | 2 | 6 | 2 | 2 |

### Combined failure categories (valid cells)

`none`=1, `patch_conflict`=19, `syntax_error`=1, `unknown`=2

> Descriptive only. Runs reuse the same model and tasks; cells are not
> independent trials. No significance test is reported or implied.
