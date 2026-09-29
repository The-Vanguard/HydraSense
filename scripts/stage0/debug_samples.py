"""Debug: what column values do the 1572 untagged LORO samples have?"""
import sys
sys.path.insert(0, '.')
import pandas as pd

df = pd.read_parquet('data/events/event_centered_samples.parquet')
print("Total rows:", len(df))
print("Columns:", list(df.columns))
print()

# Show value counts for columns that might identify region
for col in ['village', 'region', 'target_location', 'sample_type']:
    if col in df.columns:
        print("=== %s ===" % col)
        print(df[col].value_counts().head(20))
        print()
