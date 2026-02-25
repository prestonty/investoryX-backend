import numpy as np
import pandas as pd
from decimal import Decimal, ROUND_HALF_UP
from numbers import Real


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

def round_2_decimals(x):
    if x is None:
        return None
    return Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def format_number(value, prefix="", suffix="", decimal_places=2):
    if value is None or value == 'N/A':
        return "N/A"
    try:
        if isinstance(value, (Real, Decimal)):
            if decimal_places == 0:
                return f"{prefix}{value:,}{suffix}"
            else:
                return f"{prefix}{value:,.{decimal_places}f}{suffix}"
        return str(value)
    except Exception:
        return "N/A"
