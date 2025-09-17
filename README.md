# InvestoryX Backend

This is the backend repository for InvestoryX - a beginner-friendly stock analytics platform built with FastAPI and PostgreSQL.

Here's the link to [InvestoryX Frontend](https://github.com/prestonty/investoryX)

## Quick Start

```bash
uvicorn src.main:app --reload
```

## Technology Stack

-   **Framework**: FastAPI 0.115.12
-   **Database**: PostgreSQL with SQLAlchemy 2.0+
-   **Authentication**: JWT tokens with bcrypt password hashing
-   **Email**: Resend API integration for user verification
-   **Stock Data**: Yahoo Finance (yfinance) with web scraping fallbacks
-   **Data Processing**: Pandas, NumPy for financial calculations
-   **Migrations**: Alembic for database schema management
-   **Development**: Poetry for dependency management

## Prerequisites

-   Python 3.12+
-   PostgreSQL database
-   Poetry (for dependency management)
-   Environment variables configured

## Installation & Setup

### 1. Clone and Navigate

```bash
cd backend2
```

### 2. Install Dependencies

```bash
# Using Poetry (recommended)
poetry install

# Or using pip
pip install -r requirements.txt
```

### 3. Environment Configuration

Create a `.env` file in the root directory with:

```env
# Database
DATABASE_URL=postgresql://username:password@localhost/database_name

# Security
SECRET_KEY=your_secret_key_here
REFRESH_SECRET_KEY=your_refresh_secret_key_here
ALGORITHM=HS256

# Email Service
RESEND_API_KEY=your_resend_api_key

# Frontend URLs (for CORS)
FRONTEND_BASE_URL=http://localhost:3000

# Token Expiration
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7
EMAIL_TOKEN_EXPIRE_MINUTES=1440
```

### 4. Database Setup

```bash
# Run database migrations
alembic upgrade head
```

### 5. Start the Server

```bash
# Development mode with auto-reload
uvicorn src.main:app --reload

# Production mode
uvicorn src.main:app --host 0.0.0.0 --port 8000
```

The server will start at `http://127.0.0.1:8000`

## API Endpoints

### Authentication (`/api/auth`)

-   `POST /token` - User login
-   `POST /register` - User registration
-   `GET /me` - Get current user info
-   `GET /verify-email` - Email verification
-   `POST /refresh` - Refresh access token
-   `POST /logout` - User logout

### Stocks (`/api/stocks`)

-   `GET /` - List all stocks
-   `GET /{stock_id}` - Get stock by ID
-   `GET /ticker/{ticker}` - Get stock by ticker symbol
-   `GET /search/{filter_string}` - Search stocks
-   `POST /` - Create new stock entry

### Users (`/api/users`)

-   User management endpoints

### Watchlist (`/api/watchlist`)

-   Personal stock watchlist management

### Stock Data (Root Level)

-   `GET /stocks/{ticker}` - Basic stock information
-   `GET /stock-overview/{ticker}` - Detailed stock overview
-   `GET /stock-news` - Latest stock market news
-   `GET /stock-history/{ticker}` - Historical stock data
-   `GET /get-default-indexes` - Default market index ETFs

## Security Features

-   **Password Hashing**: bcrypt with automatic salt generation
-   **JWT Tokens**: Access and refresh token system
-   **Email Verification**: Required for account activation
-   **CORS Protection**: Configurable cross-origin resource sharing
-   **Rate Limiting**: Protection against API abuse

## Data Sources

-   **Primary**: Yahoo Finance API (yfinance)
-   **Fallback**: Web scraping from stockanalysis.com
-   **Local**: Curated ETF and market index data

## Development

### Code Quality

-   **Black**: Code formatting (88 character line length)
-   **Flake8**: Linting and style checking
-   **Type Hints**: Full Python type annotation support

### Database Migrations

```bash
# Create new migration
alembic revision --autogenerate -m "Description of changes"

# Apply migrations
alembic upgrade head

# Rollback migration
alembic downgrade -1
```

### Testing

```bash
# Run tests (when implemented)
pytest

# Run with coverage
pytest --cov=src
```

## Environment Variables

| Variable                      | Description                       | Default    |
| ----------------------------- | --------------------------------- | ---------- |
| `DATABASE_URL`                | PostgreSQL connection string      | Required   |
| `SECRET_KEY`                  | JWT signing key                   | Required   |
| `REFRESH_SECRET_KEY`          | Refresh token signing key         | SECRET_KEY |
| `ALGORITHM`                   | JWT algorithm                     | HS256      |
| `RESEND_API_KEY`              | Email service API key             | Required   |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Access token lifetime             | 30         |
| `REFRESH_TOKEN_EXPIRE_DAYS`   | Refresh token lifetime            | 7          |
| `EMAIL_TOKEN_EXPIRE_MINUTES`  | Email verification token lifetime | 1440       |

## Frontend Integration

This backend application is designed to work with the [InvestoryX Frontend](https://github.com/prestonty/investoryX) application, which provides:

-   Modern React-based user interface
-   Real-time data visualization with Plotly.js
-   Responsive design for all device types
-   JWT-based authentication integration
-   Portfolio management and watchlist features

The backend provides RESTful API endpoints that the frontend consumes through a centralized API layer, ensuring clean separation of concerns and maintainable code structure.

## Support

For issues and questions:

-   Check the API documentation at `/docs` when the server is running
-   Review the FastAPI interactive docs at `/redoc`
-   Check the logs for detailed error information

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

This project is part of the InvestoryX financial analytics platform.

---

**Note**: This backend is designed to work with the InvestoryX frontend application. Ensure proper CORS configuration for your frontend domain.
