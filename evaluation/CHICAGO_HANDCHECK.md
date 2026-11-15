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

## Second sample (M6 step 9)

**Date:** 2026-11-15. **Who checked:** Claude judged every item below; the project owner has not reviewed them.

**How the sample was drawn.** The Chicago file was cleaned with the engine on `main` (commit ac00c39), every
proposal approved, exactly as `evaluation/chicago_sample.py` does. A copy of that script with only the seed changed
(`SEED = 20261115`) then took `sorted(random.Random(20261115).sample(range(len(log)), 100))` over the rows of
`changelog.csv` in file order, and the 100 changes at those positions are listed below in that order. To reproduce,
change `SEED = 8` to `SEED = 20261115` in a copy of `chicago_sample.py` and run it. The draw shares one item with the
first sample by chance (row 1442, `inspection_date`); the other 99 are new.

**Total changes in the clean:** 11,840 (trim_and_normalize_text 6,666; parse_dates 5,000; flag_outliers 144, that is
143 flags plus one added column; standardize_categories 29; normalize_headers 1). Same total as step 8b.

**Method per item.** For each change the old value was compared with the raw file cell at that row and column, and
the new value with the same cell in clean.csv (all 100 match). For the trim changes the old text with whitespace
collapsed was checked to equal the new text exactly. For the two outlier flags the raw row and the column's IQR fence
were looked up.

| Verdict | Count |
|---|---:|
| Correct | 98 |
| Debatable | 0 |
| Useful flag | 2 |
| Useless flag | 0 |
| Wrong (meaning changed or data lost) | **0** |

**Reading the result.** The sample mirrors the change log: 44 location line-break joins, 42 date reformats, 12
double-space fixes (10 in the inspection notes, one business name, one address) and 2 longitude flags. The 29
category merges are 0.25% of all changes, so this draw contains none; the earlier sample's re-check covers that rule.
Both flags are O'Hare airport (11601 W TOUHY AVE). 93 of the 143 longitude flags are in zip 60666 (O'Hare); they are
true outliers by distance but genuine locations, so a user may find most longitude flags of little use.

| # | row_id | Column | Rule | Old value | New value | Reason | Verdict | Note |
|---|---:|---|---|---|---|---|---|---|
| 1 | 1315 | dba_name | trim_and_normalize_text | `FRAZIER  INTERNATIONAL` | `FRAZIER INTERNATIONAL` | (none) | correct | double space inside the business name becomes one; name otherwise as written |
| 2 | 2070 | address | trim_and_normalize_text | `1420 W 17th St  (1700S)` | `1420 W 17th St (1700S)` | (none) | correct | double space before `(1700S)` becomes one; the unusual mixed case and the `(1700S)` note are kept |
| 3 | 748 | violations | trim_and_normalize_text | `...PAIR, AND MAINTAIN.  PRIORITY FOUNDATION... (2149 chars)` | `...PAIR, AND MAINTAIN. PRIORITY FOUNDATION ... (2140 chars)` | (none) | correct | inspection notes: 9 extra space(s) removed (double spaces between words or sentences); checked that collapsing whitespace in the old text gives exactly the new text, no word changed |
| 4 | 931 | violations | trim_and_normalize_text | `... Comments: 2-101.11  OBSERVED NO CERTIFI... (2941 chars)` | `... Comments: 2-101.11 OBSERVED NO CERTIFIE... (2920 chars)` | (none) | correct | inspection notes: 21 extra space(s) removed (double spaces between words or sentences); checked that collapsing whitespace in the old text gives exactly the new text, no word changed |
| 5 | 1400 | violations | trim_and_normalize_text | `...TRUCTED TO PROVIDE.  INSTRUCTED TO PROVI... (1524 chars)` | `...TRUCTED TO PROVIDE. INSTRUCTED TO PROVID... (1519 chars)` | (none) | correct | inspection notes: 5 extra space(s) removed (double spaces between words or sentences); checked that collapsing whitespace in the old text gives exactly the new text, no word changed |
| 6 | 1833 | violations | trim_and_normalize_text | `...NO CITATION ISSUED.  \| 23. PROPER DATE M... (1348 chars)` | `...NO CITATION ISSUED. \| 23. PROPER DATE MA... (1345 chars)` | (none) | correct | inspection notes: 3 extra space(s) removed (double spaces between words or sentences); checked that collapsing whitespace in the old text gives exactly the new text, no word changed |
| 7 | 1992 | violations | trim_and_normalize_text | `...D DRY STORAGE AREA.  INSTRUCTED TO DETAI... (4984 chars)` | `...D DRY STORAGE AREA. INSTRUCTED TO DETAIL... (4983 chars)` | (none) | correct | inspection notes: 1 extra space(s) removed (double spaces between words or sentences); checked that collapsing whitespace in the old text gives exactly the new text, no word changed |
| 8 | 3728 | violations | trim_and_normalize_text | `...OR COOKED TO ORDER.  PRIORITY FOUNDATION... (2678 chars)` | `...OR COOKED TO ORDER. PRIORITY FOUNDATION ... (2677 chars)` | (none) | correct | inspection notes: 1 extra space(s) removed (double spaces between words or sentences); checked that collapsing whitespace in the old text gives exactly the new text, no word changed |
| 9 | 4108 | violations | trim_and_normalize_text | `...NAGERS CERTIFICATE.  A SERV SAFE CERTIFI... (2616 chars)` | `...NAGERS CERTIFICATE. A SERV SAFE CERTIFIC... (2605 chars)` | (none) | correct | inspection notes: 11 extra space(s) removed (double spaces between words or sentences); checked that collapsing whitespace in the old text gives exactly the new text, no word changed |
| 10 | 4515 | violations | trim_and_normalize_text | `...IOLATION. 7-38-005.  \| 10. ADEQUATE HAND... (1249 chars)` | `...IOLATION. 7-38-005. \| 10. ADEQUATE HANDW... (1247 chars)` | (none) | correct | inspection notes: 2 extra space(s) removed (double spaces between words or sentences); checked that collapsing whitespace in the old text gives exactly the new text, no word changed |
| 11 | 4532 | violations | trim_and_normalize_text | `...TION. MUST PROVIDE.  \| 2. CITY OF CHICAG... (2155 chars)` | `...TION. MUST PROVIDE. \| 2. CITY OF CHICAGO... (2143 chars)` | (none) | correct | inspection notes: 12 extra space(s) removed (double spaces between words or sentences); checked that collapsing whitespace in the old text gives exactly the new text, no word changed |
| 12 | 4606 | violations | trim_and_normalize_text | `...ILET ROOM AT 77.7F,  WAREWASHING UNIT AT... (397 chars)` | `...ILET ROOM AT 77.7F, WAREWASHING UNIT AT ... (396 chars)` | (none) | correct | inspection notes: 1 extra space(s) removed (double spaces between words or sentences); checked that collapsing whitespace in the old text gives exactly the new text, no word changed |
| 13 | 153 | location | trim_and_normalize_text | `\n,  \n(41.77425214886086, -87.64449654993336)` | `, (41.77425214886086, -87.64449654993336)` | (none) | correct | line breaks and padding removed; coordinates kept digit for digit (empty address part still leaves a leading comma, as in the source) |
| 14 | 158 | location | trim_and_normalize_text | `\n,  \n(41.88695873095325, -87.62468732307848)` | `, (41.88695873095325, -87.62468732307848)` | (none) | correct | line breaks and padding removed; coordinates kept digit for digit (empty address part still leaves a leading comma, as in the source) |
| 15 | 321 | location | trim_and_normalize_text | `\n,  \n(41.9380068184394, -87.64892450543655)` | `, (41.9380068184394, -87.64892450543655)` | (none) | correct | line breaks and padding removed; coordinates kept digit for digit (empty address part still leaves a leading comma, as in the source) |
| 16 | 336 | location | trim_and_normalize_text | `\n,  \n(41.89460677907168, -87.77483418779396)` | `, (41.89460677907168, -87.77483418779396)` | (none) | correct | line breaks and padding removed; coordinates kept digit for digit (empty address part still leaves a leading comma, as in the source) |
| 17 | 488 | location | trim_and_normalize_text | `\n,  \n(41.96634736406373, -87.68898364635334)` | `, (41.96634736406373, -87.68898364635334)` | (none) | correct | line breaks and padding removed; coordinates kept digit for digit (empty address part still leaves a leading comma, as in the source) |
| 18 | 578 | location | trim_and_normalize_text | `\n,  \n(41.917458568356686, -87.6851026411648)` | `, (41.917458568356686, -87.6851026411648)` | (none) | correct | line breaks and padding removed; coordinates kept digit for digit (empty address part still leaves a leading comma, as in the source) |
| 19 | 767 | location | trim_and_normalize_text | `\n,  \n(41.8139405139736, -87.60680964252573)` | `, (41.8139405139736, -87.60680964252573)` | (none) | correct | line breaks and padding removed; coordinates kept digit for digit (empty address part still leaves a leading comma, as in the source) |
| 20 | 773 | location | trim_and_normalize_text | `\n,  \n(41.8578590994683, -87.65550935859257)` | `, (41.8578590994683, -87.65550935859257)` | (none) | correct | line breaks and padding removed; coordinates kept digit for digit (empty address part still leaves a leading comma, as in the source) |
| 21 | 833 | location | trim_and_normalize_text | `\n,  \n(41.70074439002482, -87.64278838501865)` | `, (41.70074439002482, -87.64278838501865)` | (none) | correct | line breaks and padding removed; coordinates kept digit for digit (empty address part still leaves a leading comma, as in the source) |
| 22 | 842 | location | trim_and_normalize_text | `\n,  \n(41.89555031857086, -87.71842104357972)` | `, (41.89555031857086, -87.71842104357972)` | (none) | correct | line breaks and padding removed; coordinates kept digit for digit (empty address part still leaves a leading comma, as in the source) |
| 23 | 913 | location | trim_and_normalize_text | `\n,  \n(41.8808046152, -87.71137549591673)` | `, (41.8808046152, -87.71137549591673)` | (none) | correct | line breaks and padding removed; coordinates kept digit for digit (empty address part still leaves a leading comma, as in the source) |
| 24 | 954 | location | trim_and_normalize_text | `\n,  \n(41.98827210388373, -87.66035869613218)` | `, (41.98827210388373, -87.66035869613218)` | (none) | correct | line breaks and padding removed; coordinates kept digit for digit (empty address part still leaves a leading comma, as in the source) |
| 25 | 998 | location | trim_and_normalize_text | `\n,  \n(41.89161959288818, -87.67463356354423)` | `, (41.89161959288818, -87.67463356354423)` | (none) | correct | line breaks and padding removed; coordinates kept digit for digit (empty address part still leaves a leading comma, as in the source) |
| 26 | 1189 | location | trim_and_normalize_text | `\n,  \n(41.772536534600356, -87.58644483344753)` | `, (41.772536534600356, -87.58644483344753)` | (none) | correct | line breaks and padding removed; coordinates kept digit for digit (empty address part still leaves a leading comma, as in the source) |
| 27 | 1216 | location | trim_and_normalize_text | `\n,  \n(41.80106790853049, -87.70883469410418)` | `, (41.80106790853049, -87.70883469410418)` | (none) | correct | line breaks and padding removed; coordinates kept digit for digit (empty address part still leaves a leading comma, as in the source) |
| 28 | 1372 | location | trim_and_normalize_text | `\n,  \n(41.696086647178035, -87.6089453328002)` | `, (41.696086647178035, -87.6089453328002)` | (none) | correct | line breaks and padding removed; coordinates kept digit for digit (empty address part still leaves a leading comma, as in the source) |
| 29 | 1464 | location | trim_and_normalize_text | `\n,  \n(41.84446768480462, -87.71671532542946)` | `, (41.84446768480462, -87.71671532542946)` | (none) | correct | line breaks and padding removed; coordinates kept digit for digit (empty address part still leaves a leading comma, as in the source) |
| 30 | 1757 | location | trim_and_normalize_text | `\n,  \n(41.7951714122641, -87.5970170811026)` | `, (41.7951714122641, -87.5970170811026)` | (none) | correct | line breaks and padding removed; coordinates kept digit for digit (empty address part still leaves a leading comma, as in the source) |
| 31 | 2179 | location | trim_and_normalize_text | `\n,  \n(41.88903824289138, -87.65209006191907)` | `, (41.88903824289138, -87.65209006191907)` | (none) | correct | line breaks and padding removed; coordinates kept digit for digit (empty address part still leaves a leading comma, as in the source) |
| 32 | 2252 | location | trim_and_normalize_text | `\n,  \n(41.77322973389133, -87.60591766980235)` | `, (41.77322973389133, -87.60591766980235)` | (none) | correct | line breaks and padding removed; coordinates kept digit for digit (empty address part still leaves a leading comma, as in the source) |
| 33 | 2466 | location | trim_and_normalize_text | `\n,  \n(41.90912708426858, -87.79549071389428)` | `, (41.90912708426858, -87.79549071389428)` | (none) | correct | line breaks and padding removed; coordinates kept digit for digit (empty address part still leaves a leading comma, as in the source) |
| 34 | 2632 | location | trim_and_normalize_text | `\n,  \n(41.91737007807033, -87.6982492595568)` | `, (41.91737007807033, -87.6982492595568)` | (none) | correct | line breaks and padding removed; coordinates kept digit for digit (empty address part still leaves a leading comma, as in the source) |
| 35 | 3068 | location | trim_and_normalize_text | `\n,  \n(41.80962869787754, -87.60736973785798)` | `, (41.80962869787754, -87.60736973785798)` | (none) | correct | line breaks and padding removed; coordinates kept digit for digit (empty address part still leaves a leading comma, as in the source) |
| 36 | 3096 | location | trim_and_normalize_text | `\n,  \n(41.74473083947384, -87.55403913753914)` | `, (41.74473083947384, -87.55403913753914)` | (none) | correct | line breaks and padding removed; coordinates kept digit for digit (empty address part still leaves a leading comma, as in the source) |
| 37 | 3228 | location | trim_and_normalize_text | `\n,  \n(41.7397504818082, -87.58585674948006)` | `, (41.7397504818082, -87.58585674948006)` | (none) | correct | line breaks and padding removed; coordinates kept digit for digit (empty address part still leaves a leading comma, as in the source) |
| 38 | 3252 | location | trim_and_normalize_text | `\n,  \n(42.01948985104065, -87.67205666727395)` | `, (42.01948985104065, -87.67205666727395)` | (none) | correct | line breaks and padding removed; coordinates kept digit for digit (empty address part still leaves a leading comma, as in the source) |
| 39 | 3395 | location | trim_and_normalize_text | `\n,  \n(41.74730974866953, -87.6635054676502)` | `, (41.74730974866953, -87.6635054676502)` | (none) | correct | line breaks and padding removed; coordinates kept digit for digit (empty address part still leaves a leading comma, as in the source) |
| 40 | 3443 | location | trim_and_normalize_text | `\n,  \n(41.99539958897028, -87.6997113393183)` | `, (41.99539958897028, -87.6997113393183)` | (none) | correct | line breaks and padding removed; coordinates kept digit for digit (empty address part still leaves a leading comma, as in the source) |
| 41 | 3485 | location | trim_and_normalize_text | `\n,  \n(41.76587080075327, -87.58646836805688)` | `, (41.76587080075327, -87.58646836805688)` | (none) | correct | line breaks and padding removed; coordinates kept digit for digit (empty address part still leaves a leading comma, as in the source) |
| 42 | 3653 | location | trim_and_normalize_text | `\n,  \n(41.737261528894834, -87.57557560680759)` | `, (41.737261528894834, -87.57557560680759)` | (none) | correct | line breaks and padding removed; coordinates kept digit for digit (empty address part still leaves a leading comma, as in the source) |
| 43 | 3659 | location | trim_and_normalize_text | `\n,  \n(41.8445312897657, -87.66011645213311)` | `, (41.8445312897657, -87.66011645213311)` | (none) | correct | line breaks and padding removed; coordinates kept digit for digit (empty address part still leaves a leading comma, as in the source) |
| 44 | 3716 | location | trim_and_normalize_text | `\n,  \n(41.92163237713568, -87.65325613745081)` | `, (41.92163237713568, -87.65325613745081)` | (none) | correct | line breaks and padding removed; coordinates kept digit for digit (empty address part still leaves a leading comma, as in the source) |
| 45 | 3841 | location | trim_and_normalize_text | `\n,  \n(41.968423847600164, -87.72135178109974)` | `, (41.968423847600164, -87.72135178109974)` | (none) | correct | line breaks and padding removed; coordinates kept digit for digit (empty address part still leaves a leading comma, as in the source) |
| 46 | 3902 | location | trim_and_normalize_text | `\n,  \n(41.89395585670853, -87.62854664840329)` | `, (41.89395585670853, -87.62854664840329)` | (none) | correct | line breaks and padding removed; coordinates kept digit for digit (empty address part still leaves a leading comma, as in the source) |
| 47 | 4019 | location | trim_and_normalize_text | `\n,  \n(41.939921544007646, -87.6603982715363)` | `, (41.939921544007646, -87.6603982715363)` | (none) | correct | line breaks and padding removed; coordinates kept digit for digit (empty address part still leaves a leading comma, as in the source) |
| 48 | 4065 | location | trim_and_normalize_text | `\n,  \n(42.00875076599798, -87.90687413400109)` | `, (42.00875076599798, -87.90687413400109)` | (none) | correct | line breaks and padding removed; coordinates kept digit for digit (empty address part still leaves a leading comma, as in the source) |
| 49 | 4089 | location | trim_and_normalize_text | `\n,  \n(41.94419899230355, -87.74715728156374)` | `, (41.94419899230355, -87.74715728156374)` | (none) | correct | line breaks and padding removed; coordinates kept digit for digit (empty address part still leaves a leading comma, as in the source) |
| 50 | 4120 | location | trim_and_normalize_text | `\n,  \n(41.75817409333064, -87.62199444753409)` | `, (41.75817409333064, -87.62199444753409)` | (none) | correct | line breaks and padding removed; coordinates kept digit for digit (empty address part still leaves a leading comma, as in the source) |
| 51 | 4228 | location | trim_and_normalize_text | `\n,  \n(41.874081965880684, -87.68092243741066)` | `, (41.874081965880684, -87.68092243741066)` | (none) | correct | line breaks and padding removed; coordinates kept digit for digit (empty address part still leaves a leading comma, as in the source) |
| 52 | 4308 | location | trim_and_normalize_text | `\n,  \n(41.89558430998033, -87.65538895169536)` | `, (41.89558430998033, -87.65538895169536)` | (none) | correct | line breaks and padding removed; coordinates kept digit for digit (empty address part still leaves a leading comma, as in the source) |
| 53 | 4335 | location | trim_and_normalize_text | `\n,  \n(41.93988699458274, -87.64424769774926)` | `, (41.93988699458274, -87.64424769774926)` | (none) | correct | line breaks and padding removed; coordinates kept digit for digit (empty address part still leaves a leading comma, as in the source) |
| 54 | 4382 | location | trim_and_normalize_text | `\n,  \n(41.81644707189336, -87.62317587391068)` | `, (41.81644707189336, -87.62317587391068)` | (none) | correct | line breaks and padding removed; coordinates kept digit for digit (empty address part still leaves a leading comma, as in the source) |
| 55 | 4437 | location | trim_and_normalize_text | `\n,  \n(41.88135886163692, -87.66524938888526)` | `, (41.88135886163692, -87.66524938888526)` | (none) | correct | line breaks and padding removed; coordinates kept digit for digit (empty address part still leaves a leading comma, as in the source) |
| 56 | 4542 | location | trim_and_normalize_text | `\n,  \n(41.8915590423211, -87.62813937546481)` | `, (41.8915590423211, -87.62813937546481)` | (none) | correct | line breaks and padding removed; coordinates kept digit for digit (empty address part still leaves a leading comma, as in the source) |
| 57 | 6 | inspection_date | parse_dates | `2026-11-10T00:00:00.000` | `2026-11-10T00:00:00` | (none) | correct | only the zero milliseconds `.000` are dropped; date and time unchanged |
| 58 | 282 | inspection_date | parse_dates | `2026-10-29T00:00:00.000` | `2026-10-29T00:00:00` | (none) | correct | only the zero milliseconds `.000` are dropped; date and time unchanged |
| 59 | 622 | inspection_date | parse_dates | `2026-10-20T00:00:00.000` | `2026-10-20T00:00:00` | (none) | correct | only the zero milliseconds `.000` are dropped; date and time unchanged |
| 60 | 689 | inspection_date | parse_dates | `2026-10-19T00:00:00.000` | `2026-10-19T00:00:00` | (none) | correct | only the zero milliseconds `.000` are dropped; date and time unchanged |
| 61 | 744 | inspection_date | parse_dates | `2026-10-16T00:00:00.000` | `2026-10-16T00:00:00` | (none) | correct | only the zero milliseconds `.000` are dropped; date and time unchanged |
| 62 | 858 | inspection_date | parse_dates | `2026-10-14T00:00:00.000` | `2026-10-14T00:00:00` | (none) | correct | only the zero milliseconds `.000` are dropped; date and time unchanged |
| 63 | 888 | inspection_date | parse_dates | `2026-10-13T00:00:00.000` | `2026-10-13T00:00:00` | (none) | correct | only the zero milliseconds `.000` are dropped; date and time unchanged |
| 64 | 1127 | inspection_date | parse_dates | `2026-10-06T00:00:00.000` | `2026-10-06T00:00:00` | (none) | correct | only the zero milliseconds `.000` are dropped; date and time unchanged |
| 65 | 1442 | inspection_date | parse_dates | `2026-09-28T00:00:00.000` | `2026-09-28T00:00:00` | (none) | correct | only the zero milliseconds `.000` are dropped; date and time unchanged |
| 66 | 1589 | inspection_date | parse_dates | `2026-09-23T00:00:00.000` | `2026-09-23T00:00:00` | (none) | correct | only the zero milliseconds `.000` are dropped; date and time unchanged |
| 67 | 1748 | inspection_date | parse_dates | `2026-09-18T00:00:00.000` | `2026-09-18T00:00:00` | (none) | correct | only the zero milliseconds `.000` are dropped; date and time unchanged |
| 68 | 1792 | inspection_date | parse_dates | `2026-09-17T00:00:00.000` | `2026-09-17T00:00:00` | (none) | correct | only the zero milliseconds `.000` are dropped; date and time unchanged |
| 69 | 1986 | inspection_date | parse_dates | `2026-09-14T00:00:00.000` | `2026-09-14T00:00:00` | (none) | correct | only the zero milliseconds `.000` are dropped; date and time unchanged |
| 70 | 2144 | inspection_date | parse_dates | `2026-09-09T00:00:00.000` | `2026-09-09T00:00:00` | (none) | correct | only the zero milliseconds `.000` are dropped; date and time unchanged |
| 71 | 2172 | inspection_date | parse_dates | `2026-09-08T00:00:00.000` | `2026-09-08T00:00:00` | (none) | correct | only the zero milliseconds `.000` are dropped; date and time unchanged |
| 72 | 2219 | inspection_date | parse_dates | `2026-09-08T00:00:00.000` | `2026-09-08T00:00:00` | (none) | correct | only the zero milliseconds `.000` are dropped; date and time unchanged |
| 73 | 2243 | inspection_date | parse_dates | `2026-09-04T00:00:00.000` | `2026-09-04T00:00:00` | (none) | correct | only the zero milliseconds `.000` are dropped; date and time unchanged |
| 74 | 2259 | inspection_date | parse_dates | `2026-09-03T00:00:00.000` | `2026-09-03T00:00:00` | (none) | correct | only the zero milliseconds `.000` are dropped; date and time unchanged |
| 75 | 2428 | inspection_date | parse_dates | `2026-09-01T00:00:00.000` | `2026-09-01T00:00:00` | (none) | correct | only the zero milliseconds `.000` are dropped; date and time unchanged |
| 76 | 2810 | inspection_date | parse_dates | `2026-08-21T00:00:00.000` | `2026-08-21T00:00:00` | (none) | correct | only the zero milliseconds `.000` are dropped; date and time unchanged |
| 77 | 3077 | inspection_date | parse_dates | `2026-08-17T00:00:00.000` | `2026-08-17T00:00:00` | (none) | correct | only the zero milliseconds `.000` are dropped; date and time unchanged |
| 78 | 3246 | inspection_date | parse_dates | `2026-08-12T00:00:00.000` | `2026-08-12T00:00:00` | (none) | correct | only the zero milliseconds `.000` are dropped; date and time unchanged |
| 79 | 3277 | inspection_date | parse_dates | `2026-08-11T00:00:00.000` | `2026-08-11T00:00:00` | (none) | correct | only the zero milliseconds `.000` are dropped; date and time unchanged |
| 80 | 3339 | inspection_date | parse_dates | `2026-08-10T00:00:00.000` | `2026-08-10T00:00:00` | (none) | correct | only the zero milliseconds `.000` are dropped; date and time unchanged |
| 81 | 3340 | inspection_date | parse_dates | `2026-08-10T00:00:00.000` | `2026-08-10T00:00:00` | (none) | correct | only the zero milliseconds `.000` are dropped; date and time unchanged |
| 82 | 3473 | inspection_date | parse_dates | `2026-08-06T00:00:00.000` | `2026-08-06T00:00:00` | (none) | correct | only the zero milliseconds `.000` are dropped; date and time unchanged |
| 83 | 3635 | inspection_date | parse_dates | `2026-08-04T00:00:00.000` | `2026-08-04T00:00:00` | (none) | correct | only the zero milliseconds `.000` are dropped; date and time unchanged |
| 84 | 3636 | inspection_date | parse_dates | `2026-08-04T00:00:00.000` | `2026-08-04T00:00:00` | (none) | correct | only the zero milliseconds `.000` are dropped; date and time unchanged |
| 85 | 3655 | inspection_date | parse_dates | `2026-08-03T00:00:00.000` | `2026-08-03T00:00:00` | (none) | correct | only the zero milliseconds `.000` are dropped; date and time unchanged |
| 86 | 3760 | inspection_date | parse_dates | `2026-07-30T00:00:00.000` | `2026-07-30T00:00:00` | (none) | correct | only the zero milliseconds `.000` are dropped; date and time unchanged |
| 87 | 3776 | inspection_date | parse_dates | `2026-07-30T00:00:00.000` | `2026-07-30T00:00:00` | (none) | correct | only the zero milliseconds `.000` are dropped; date and time unchanged |
| 88 | 3807 | inspection_date | parse_dates | `2026-07-30T00:00:00.000` | `2026-07-30T00:00:00` | (none) | correct | only the zero milliseconds `.000` are dropped; date and time unchanged |
| 89 | 4020 | inspection_date | parse_dates | `2026-07-27T00:00:00.000` | `2026-07-27T00:00:00` | (none) | correct | only the zero milliseconds `.000` are dropped; date and time unchanged |
| 90 | 4076 | inspection_date | parse_dates | `2026-07-24T00:00:00.000` | `2026-07-24T00:00:00` | (none) | correct | only the zero milliseconds `.000` are dropped; date and time unchanged |
| 91 | 4165 | inspection_date | parse_dates | `2026-07-23T00:00:00.000` | `2026-07-23T00:00:00` | (none) | correct | only the zero milliseconds `.000` are dropped; date and time unchanged |
| 92 | 4408 | inspection_date | parse_dates | `2026-07-16T00:00:00.000` | `2026-07-16T00:00:00` | (none) | correct | only the zero milliseconds `.000` are dropped; date and time unchanged |
| 93 | 4506 | inspection_date | parse_dates | `2026-07-14T00:00:00.000` | `2026-07-14T00:00:00` | (none) | correct | only the zero milliseconds `.000` are dropped; date and time unchanged |
| 94 | 4609 | inspection_date | parse_dates | `2026-07-10T00:00:00.000` | `2026-07-10T00:00:00` | (none) | correct | only the zero milliseconds `.000` are dropped; date and time unchanged |
| 95 | 4760 | inspection_date | parse_dates | `2026-07-07T00:00:00.000` | `2026-07-07T00:00:00` | (none) | correct | only the zero milliseconds `.000` are dropped; date and time unchanged |
| 96 | 4824 | inspection_date | parse_dates | `2026-07-06T00:00:00.000` | `2026-07-06T00:00:00` | (none) | correct | only the zero milliseconds `.000` are dropped; date and time unchanged |
| 97 | 4841 | inspection_date | parse_dates | `2026-07-06T00:00:00.000` | `2026-07-06T00:00:00` | (none) | correct | only the zero milliseconds `.000` are dropped; date and time unchanged |
| 98 | 4995 | inspection_date | parse_dates | `2026-06-30T00:00:00.000` | `2026-06-30T00:00:00` | (none) | correct | only the zero milliseconds `.000` are dropped; date and time unchanged |
| 99 | 2675 | longitude_outlier_flag | flag_outliers | `(empty)` | `true` | (none) | useful flag | longitude -87.90687 at 11601 W TOUHY AVE (O'Hare airport, zip 60666), far west of the fence -87.811; a real outlier by distance, but a genuine location, not an error; value unchanged |
| 100 | 2754 | longitude_outlier_flag | flag_outliers | `(empty)` | `true` | (none) | useful flag | longitude -87.90687 at 11601 W TOUHY AVE (O'Hare airport, zip 60666), far west of the fence -87.811; a real outlier by distance, but a genuine location, not an error; value unchanged |
