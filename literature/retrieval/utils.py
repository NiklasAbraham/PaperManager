from datetime import datetime, timedelta


def next_day(date):
    date_obj = datetime.strptime(date, "%Y/%m/%d")
    next_day = date_obj + timedelta(days=1)
    next_day = next_day.strftime("%Y/%m/%d")

    return next_day


def list_dates(start_date, end_date):
    """
    List all dates between the start and end date, inclusive.

    Parameters:
    - start_date: Start date in the format 'YYYY/MM/DD'
    - end_date: End date in the format 'YYYY/MM/DD'

    Returns:
    - List of dates as strings in 'YYYY/MM/DD' format
    """
    # Convert string dates to datetime objects
    start = datetime.strptime(start_date, '%Y/%m/%d')
    end = datetime.strptime(end_date, '%Y/%m/%d')

    # Create a list of dates
    date_list = []
    current_date = start

    while current_date <= end:
        date_list.append(current_date.strftime('%Y/%m/%d'))
        current_date += timedelta(days=1)  # Increment by one day

    return date_list
