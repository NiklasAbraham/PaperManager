import requests
import pandas as pd
import numpy as np
import re
import time

from .utils import *


def filter_result(result):
    text = result['title']
    text = text.lower()
    text = text.replace('-', ' ')
    # OR within query_sets and AND between them
    queries = [
        ["protein*", "peptide*", "antibod*", "nanobod*", "enzyme*", "tcr",
         "t cell receptor*"],
        ["learn*", "deep*", "neural network*", "diffusion*", "transformer*",
         "flow matching", "predict*", "generative",
         "embedding*", "representation", "benchmark*", "supervised*",
         "unsupervised*", "design*", "structure*", "model*"],

    ]
    outcomes = []
    for query_set in queries:
        outcomes.append(
            any([bool(re.search(query, text)) for query in query_set]))
    return all(outcomes)


def process_result(result):
    # Parse date - the one in doi is earliest published date but is not present for old publications
    doi_end = result['doi'].split('/')[-1]
    if len(doi_end.split('.')) > 3:  # Date followed by id
        date = '-'.join(doi_end.split('.')[:3])
    else:
        date = result['date']

    return {
        'title': result['title'],
        'abstract': result['abstract'],
        'doi': result['doi'],
        'date': date,
    }


def fetch_biorxiv_results(date, max_retries=3, retry_delay=5):
    date = date.replace('/', '-')

    cursor_max = np.inf
    cursor_curr = 0
    results = []
    bad_status=False
    while cursor_curr<cursor_max and not bad_status:
        for attempt in range(max_retries):
            try:
                api_url = f'https://api.biorxiv.org/details/biorxiv/{date}/{date}/{cursor_curr}/json'
                response = requests.get(api_url, timeout=30)

                # Check that response is ok for this day
                if response.json()['messages'][0]['status'] != 'ok':
                    print('bioRxiv could not retrieve results with status: ' +
                          response.json()['messages'][0]['status'])
                    bad_status=True
                    break

                # Save filtered results
                results.extend([
                    process_result(res) for res in response.json()["collection"]
                    if filter_result(res)
                ])

                # Increase retrieval counter as API retrieves batches of 100
                message = response.json()['messages'][0]
                if cursor_max == np.inf:
                    cursor_max = int(message['total'])
                cursor_curr += int(message['count'])

                # Finish loop if successful
                break

            except requests.exceptions.RequestException as e:
                if attempt < max_retries - 1:
                    print(
                        f"Error fetching results (attempt {attempt + 1}/{max_retries}): {e}")
                    print(f"Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                else:
                    print(
                        f"Failed to fetch results after {max_retries} attempts: {e}")

    return results


def run_biorxiv_search(start_date, end_date):
    print('Retrieving biorxiv')
    all_results = []

    dates_list = list_dates(start_date, end_date)

    for date in dates_list:

        # Fetch the results
        print(f"Fetching results from bioRxiv API for date {date}...")
        results = fetch_biorxiv_results(date)

        # Print the results
        print(f"\nFound {len(results)} articles for date {date}\n")

        for article in results:
            article['search_date'] = date.replace('/', '-')
            all_results.append(article)

    return pd.DataFrame(all_results)

