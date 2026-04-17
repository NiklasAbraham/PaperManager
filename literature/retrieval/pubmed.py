from Bio import Entrez
import pandas as pd
import time

from .utils import *


# Define the function to search PubMed with a date range
def search_pubmed_by_date(email, start_date, end_date, retmax=100):
    """
    Search PubMed for articles matching the query within a specific date range.

    Parameters:
    - query: PubMed search query
    - email: Email address for NCBI API
    - start_date: Start date in format 'YYYY/MM/DD'
    - end_date: End date in format 'YYYY/MM/DD'
    - retmax: Maximum number of results to return

    Returns:
    - List of PubMed IDs
    """
    query = """("protein*"[Title] OR "peptide*"[Title] OR "antibod*"[Title] OR "nanobod*"[Title] OR "enzyme*"[Title] OR "TCR"[Title]) 
    AND ("learn*"[Title] OR "deep*"[Title] OR "neural network"[Title] OR "diffusion*"[Title] OR "transformer*"[Title] OR "flow matching"[Title] 
    OR "predict*"[Title] OR "generative"[Title] OR "embedding"[Title] OR "representation"[Title] OR "benchmark*"[Title] OR "supervised*"[Title] 
    OR "unsupervised*"[Title] OR "design*"[Title] OR "structure*"[Title] OR "model*"[Title] OR "reinforcement*"[Title])"""

    Entrez.email = email

    # Format the date range for PubMed query
    date_range = f"{start_date}:{end_date}[Date - Create]"
    full_query = f"({query}) AND {date_range}"

    # Search PubMed
    handle = Entrez.esearch(db="pubmed", term=full_query, retmax=retmax)
    record = Entrez.read(handle)
    handle.close()

    return record["IdList"]


# Function to fetch article details
def fetch_article_details(id_list):
    """
    Fetch details for a list of PubMed IDs.

    Parameters:
    - id_list: List of PubMed IDs

    Returns:
    - List of dictionaries with article details
    """
    articles = []

    # Process in batches to avoid overloading the server
    batch_size = 50
    for i in range(0, len(id_list), batch_size):
        batch_ids = id_list[i:i + batch_size]

        try:
            handle = Entrez.efetch(db="pubmed", id=batch_ids, rettype="medline",
                                   retmode="xml")
            records = Entrez.read(handle)

            for record in records['PubmedArticle'] + records[
                'PubmedBookArticle']:
                # Extract relevant information
                article = {}

                if 'ArticleTitle' in record['MedlineCitation']['Article']:
                    article['title'] = record['MedlineCitation']['Article'][
                        'ArticleTitle']
                if 'Abstract' in record['MedlineCitation']['Article']:
                    article['abstract'] = \
                        record['MedlineCitation']['Article']['Abstract'][
                            'AbstractText'][0]

                if len(record['MedlineCitation']['Article']['ArticleDate']) > 0:
                    date = [r for r in
                            record['MedlineCitation']['Article']['ArticleDate']
                            if r.attributes['DateType'] == "Electronic"][0]
                elif 'DateCompleted' in record['MedlineCitation']:
                    date = record['MedlineCitation']['DateCompleted']
                else:
                    date = None
                if date is not None:
                    article[
                        'date'] = f"{date['Year']}-{date['Month']}-{date['Day']}"

                if 'ELocationID' in record['MedlineCitation']['Article']:
                    dois = [str(r) for r in
                            record['MedlineCitation']['Article']['ELocationID']
                            if r.attributes['EIdType'] == 'doi']
                    if len(dois) > 0:
                        article['doi'] = dois[0]

                articles.append(article)

            handle.close()

            # Be nice to NCBI servers
            time.sleep(0.05)

        except Exception as e:
            print(f"Error fetching details for batch: {e}")

    return articles


# Main function to run the PubMed search for specified days
def run_pubmed_search(email, start_date, end_date):
    """
    Run PubMed searches for specific days and save results.

    Parameters:
    - query: PubMed search query
    - email: Email address for NCBI API
    """

    print('Retrieving PubMed')

    all_results = []

    days_list = list_dates(start_date, end_date)

    for day in days_list:
        print(f"Searching for articles on {day}...")

        # For a single day, use the same date for start and end
        pmids = search_pubmed_by_date(email, day, day)

        if pmids:
            print(f"Found {len(pmids)} articles for {day}")
            articles = fetch_article_details(pmids)

            # Add date to each article record
            for article in articles:
                article['search_date'] = day.replace('/', '-')
                all_results.append(article)

        else:
            print(f"No articles found for {day}")

    return pd.DataFrame(all_results)
