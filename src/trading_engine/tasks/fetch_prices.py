from celery import Celery

@app.task
def fetch_price(ticker):
    