import csv
import requests
import io
from sqlalchemy.orm import Session
from app.api.database.database import SessionLocal
from app.models.stocks import Stocks

def download_csv_from_alphavantage():
    """Download the CSV from Alpha Vantage API"""
    url = "https://www.alphavantage.co/query?function=LISTING_STATUS&apikey=demo"
    
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        print(f"Error downloading CSV: {e}")
        return None

def parse_csv_and_insert_stocks(csv_content):
    """Parse CSV content and insert valid stocks into database"""
    if not csv_content:
        print("No CSV content to parse")
        return
    
    db = SessionLocal()
    inserted_count = 0
    skipped_count = 0
    
    try:
        # Parse CSV content
        csv_reader = csv.DictReader(io.StringIO(csv_content))
        
        for row in csv_reader:
            # Check if all required fields are present and not empty
            symbol = row.get('symbol', '').strip()
            name = row.get('name', '').strip()
            exchange = row.get('exchange', '').strip()
            asset_type = row.get('assetType', '').strip()
            
            # Skip if any required field is missing or empty
            if not all([symbol, name, exchange, asset_type]):
                skipped_count += 1
                continue
            
            # Check if stock already exists (avoid duplicates)
            existing_stock = db.query(Stocks).filter_by(ticker=symbol).first()
            if existing_stock:
                skipped_count += 1
                continue
            
            # Create new stock entry
            new_stock = Stocks(
                company_name=name,
                ticker=symbol,
                exchange=exchange,
                asset_type=asset_type
            )
            
            db.add(new_stock)
            inserted_count += 1
            
            # Commit in batches to avoid memory issues
            if inserted_count % 1000 == 0:
                db.commit()
                print(f"Inserted {inserted_count} stocks so far...")
        
        # Final commit for remaining stocks
        db.commit()
        
        print(f"✅ Successfully inserted {inserted_count} stocks")
        print(f"⏭️  Skipped {skipped_count} stocks (missing data or duplicates)")
        
    except Exception as e:
        print(f"❌ Error processing CSV: {e}")
        db.rollback()
    finally:
        db.close()

def main():
    print("🔄 Downloading stock data from Alpha Vantage...")
    csv_content = download_csv_from_alphavantage()
    
    if csv_content:
        print("📊 Parsing CSV and inserting stocks into database...")
        parse_csv_and_insert_stocks(csv_content)
    else:
        print("❌ Failed to download CSV data")

if __name__ == "__main__":
    main()