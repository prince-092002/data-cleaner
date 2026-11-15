# Hand check: 100 random changes on Chicago Food Inspections

File: `sample_data/chicago_food_inspections.csv`, 5,000 real rows, no ground truth. Every proposal was approved.

- **First check, 2026-11-15 (M6 step 8):** the clean made 17,347 changes. `evaluation/chicago_sample.py` drew 100 of
  them with a fixed seed (8). Each was read and judged.
- **Re-check, 2026-11-15 (M6 step 8b):** after two engine fixes (clear-majority spelling wins; license-style names
  are ids) the clean makes 11,840 changes. The SAME 100 changes were looked up in the new change log and judged with
  the SAME rubric. A change the engine no longer makes is counted as "no longer made".

**Who checked:** Claude read each change (old value, new value, column) and judged it, both times. The project owner
has not reviewed them yet.

## Result, before and after

| Verdict | Step 8 | Step 8b | What it means |
|---|---:|---:|---|
| Correct | 65 | 65 | Same meaning, tidier form |
| Debatable | 31 | 0 | Same meaning, but a questionable choice of spelling |
| Useful flag | 1 | 1 | A true statistical outlier, flagged only |
| Useless flag | 3 | 0 | A flag on a column where outliers mean nothing |
| Wrong (meaning changed or data lost) | **0** | **0** | |
| No longer made | 0 | 34 | The engine does not make this change any more |

Nothing got worse. The 31 debatable changes and the 3 useless flags are simply not made any more; the other 66 are
the same change as before, except item 96, which is still correct.

## What changed between the two checks

1. **City.** The raw file has `CHICAGO` 4,953 times, `Chicago` 20 times, `chicago` 7 times and `CHICAGO.` twice.
   Before: 4,960 automatic changes rewrote the capitals to `Chicago`. Now: `CHICAGO` holds over 99% of its group, so
   it stays as written and only the 27 minority rows change to `CHICAGO`, each logged with the reason
   "majority spelling". `CHICAGO.` is still a suggestion and now becomes `CHICAGO`.
2. **License.** `license_` is now typed as an id (the name has the word "license"), so its 573 outlier flags are
   gone. The 143 longitude flags stay.
3. Whole file: 17,347 changes before, 11,840 now. Quality scores are unchanged (95.7 to 99.4).

## All 100 items

| # | Rule | Column | Row | Change in step 8 | Verdict step 8 | Verdict step 8b | Note |
|---|---|---|---|---|---|---|---|
| 1 | trim_and_normalize_text | violations | 855 | double spaces in the inspection notes become single spaces | correct | correct | same change |
| 2 | trim_and_normalize_text | violations | 1001 | double spaces in the inspection notes become single spaces | correct | correct | same change |
| 3 | trim_and_normalize_text | violations | 1656 | double spaces in the inspection notes become single spaces | correct | correct | same change |
| 4 | trim_and_normalize_text | violations | 2261 | double spaces in the inspection notes become single spaces | correct | correct | same change |
| 5 | trim_and_normalize_text | violations | 2756 | double spaces in the inspection notes become single spaces | correct | correct | same change |
| 6 | trim_and_normalize_text | violations | 3147 | double spaces in the inspection notes become single spaces | correct | correct | same change |
| 7 | trim_and_normalize_text | violations | 3540 | double spaces in the inspection notes become single spaces | correct | correct | same change |
| 8 | trim_and_normalize_text | violations | 4136 | double spaces in the inspection notes become single spaces | correct | correct | same change |
| 9 | trim_and_normalize_text | location | 210 | three-line value becomes `, (lat, lon)`; coordinates kept digit for digit | correct | correct | same change |
| 10 | trim_and_normalize_text | location | 375 | three-line value becomes `, (lat, lon)`; coordinates kept digit for digit | correct | correct | same change |
| 11 | trim_and_normalize_text | location | 417 | three-line value becomes `, (lat, lon)`; coordinates kept digit for digit | correct | correct | same change |
| 12 | trim_and_normalize_text | location | 648 | three-line value becomes `, (lat, lon)`; coordinates kept digit for digit | correct | correct | same change |
| 13 | trim_and_normalize_text | location | 1100 | three-line value becomes `, (lat, lon)`; coordinates kept digit for digit | correct | correct | same change |
| 14 | trim_and_normalize_text | location | 1128 | three-line value becomes `, (lat, lon)`; coordinates kept digit for digit | correct | correct | same change |
| 15 | trim_and_normalize_text | location | 1245 | three-line value becomes `, (lat, lon)`; coordinates kept digit for digit | correct | correct | same change |
| 16 | trim_and_normalize_text | location | 1497 | three-line value becomes `, (lat, lon)`; coordinates kept digit for digit | correct | correct | same change |
| 17 | trim_and_normalize_text | location | 1512 | three-line value becomes `, (lat, lon)`; coordinates kept digit for digit | correct | correct | same change |
| 18 | trim_and_normalize_text | location | 1850 | three-line value becomes `, (lat, lon)`; coordinates kept digit for digit | correct | correct | same change |
| 19 | trim_and_normalize_text | location | 2048 | three-line value becomes `, (lat, lon)`; coordinates kept digit for digit | correct | correct | same change |
| 20 | trim_and_normalize_text | location | 2132 | three-line value becomes `, (lat, lon)`; coordinates kept digit for digit | correct | correct | same change |
| 21 | trim_and_normalize_text | location | 2139 | three-line value becomes `, (lat, lon)`; coordinates kept digit for digit | correct | correct | same change |
| 22 | trim_and_normalize_text | location | 2462 | three-line value becomes `, (lat, lon)`; coordinates kept digit for digit | correct | correct | same change |
| 23 | trim_and_normalize_text | location | 2745 | three-line value becomes `, (lat, lon)`; coordinates kept digit for digit | correct | correct | same change |
| 24 | trim_and_normalize_text | location | 2807 | three-line value becomes `, (lat, lon)`; coordinates kept digit for digit | correct | correct | same change |
| 25 | trim_and_normalize_text | location | 2879 | three-line value becomes `, (lat, lon)`; coordinates kept digit for digit | correct | correct | same change |
| 26 | trim_and_normalize_text | location | 2981 | three-line value becomes `, (lat, lon)`; coordinates kept digit for digit | correct | correct | same change |
| 27 | trim_and_normalize_text | location | 3180 | three-line value becomes `, (lat, lon)`; coordinates kept digit for digit | correct | correct | same change |
| 28 | trim_and_normalize_text | location | 3244 | three-line value becomes `, (lat, lon)`; coordinates kept digit for digit | correct | correct | same change |
| 29 | trim_and_normalize_text | location | 3514 | three-line value becomes `, (lat, lon)`; coordinates kept digit for digit | correct | correct | same change |
| 30 | trim_and_normalize_text | location | 3592 | three-line value becomes `, (lat, lon)`; coordinates kept digit for digit | correct | correct | same change |
| 31 | trim_and_normalize_text | location | 3773 | three-line value becomes `, (lat, lon)`; coordinates kept digit for digit | correct | correct | same change |
| 32 | trim_and_normalize_text | location | 3903 | three-line value becomes `, (lat, lon)`; coordinates kept digit for digit | correct | correct | same change |
| 33 | trim_and_normalize_text | location | 4071 | three-line value becomes `, (lat, lon)`; coordinates kept digit for digit | correct | correct | same change |
| 34 | trim_and_normalize_text | location | 4631 | three-line value becomes `, (lat, lon)`; coordinates kept digit for digit | correct | correct | same change |
| 35 | trim_and_normalize_text | location | 4660 | three-line value becomes `, (lat, lon)`; coordinates kept digit for digit | correct | correct | same change |
| 36 | trim_and_normalize_text | location | 4684 | three-line value becomes `, (lat, lon)`; coordinates kept digit for digit | correct | correct | same change |
| 37 | trim_and_normalize_text | location | 4809 | three-line value becomes `, (lat, lon)`; coordinates kept digit for digit | correct | correct | same change |
| 38 | trim_and_normalize_text | location | 4945 | three-line value becomes `, (lat, lon)`; coordinates kept digit for digit | correct | correct | same change |
| 39 | parse_dates | inspection_date | 147 | `2026-11-03T00:00:00.000` becomes `2026-11-03T00:00:00` | correct | correct | same change |
| 40 | parse_dates | inspection_date | 195 | `2026-11-02T00:00:00.000` becomes `2026-11-02T00:00:00` | correct | correct | same change |
| 41 | parse_dates | inspection_date | 536 | `2026-10-22T00:00:00.000` becomes `2026-10-22T00:00:00` | correct | correct | same change |
| 42 | parse_dates | inspection_date | 541 | `2026-10-22T00:00:00.000` becomes `2026-10-22T00:00:00` | correct | correct | same change |
| 43 | parse_dates | inspection_date | 762 | `2026-10-15T00:00:00.000` becomes `2026-10-15T00:00:00` | correct | correct | same change |
| 44 | parse_dates | inspection_date | 926 | `2026-10-13T00:00:00.000` becomes `2026-10-13T00:00:00` | correct | correct | same change |
| 45 | parse_dates | inspection_date | 1007 | `2026-10-08T00:00:00.000` becomes `2026-10-08T00:00:00` | correct | correct | same change |
| 46 | parse_dates | inspection_date | 1015 | `2026-10-08T00:00:00.000` becomes `2026-10-08T00:00:00` | correct | correct | same change |
| 47 | parse_dates | inspection_date | 1325 | `2026-09-30T00:00:00.000` becomes `2026-09-30T00:00:00` | correct | correct | same change |
| 48 | parse_dates | inspection_date | 1442 | `2026-09-28T00:00:00.000` becomes `2026-09-28T00:00:00` | correct | correct | same change |
| 49 | parse_dates | inspection_date | 1682 | `2026-09-21T00:00:00.000` becomes `2026-09-21T00:00:00` | correct | correct | same change |
| 50 | parse_dates | inspection_date | 1799 | `2026-09-17T00:00:00.000` becomes `2026-09-17T00:00:00` | correct | correct | same change |
| 51 | parse_dates | inspection_date | 2075 | `2026-09-10T00:00:00.000` becomes `2026-09-10T00:00:00` | correct | correct | same change |
| 52 | parse_dates | inspection_date | 2077 | `2026-09-10T00:00:00.000` becomes `2026-09-10T00:00:00` | correct | correct | same change |
| 53 | parse_dates | inspection_date | 2651 | `2026-08-26T00:00:00.000` becomes `2026-08-26T00:00:00` | correct | correct | same change |
| 54 | parse_dates | inspection_date | 2694 | `2026-08-25T00:00:00.000` becomes `2026-08-25T00:00:00` | correct | correct | same change |
| 55 | parse_dates | inspection_date | 3023 | `2026-08-18T00:00:00.000` becomes `2026-08-18T00:00:00` | correct | correct | same change |
| 56 | parse_dates | inspection_date | 3110 | `2026-08-14T00:00:00.000` becomes `2026-08-14T00:00:00` | correct | correct | same change |
| 57 | parse_dates | inspection_date | 3165 | `2026-08-13T00:00:00.000` becomes `2026-08-13T00:00:00` | correct | correct | same change |
| 58 | parse_dates | inspection_date | 3452 | `2026-08-06T00:00:00.000` becomes `2026-08-06T00:00:00` | correct | correct | same change |
| 59 | parse_dates | inspection_date | 3616 | `2026-08-04T00:00:00.000` becomes `2026-08-04T00:00:00` | correct | correct | same change |
| 60 | parse_dates | inspection_date | 4423 | `2026-07-16T00:00:00.000` becomes `2026-07-16T00:00:00` | correct | correct | same change |
| 61 | parse_dates | inspection_date | 4534 | `2026-07-14T00:00:00.000` becomes `2026-07-14T00:00:00` | correct | correct | same change |
| 62 | parse_dates | inspection_date | 4581 | `2026-07-13T00:00:00.000` becomes `2026-07-13T00:00:00` | correct | correct | same change |
| 63 | parse_dates | inspection_date | 4612 | `2026-07-10T00:00:00.000` becomes `2026-07-10T00:00:00` | correct | correct | same change |
| 64 | parse_dates | inspection_date | 4990 | `2026-06-30T00:00:00.000` becomes `2026-06-30T00:00:00` | correct | correct | same change |
| 65 | standardize_categories | city | 22 | `CHICAGO` becomes `Chicago` | debatable | no longer made | CHICAGO is the majority spelling (4,953 of 4,980 rows), so it is left as written |
| 66 | standardize_categories | city | 33 | `CHICAGO` becomes `Chicago` | debatable | no longer made | CHICAGO is the majority spelling (4,953 of 4,980 rows), so it is left as written |
| 67 | standardize_categories | city | 475 | `CHICAGO` becomes `Chicago` | debatable | no longer made | CHICAGO is the majority spelling (4,953 of 4,980 rows), so it is left as written |
| 68 | standardize_categories | city | 638 | `CHICAGO` becomes `Chicago` | debatable | no longer made | CHICAGO is the majority spelling (4,953 of 4,980 rows), so it is left as written |
| 69 | standardize_categories | city | 690 | `CHICAGO` becomes `Chicago` | debatable | no longer made | CHICAGO is the majority spelling (4,953 of 4,980 rows), so it is left as written |
| 70 | standardize_categories | city | 699 | `CHICAGO` becomes `Chicago` | debatable | no longer made | CHICAGO is the majority spelling (4,953 of 4,980 rows), so it is left as written |
| 71 | standardize_categories | city | 760 | `CHICAGO` becomes `Chicago` | debatable | no longer made | CHICAGO is the majority spelling (4,953 of 4,980 rows), so it is left as written |
| 72 | standardize_categories | city | 805 | `CHICAGO` becomes `Chicago` | debatable | no longer made | CHICAGO is the majority spelling (4,953 of 4,980 rows), so it is left as written |
| 73 | standardize_categories | city | 1000 | `CHICAGO` becomes `Chicago` | debatable | no longer made | CHICAGO is the majority spelling (4,953 of 4,980 rows), so it is left as written |
| 74 | standardize_categories | city | 1135 | `CHICAGO` becomes `Chicago` | debatable | no longer made | CHICAGO is the majority spelling (4,953 of 4,980 rows), so it is left as written |
| 75 | standardize_categories | city | 1325 | `CHICAGO` becomes `Chicago` | debatable | no longer made | CHICAGO is the majority spelling (4,953 of 4,980 rows), so it is left as written |
| 76 | standardize_categories | city | 1474 | `CHICAGO` becomes `Chicago` | debatable | no longer made | CHICAGO is the majority spelling (4,953 of 4,980 rows), so it is left as written |
| 77 | standardize_categories | city | 1539 | `CHICAGO` becomes `Chicago` | debatable | no longer made | CHICAGO is the majority spelling (4,953 of 4,980 rows), so it is left as written |
| 78 | standardize_categories | city | 1702 | `CHICAGO` becomes `Chicago` | debatable | no longer made | CHICAGO is the majority spelling (4,953 of 4,980 rows), so it is left as written |
| 79 | standardize_categories | city | 2006 | `CHICAGO` becomes `Chicago` | debatable | no longer made | CHICAGO is the majority spelling (4,953 of 4,980 rows), so it is left as written |
| 80 | standardize_categories | city | 2221 | `CHICAGO` becomes `Chicago` | debatable | no longer made | CHICAGO is the majority spelling (4,953 of 4,980 rows), so it is left as written |
| 81 | standardize_categories | city | 2312 | `CHICAGO` becomes `Chicago` | debatable | no longer made | CHICAGO is the majority spelling (4,953 of 4,980 rows), so it is left as written |
| 82 | standardize_categories | city | 2625 | `CHICAGO` becomes `Chicago` | debatable | no longer made | CHICAGO is the majority spelling (4,953 of 4,980 rows), so it is left as written |
| 83 | standardize_categories | city | 2940 | `CHICAGO` becomes `Chicago` | debatable | no longer made | CHICAGO is the majority spelling (4,953 of 4,980 rows), so it is left as written |
| 84 | standardize_categories | city | 3205 | `CHICAGO` becomes `Chicago` | debatable | no longer made | CHICAGO is the majority spelling (4,953 of 4,980 rows), so it is left as written |
| 85 | standardize_categories | city | 3309 | `CHICAGO` becomes `Chicago` | debatable | no longer made | CHICAGO is the majority spelling (4,953 of 4,980 rows), so it is left as written |
| 86 | standardize_categories | city | 3404 | `CHICAGO` becomes `Chicago` | debatable | no longer made | CHICAGO is the majority spelling (4,953 of 4,980 rows), so it is left as written |
| 87 | standardize_categories | city | 3905 | `CHICAGO` becomes `Chicago` | debatable | no longer made | CHICAGO is the majority spelling (4,953 of 4,980 rows), so it is left as written |
| 88 | standardize_categories | city | 4261 | `CHICAGO` becomes `Chicago` | debatable | no longer made | CHICAGO is the majority spelling (4,953 of 4,980 rows), so it is left as written |
| 89 | standardize_categories | city | 4337 | `CHICAGO` becomes `Chicago` | debatable | no longer made | CHICAGO is the majority spelling (4,953 of 4,980 rows), so it is left as written |
| 90 | standardize_categories | city | 4379 | `CHICAGO` becomes `Chicago` | debatable | no longer made | CHICAGO is the majority spelling (4,953 of 4,980 rows), so it is left as written |
| 91 | standardize_categories | city | 4577 | `CHICAGO` becomes `Chicago` | debatable | no longer made | CHICAGO is the majority spelling (4,953 of 4,980 rows), so it is left as written |
| 92 | standardize_categories | city | 4588 | `CHICAGO` becomes `Chicago` | debatable | no longer made | CHICAGO is the majority spelling (4,953 of 4,980 rows), so it is left as written |
| 93 | standardize_categories | city | 4675 | `CHICAGO` becomes `Chicago` | debatable | no longer made | CHICAGO is the majority spelling (4,953 of 4,980 rows), so it is left as written |
| 94 | standardize_categories | city | 4874 | `CHICAGO` becomes `Chicago` | debatable | no longer made | CHICAGO is the majority spelling (4,953 of 4,980 rows), so it is left as written |
| 95 | standardize_categories | city | 4965 | `CHICAGO` becomes `Chicago` | debatable | no longer made | CHICAGO is the majority spelling (4,953 of 4,980 rows), so it is left as written |
| 96 | standardize_categories | city | 3732 | `CHICAGO.` becomes `Chicago` | correct | correct | now `CHICAGO.` becomes `CHICAGO` (the majority spelling), still an approved suggestion |
| 97 | flag_outliers | license_outlier_flag | 874 | `license_outlier_flag = true` | useless flag | no longer made | license is now an id column, so it gets no outlier flags |
| 98 | flag_outliers | license_outlier_flag | 2162 | `license_outlier_flag = true` | useless flag | no longer made | license is now an id column, so it gets no outlier flags |
| 99 | flag_outliers | license_outlier_flag | 2996 | `license_outlier_flag = true` | useless flag | no longer made | license is now an id column, so it gets no outlier flags |
| 100 | flag_outliers | longitude_outlier_flag | 3982 | `longitude_outlier_flag = true` | useful flag | useful flag | same change |

## Still open for the owner

1. **Line breaks inside cells are joined** (items 9 to 38). Harmless here; worth knowing for address or comment columns.
2. Carried over from M5: uniqueness can fall by about 0.1 point because the long `violations` text counts as a key candidate.

## Reproduce

```
.venv/Scripts/python evaluation/chicago_sample.py
```

The script draws 100 changes from the current engine's change log (11,840 changes now), so its list is no longer
the step 8 list; the table above keeps the original 100.
