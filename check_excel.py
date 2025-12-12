import pandas as pd

try:
    df = pd.read_excel('2024 Players.xlsx')
    print("Column names in Excel file:")
    print(df.columns.tolist())
    print(f"\nTotal rows: {len(df)}")
    print(f"\nFirst few rows:")
    print(df.head(10))
except Exception as e:
    print(f"Error: {e}")
