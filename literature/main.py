import argparse
import os
from datetime import datetime

import pandas as pd

from retrieval.main import retrieve_all
from scoring.topic import score


def main():
    fn_full = 'data/papers.csv'
    fn_filtered = 'data/papers_filtered.csv'

    if os.path.isfile(fn_filtered):
        postprocess_filtered(fn_filtered)

    parser = argparse.ArgumentParser()

    # Add arguments
    parser.add_argument('-s', '--start_date', type=str, required=False)
    parser.add_argument('-e', '--end_date', type=str, required=False)

    args = parser.parse_args()
    if not args.start_date:
        dates = pd.read_csv(fn_full)['search_date'].unique()
        # Include last date as well since the search may not have been at EOD
        args.start_date = max([
            datetime.strptime(date, "%Y-%m-%d") for date in dates
        ]).strftime("%Y/%m/%d")
        args.end_date = datetime.today().strftime("%Y/%m/%d")

    if not args.end_date:
        args.end_date = args.start_date

    # Retrieve
    papers = retrieve_all(
        start_date=args.start_date, end_date=args.end_date,
        email='karin.hrovatin@merckgroup.com'
    )

    if papers.shape[0] > 0:

        # Deduplicate
        # Unify how doi is represented across databases
        papers['doi'] = papers.doi.str.replace('https://doi.org/', '')
        papers.drop_duplicates(subset='doi', keep='first', inplace=True)

        # Keep only new papers that have not been added before
        # Note - papers without doi will stay duplicated
        if os.path.isfile(fn_full):
            existing_dois = set(pd.read_csv(fn_full)['doi'].unique())
            papers = papers.query('~doi.isin(@existing_dois)').copy()

    # Redo check as some papers may have been removed
    if papers.shape[0] > 0:
        # Score
        papers['topic_score'] = score(papers)
        papers_filtered = papers.query('topic_score>0.55')

        # Save

        # Make sure columns align
        def align_columns(df, cols):
            df = df.copy()
            for col in cols:
                if col not in df.columns:
                    df[col] = None
            return df[cols].copy()

        if os.path.isfile(fn_full):
            papers = align_columns(papers, pd.read_csv(fn_full).columns)
        if os.path.isfile(fn_filtered):
            papers_filtered = align_columns(papers_filtered, pd.read_csv(fn_filtered).columns)

        papers.to_csv(
            fn_full, index=False, mode='a',
            header=not os.path.isfile(fn_full))
        papers_filtered.to_csv(
            fn_filtered, index=False, mode='a',
            header=not os.path.isfile(fn_filtered))


def postprocess_filtered(fn_filtered):
    data = pd.read_csv(fn_filtered, na_values='', keep_default_na=False)
    data['highlight'] = data['highlight'].fillna(0)
    data.to_csv(fn_filtered, index=False)

if __name__ == "__main__":
    main()
