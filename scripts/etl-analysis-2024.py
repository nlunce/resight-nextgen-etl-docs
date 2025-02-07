import polars as pl
import numpy as np
from tabulate import tabulate

def calculate_favstats(df):
    """Calculate summary statistics for daily loads and rows"""
    
    # Calculate daily totals first
    daily_stats = (
        df.group_by(pl.col('timestamp').dt.date())
        .agg([
            pl.count().alias('loads'),
            pl.sum('rows').alias('rows')
        ])
    )
    
    # Function to calculate stats for a column
    def get_stats(column):
        data = daily_stats[column]
        q1, q3 = np.percentile(data, [25, 75])
        
        return {
            'min': data.min(),
            'q1': q1,
            'median': np.median(data),
            'q3': q3,
            'max': data.max(),
            'mean': data.mean(),
            'sd': data.std(),
            'n': len(data),
            'missing': data.null_count()
        }
    
    # Calculate stats for both metrics
    loads_stats = get_stats('loads')
    rows_stats = get_stats('rows')
    
    # Create table data
    metrics = ['Loads per Day', 'Rows per Day']
    table_data = []
    
    for metric, stats in zip(metrics, [loads_stats, rows_stats]):
        row = [
            metric,
            f"{stats['min']:,.0f}",
            f"{stats['q1']:,.0f}",
            f"{stats['median']:,.0f}",
            f"{stats['q3']:,.0f}",
            f"{stats['max']:,.0f}",
            f"{stats['mean']:,.1f}",
            f"{stats['sd']:,.1f}",
            f"{stats['n']:,}",
            f"{stats['missing']:,}"
        ]
        table_data.append(row)
    
    # Create and print table
    headers = ['Metric', 'Min', 'Q1', 'Median', 'Q3', 'Max', 'Mean', 'SD', 'N', 'Missing']
    print("\nETL Summary Statistics (2024)")
    print(tabulate(table_data, headers=headers, tablefmt='grid'))

if __name__ == "__main__":
    # Read the parquet file
    df = pl.read_parquet('etl_history_2024.parquet')
    
    # Calculate and display favstats
    calculate_favstats(df)