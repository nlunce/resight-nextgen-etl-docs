from slack_sdk import WebClient
from datetime import datetime, timedelta
import re
import polars as pl
from concurrent.futures import ThreadPoolExecutor
import os
from functools import partial
import time
from tqdm import tqdm

def fetch_slack_chunk(client, channel, oldest, latest):
    """
    Fetches a chunk of Slack messages between timestamps, using pagination
    """
    try:
        all_rows = []
        cursor = None
        has_more = True
        
        while has_more:
            try:
                # Get batch of messages
                result = client.conversations_history(
                    channel=channel,
                    oldest=str(oldest),  # Convert to string for Slack API
                    latest=str(latest),
                    limit=1000,
                    cursor=cursor
                )
                
                # Process messages
                for msg in result.get("messages", []):
                    if "attachments" in msg:
                        for attachment in msg["attachments"]:
                            if attachment.get("pretext") == "ETL Notification":
                                ts = datetime.fromtimestamp(float(msg["ts"]))
                                text = attachment.get("text", "")

                                filename_match = re.search(r'loaded: (.*?) \(', text)
                                filename = filename_match.group(1) if filename_match else "Unknown"

                                dest_match = re.search(r'into (.*?):', text)
                                destination = dest_match.group(1) if dest_match else "Unknown"

                                table_data = re.findall(r'([\w\.]+):\s*(\d+)\s*rows', text)
                                
                                for table, row_count in table_data:
                                    all_rows.append({
                                        'timestamp': ts,
                                        'filename': filename,
                                        'destination': destination,
                                        'table': table,
                                        'rows': int(row_count)
                                    })
                
                # Check if there are more messages
                cursor = result.get('response_metadata', {}).get('next_cursor')
                has_more = bool(cursor and result.get('has_more', False))
                
                if has_more:
                    time.sleep(2)  # Increased delay to avoid rate limits
                
            except Exception as e:
                print(f"Error in batch: {e}")
                time.sleep(2)  # Wait longer on error
                has_more = False
        
        print(f"Fetched {len(all_rows)} records for period {datetime.fromtimestamp(oldest)} to {datetime.fromtimestamp(latest)}")
        return all_rows

    except Exception as e:
        print(f"Error fetching chunk: {e}")
        return []

def fetch_etl_history(cache_file='etl_history_2024.parquet', start_date=None, end_date=None):
    """
    Fetches ETL data from Slack with parallelization and caching
    """
    # Check for cached data
    if os.path.exists(cache_file):
        print("Loading cached ETL history...")
        return pl.read_parquet(cache_file)

    client = WebClient(token="YOUR_SLACK_API_TOKEN")
    channel = "YOUR_SLACK_CHANNEL_ID"
    
    # Set time range
    if end_date is None:
        end_time = datetime.now()
    else:
        end_time = datetime.strptime(end_date, '%Y-%m-%d')
        
    if start_date is None:
        # Default to January 1, 2024 if no start date provided
        start_time = datetime(2024, 1, 1)
    else:
        start_time = datetime.strptime(start_date, '%Y-%m-%d')
    
    # Create 7-day chunks (increased from 1 day to get more data per chunk)
    time_chunks = []
    chunk_start = start_time
    while chunk_start < end_time:
        chunk_end = min(chunk_start + timedelta(days=7), end_time)
        time_chunks.append((chunk_start.timestamp(), chunk_end.timestamp()))
        chunk_start = chunk_end

    print(f"Fetching ETL history from {start_time} to {end_time}...")
    
    # Fetch chunks in parallel with progress bar
    with ThreadPoolExecutor(max_workers=3) as executor:  # Reduced workers further
        partial_fetch = partial(fetch_slack_chunk, client, channel)
        chunk_results = list(tqdm(
            executor.map(lambda x: partial_fetch(oldest=x[0], latest=x[1]), time_chunks),
            total=len(time_chunks),
            desc="Fetching chunks"
        ))

    # Combine all results
    all_rows = [row for chunk in chunk_results for row in chunk]
    
    if not all_rows:
        print("No ETL data found!")
        return None

    # Convert to Polars DataFrame and sort
    df = pl.DataFrame(all_rows).sort('timestamp')
    
    # Cache the results
    print(f"Caching ETL history to {cache_file}...")
    df.write_parquet(cache_file)
    
    print(f"Total records fetched: {len(all_rows)}")
    return df

def analyze_data(df):
    """
    Print basic analysis of the ETL data
    """
    if df is None:
        return
        
    print("\nData Summary:")
    print(f"Date Range: {df['timestamp'].min()} to {df['timestamp'].max()}")
    print(f"Total Records: {df.height}")
    
    # Daily statistics
    daily_stats = (
        df.group_by(pl.col('timestamp').dt.date())
        .agg([
            pl.len().alias('number_of_loads'),
            pl.sum('rows').alias('total_rows')
        ])
        .sort('timestamp')
    )
    
    print("\nDaily Statistics:")
    print(f"Average daily loads: {daily_stats['number_of_loads'].mean():.1f}")
    print(f"Average rows per day: {daily_stats['total_rows'].mean():,.0f}")
    
    # Print earliest and latest dates for verification
    print(f"\nFirst ETL notification: {daily_stats['timestamp'].min()}")
    print(f"Last ETL notification: {daily_stats['timestamp'].max()}")

if __name__ == "__main__":
    # Delete cache file if exists to force fresh fetch
    cache_file = 'etl_history_2024.parquet'
    if os.path.exists(cache_file):
        os.remove(cache_file)
        print("Deleted existing cache file.")
    
    # Fetch 2024 data only
    start_date = '2024-01-01'
    end_date = '2024-12-31'
    df = fetch_etl_history(cache_file, start_date=start_date, end_date=end_date)
    
