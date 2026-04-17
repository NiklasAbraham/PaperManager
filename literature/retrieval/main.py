import pandas as pd
from warnings import warn

from .pubmed import run_pubmed_search
from .arxiv import run_arxiv_search
from .biorxiv import run_biorxiv_search


def retrieve_all(start_date, end_date, email):
    results = []

    pubmed = run_pubmed_search(
        email=email, start_date=start_date, end_date=end_date)
    pubmed['database'] = 'pubmed'
    results.append(pubmed)

    arxiv = run_arxiv_search(start_date=start_date, end_date=end_date)
    arxiv['database'] = 'arxiv'
    results.append(arxiv)

    biorxiv = run_biorxiv_search(start_date=start_date, end_date=end_date)
    biorxiv['database'] = 'biorxiv'
    results.append(biorxiv)

    results = pd.concat(results)
    return results
