# Real public dataset (sample 4)

- **Dataset:** Chicago Food Inspections (City of Chicago Data Portal)
- **Source URL:** https://data.cityofchicago.org/resource/4ijn-s7e5.csv?$limit=5000 (dataset id 4ijn-s7e5)
- **Download date:** 2026-11-11
- **File:** `chicago_food_inspections.csv`, 3,995 data rows (plus header), 17 columns, 3,999,150 bytes (about 3.8 MiB)
- **Trim (2026-11-16):** the file is the first 3,995 records of the 5,000-row download (original 5,003,664 bytes), cut at a record boundary so it stays under the 4 MB live limit. The kept bytes are unchanged; the rest of the download was dropped.
- **Licence:** public domain open data, unmodified (bytes kept as served; do not edit)
- **Evaluation:** excluded from ground-truth evaluation. It has no injected errors and is not in `ground_truth.csv` or `make_samples.py`. Use `score_real_dataset.py` for a report only.
