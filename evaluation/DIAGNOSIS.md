# M6 Step 1: Diagnosis of missed duplicates and outliers

Date: 2026-11-12. Starting point: tag `phase1-m5`. Reproduce with `.venv/Scripts/python evaluation/diagnose.py`.

## Summary

| Item | Missed at M5 | (i) | (ii) | (iii) | Change made |
|---|---|---|---|---|---|
| Duplicate rows | 16 of 36 | 0 | 0 | 16 | Answer key fixed |
| Outliers | 1 of 3 | 1 | 0 | 0 | None |
| "(123)" amounts | 4 of 5 | n/a | n/a | n/a | Answer key fixed |

No engine code, rule order or outlier method was changed.

## a) Duplicate rows (recall 55.6% at M5)

Categories: (i) true exact duplicate in the raw file that the rule missed; (ii) only a duplicate after trimming or normalizing; (iii) not a duplicate of an earlier row, so the answer key is wrong.

All 16 misses are **(iii)**. In every case the labelled row has an exact copy in the raw file, but the copy sits *below* it. The generator picked a source row and inserted the copy at a random position, which was often above the source. The rule keeps the first occurrence (CONTRACT 2.3), so it removed the other row of the pair. That is correct behaviour; the key labelled the wrong row. The evaluation showed this as 16 misses plus 16 "wrong" row removals.

| File | Labelled row (first copy) | Identical row removed by the rule |
|---|---|---|
| sales_orders_messy.csv | 57, 69, 107, 154, 203, 234, 250, 271, 295 | 88, 101, 279, 183, 371, 390, 344, 339, 378 |
| customers_messy.xlsx | 12, 36, 40, 227 | 28, 254, 118, 234 |
| hr_survey_messy.csv | 22, 44, 112 | 37, 212, 246 |

The M5 README explanation ("some copies carry a missing value the original lacks") was wrong: the copies are identical.

**Fix (answer key only):** `make_samples.py` now labels every row that has an identical non-empty row above it, after all rows are placed. No random calls changed, so the three sample files are byte-identical (xlsx cell-identical); only `ground_truth.csv` changed. Duplicate count stays 36. New test: `test_duplicate_row_labels_the_later_copy`.

After the fix: 36 of 36 duplicates removed, 0 wrong removals.

## b) Outliers (recall 66.7% at M5)

Categories: (i) value not beyond the threshold; (ii) method misses it; (iii) engine bug.

| File | Row | Column | Value | IQR fence (k = 1.5) | Category |
|---|---|---|---|---|---|
| hr_survey_messy.csv | 207 | Salary | 1 | -8,875 to 188,125 (Q1 65,000, Q3 114,250, n = 296) | (i) |

A salary of 1 is implausible, but it is inside the statistical fence: salaries are spread widely, so the lower bound is negative. The rule did exactly what CONTRACT 2.3 says. No method change. This stays a known limit: a plausibility check (for example "salary below a floor") is a different rule, not a fix to this one. The other two outliers (9,999,999 salary and 9,750,000 lifetime value) are flagged.

## c) "(123)" amounts

CONTRACT 2.3 says `(123)` becomes `-123`. The key recorded the positive value, so 4 of 5 were scored as misses (the fifth sat on a duplicate row that was removed). **Fix:** the key now records `-<amount>`. New test: `test_parentheses_negative_expects_a_negative_number`.

## d) messy_orders_demo.csv: was a Region suggestion created?

The file is not in the repo (it is in the owner's Downloads folder). Its one stored run (`storage/bb85a465-...`) shows:

- **The suggestion was created** (`sug_cfa4c49aca0b`, `standardize_categories` on `region`, mode suggest) **and never approved**: it is not in `plan.json`, so the clean file still has 17 Region spellings.
- Even if approved it would not have been enough. Its mapping merges only case variants and `Nrth`, `Wst`; it keeps `east`/`west` in lowercase (most common raw spelling), splits `South` from `SOUTH`, and leaves `Eest`, `Sth` and `N.` alone. This is what Step 2 addresses.
- Quantity is inferred as `id` because of the value `03`, so `coerce_numeric` never runs on it (Step 2b).

## Effect on the headline numbers

With the corrected key and no engine change: recall 99.9% (1,741 of 1,742 fixable), precision 100%, 0 damaged cells. The only miss is the salary of 1. This figure only counts fixable errors; Step 8 replaces it with detection recall and fix recall over all injected errors on a held-out batch. The README table still shows the M5 numbers until Step 8.
