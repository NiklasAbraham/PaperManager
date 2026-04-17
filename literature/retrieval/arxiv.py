import urllib
import requests
import xml.etree.ElementTree as ET
import time
import pandas as pd

from .utils import *


def construct_arxiv_api_query(date):
    """
    Constructs an arXiv API query URL from the search parameters.

    Args:
        search_params (dict): Dictionary containing search parameters

    Returns:
        str: The constructed API query URL
    """
    base_url = "http://export.arxiv.org/api/query?"

    # Construct the search query
    query_parts = []

    # Add title search terms
    title_terms = []
    for term in ["protein*", "peptide*", "nanobod*", "antibod*", "enzyme*",
                 "T-cell receptor*", "TCR*"]:
        title_terms.append(f"ti:{term}")

    # Combine title terms with OR
    if title_terms:
        query_parts.append("(" + " OR ".join(title_terms) + ")")
    search_query = ''.join(query_parts)

    # Add date range
    date_from = date
    date_to = next_day(date)

    # Format dates for arXiv API (YYYYMMDD format)
    date_from_formatted = date_from.replace('/', '')
    date_to_formatted = date_to.replace('/', '')

    search_query += f" AND submittedDate:[{date_from_formatted} TO {date_to_formatted}]"

    # URL encode the query
    encoded_query = urllib.parse.quote(search_query)

    # Construct the final URL with parameters
    params = {
        "search_query": encoded_query,
        "start": 0,
        "max_results": 200,
        "sortBy": "submittedDate",
        "sortOrder": "descending"
    }

    query_string = "&".join([f"{k}={v}" for k, v in params.items()])

    final_query = base_url + query_string
    return final_query


def fetch_arxiv_results(api_url, max_retries=3, retry_delay=10):
    """
    Fetches results from the arXiv API with retry mechanism.

    Args:
        api_url (str): The API URL to fetch results from
        max_retries (int): Maximum number of retry attempts
        retry_delay (int): Initial delay between retries in seconds (doubles on each retry)

    Returns:
        list: List of dictionaries containing article information
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    current_delay = retry_delay
    for attempt in range(max_retries):
        try:
            response = requests.get(api_url, headers=headers, timeout=60)
            response.raise_for_status()

            # Parse the XML response
            root = ET.fromstring(response.content)

            # Define the XML namespace
            ns = {'atom': 'http://www.w3.org/2005/Atom',
                  'arxiv': 'http://arxiv.org/schemas/atom'}

            # Extract entries
            entries = root.findall('.//atom:entry', ns)

            results = []
            for entry in entries:
                # Extract basic metadata
                title = entry.find('./atom:title', ns).text.strip()
                abstract = entry.find('./atom:summary', ns).text.strip()
                published = entry.find('./atom:published', ns).text.split('T')[
                    0]

                # Extract DOI if available
                doi = None
                for link in entry.findall('./atom:link', ns):
                    if link.get('title') == 'doi':
                        doi = link.get('href')

                # Extract arXiv ID
                id_url = entry.find('./atom:id', ns).text
                arxiv_id = id_url.split('/')[-1]

                # If no DOI is found, create the arXiv DOI
                if not doi:
                    doi = f"https://doi.org/10.48550/arXiv.{arxiv_id.split('v')[0]}"

                results.append({
                    'title': title,
                    'abstract': abstract,
                    'date': published,
                    'doi': doi,
                })

            return results

        except requests.exceptions.RequestException as e:
            if attempt < max_retries - 1:
                print(
                    f"Error fetching results (attempt {attempt + 1}/{max_retries}): {e}")
                print(f"Retrying in {current_delay} seconds...")
                time.sleep(current_delay)
                current_delay *= 2  # Exponential backoff
            else:
                print(
                    f"Failed to fetch results after {max_retries} attempts: {e}")
                return []


def run_arxiv_search(start_date, end_date):
    print('Retrieving arxiv')
    all_results = []

    dates_list = list_dates(start_date, end_date)

    for date in dates_list:
        # Construct the API query URL
        api_url = construct_arxiv_api_query(date)

        # Fetch the results
        print(f"Fetching results from arXiv API for date {date}...")
        results = fetch_arxiv_results(api_url)

        # Respect arXiv rate limit (min 3s between requests)
        time.sleep(3)

        # Print the results
        print(f"\nFound {len(results)} articles for date {date}\n")

        for article in results:
            article['search_date'] = date.replace('/', '-')
            all_results.append(article)

    return pd.DataFrame(all_results)


