# Hand check: 100 random changes on Chicago Food Inspections

Date: 2026-11-15 (M6 step 8). File: `sample_data/chicago_food_inspections.csv`, 5,000 real rows, no ground truth.
Every proposal was approved. The clean made 17,347 changes; `evaluation/chicago_sample.py` draws 100 of them
with a fixed seed (8), so the same 100 can be listed again.

**Who checked:** Claude read each of the 100 changes (old value, new value, column) and judged it. The project
owner has not reviewed them yet; the list can be reproduced with the script for a second opinion.

## Result

| Verdict | Count | What it means |
|---|---:|---|
| Correct | 65 | Same meaning, tidier form |
| Correct in meaning, debatable choice | 31 | The value still means the same, but the choice of spelling is questionable |
| Flag, reasonable | 1 | A true statistical outlier, flagged only |
| Flag, not useful | 3 | A flag on a column where outliers mean nothing |
| Wrong (meaning changed or data lost) | **0** | |

No sampled change damaged a value. 96 of 100 are value changes that keep the meaning; 4 are flags (flags never change a value).

## By group

| # in sample | Rule | Column | Change | Verdict |
|---|---|---|---|---|
| 1 to 8 | trim_and_normalize_text | violations | Double spaces inside long inspection notes become single spaces | Correct. Text is otherwise untouched (lengths drop by 1 to 17 characters). |
| 9 to 38 | trim_and_normalize_text | location | A three-line value (two empty address lines, then the coordinates) becomes `, (41.87..., -87.70...)` | Correct. The coordinates are kept digit for digit. Note: line breaks inside a cell are treated as spaces, so a multi-line address would be joined into one line. |
| 39 to 64 | parse_dates | inspection_date | `2026-11-03T00:00:00.000` becomes `2026-11-03T00:00:00` | Correct. Same moment; the empty milliseconds are dropped. |
| 65 to 95 | standardize_categories (Tier 1, automatic) | city | `CHICAGO` becomes `Chicago` | **Correct in meaning, debatable.** See finding 1. |
| 96 | standardize_categories (Tier 2, approved) | city | `CHICAGO.` becomes `Chicago` | Correct. A stray full stop. |
| 97 to 99 | flag_outliers | license | `license_outlier_flag = true` | **Not useful.** See finding 2. |
| 100 | flag_outliers | longitude | `longitude_outlier_flag = true` | Reasonable: the point is far from the rest. Flag only. |

## Findings for the owner (nothing was changed in the engine)

1. **Title Case beats a 99% majority.** The raw file has `CHICAGO` 4,953 times, `Chicago` 20 times and `chicago`
   7 times. The owner's Step 2 rule (prefer an existing Title Case spelling) rewrites all 4,953 automatically.
   The meaning is the same, and it can be undone on the Fixes screen, but it is 4,960 automatic changes that go
   against how the file is written. Option: prefer Title Case only when no spelling has a clear majority.
2. **License numbers are flagged as outliers.** `license` is read as a whole number (the column name is not on
   the id list), so `flag_outliers` flags 573 rows. A flag changes no value, but these flags are noise.
   Option: add `license` and `number`-style names to the id-like list, or skip outlier flags on columns where
   almost every value is distinct.
3. **Line breaks inside cells are joined.** Harmless here; worth knowing for address or comment columns.
4. Carried over from M5: uniqueness can fall by about 0.1 point because the long `violations` text counts as a
   key candidate.

## Reproduce

```
.venv/Scripts/python evaluation/chicago_sample.py
```
