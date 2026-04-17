# Use
1. Generate environment via `environment.yml` (change install path)
2. Run via `python main.py`

It will save files:
- papers.csv - All papers based on keyword search 
- papers_filtered.csv - Papers that fit the general computational protein design topic via LLM scoring

If no parameters are used in `python main.py` new papers will be sought for all dates since the date of the last paper. The results will be appended to the existing files.
