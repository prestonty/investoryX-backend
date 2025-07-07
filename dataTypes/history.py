from enum import StrEnum

class Interval(StrEnum):
    MINUTE_1 = "1m"
    MINUTE_2 = "2m"
    MINUTE_5 = "5m"
    MINUTE_15 = "15m"  
    MINUTE_30 = "30m"
    MINUTE_60 = "60m"
    MINUTE_90 = "90m"
    HOUR_1 = "1h"
    DAY_1 = "1d"
    DAY_5 = "5d"
    WEEK_1 = "1wk"
    MONTH_1 = "1mo"
    MONTH_3 = "3mo"

class Period(StrEnum):
    DAY_1 = "1d"
    DAY_5 = "5d"
    MONTH_1 = "1mo"
    MONTH_3 = "3mo"
    MONTH_6 = "3mo"
    YEAR_1 = "1y"
    YEAR_2 = "2y"
    YEAR_5 = "5y"
    YEAR_10 = "10y"
    YEAR_TO_DATE = "ytd"
    MAX = "max"

      
