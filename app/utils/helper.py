import numpy as np
import pandas as pd

def dataframeToJson(df: pd.DataFrame) -> list[dict]:
    df = df.reset_index()

    json_safe = []
    for row in df.to_dict(orient="records"):
        safe_row = {}
        for key, value in row.items():
            if isinstance(value, (np.integer, np.floating)):
                safe_row[key] = value.item()
            elif isinstance(value, (pd.Timestamp, np.datetime64)):
                safe_row[key] = pd.to_datetime(value).isoformat()
            elif isinstance(value, np.ndarray):
                safe_row[key] = value.tolist()
            else:
                safe_row[key] = value
        json_safe.append(safe_row)

    return json_safe