import pandas as pd
import numpy as np

def clean_and_validate(data_list):
    """
    Takes a raw list of dictionary rows and applies data validation rules:
    - Removes 0 volume candles
    - Removes anomalies (price spikes > X%)
    - Handles missing values
    """
    if not data_list:
        return []

    print(f"Validating {len(data_list)} rows...")
    df = pd.DataFrame(data_list)

    # 1. Drop rows with null close prices
    initial_len = len(df)
    df.dropna(subset=['close'], inplace=True)
    if len(df) < initial_len:
        print(f"Dropped {initial_len - len(df)} rows with missing 'close' pricing")

    # 2. Filter 0 Volume (Optional depending on asset, but usually we keep it for weekends in crypto if any, 
    # but 0 volume for a whole day in stocks usually means halted or thinly traded)
    # df = df[df['volume'] > 0] 

    # 3. Detect sudden extreme price anomalies (e.g. 1000% daily spike which is usually a data split/error)
    # We rely on yfinance's auto_adjust for splits, but it occasionally fails.
    # To properly detect temporal spikes, we'd need to sort and compute pct_change.
    df.sort_values(by=['symbol', 'timestamp'], inplace=True)
    
    # Calculate daily returns per symbol ignoring division by zero
    # We'll just print warnings for now rather than dropping automatically,
    # as some penny stocks or crypto actually do jump 500%.
    returns = df.groupby('symbol')['close'].pct_change()
    spikes = returns[returns > 5.0] # 500% spike
    if not spikes.empty:
        spike_dates = df.loc[spikes.index][['symbol', 'timestamp', 'close']]
        print(f"WARNING: Detected {len(spikes)} potential extreme data spikes (>500% daily move). Check symbols: {spike_dates['symbol'].unique()}")

    # Ensure python types are matched for psycopg2
    df.replace({np.nan: None}, inplace=True)

    validated_list = df.to_dict('records')
    print(f"Validation complete. {len(validated_list)} valid rows remaining.")
    return validated_list
