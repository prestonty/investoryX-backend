# InvestoryX Backend

This is the backend repository for InvestoryX - a beginner-friendly stock analytics platform built with FastAPI and PostgreSQL.

Here's the link to [InvestoryX Frontend](https://github.com/prestonty/investoryX)

## Video Demo

Watch video demo here: https://youtu.be/PdQUqJX_cCM

## Getting Started

Everything runs in Docker: Postgres, Redis, migrations, the API and Celery. The
only prerequisite is Docker (Docker Desktop on Windows/macOS), and every command
in this README goes through it.

### 1. Configure the Environment

```bash
cp .env.example .env
```

Fill in the secrets, including `ALPHAVANTAGE_API_KEY` (free at alphavantage.co),
which downloads the stock list. Keep `DATABASE_URL` pointing at the `db` host as in
the example; that's the Postgres container's name on Docker's network. The
`POSTGRES_*` values create the database the first time it starts and must match
the user, password and database name in `DATABASE_URL`.

### 2. Start the Stack

```bash
docker compose up --build
```

This starts:

| Service           | What it does                                                      | Port   |
| ----------------- | ----------------------------------------------------------------- | ------ |
| `db`              | Postgres 16                                                       | `5433` |
| `redis`           | Celery broker + stock data cache                                  | `6379` |
| `migrate`         | One-shot: runs `alembic upgrade head`, seeds stocks if table empty | –      |
| `backend`         | FastAPI (auto-reloads on code changes)                            | `8000` |
| `celery-worker`   | Celery worker                                                     | –      |
| `celery-beat`     | Celery Beat scheduler                                             | –      |
| `redis-commander` | Web UI for inspecting Redis                                       | `8081` |

The API is at `http://localhost:8000`, with interactive docs at `/docs`.

The frontend is not part of this stack. Run it from the frontend repo with `npm run dev`.

### What Happens Behind the Scenes

1. `db` and `redis` start, and Compose waits until both pass their health checks.
2. `migrate` runs once: `alembic upgrade head` applies any migrations in
   `alembic/versions/` that this database hasn't had yet, then the seed downloads
   the US stock list from Alpha Vantage if the `stocks` table is empty. It then
   exits with code 0, which is expected.
3. `backend`, `celery-worker` and `celery-beat` start only after `migrate`
   succeeds, so the schema is always current before any code touches it.
4. `celery-beat` queues scheduled jobs (weekdays, US Eastern time) and `celery-worker` runs them:
   - 7:00 AM: add newly listed tickers (e.g. IPOs) to `stocks`
   - Every 15 minutes, 9:05 AM–3:50 PM: fill manual orders queued while the market was closed
   - 4:30 PM: the trading pipeline (fetch prices, fill strategy orders at the
     open, rebuild portfolios, evaluate strategies)

Your code is mounted into the containers rather than copied, so edits apply
without a rebuild. Uvicorn reloads on its own; Celery needs a restart (below).

## Docker Commands

```bash
# First start, or after dependency changes
docker compose up --build

# Start in the background
docker compose up -d --build

# Stream backend logs
docker compose logs -f backend
```

After editing Celery tasks or schedules, restart the Celery containers:

```bash
docker compose restart celery-worker celery-beat
```

After pulling or writing a new migration while the stack is running, apply it with:

```bash
docker compose run --rm migrate
```

Plain `alembic upgrade head` from your own terminal won't work against this stack:
`DATABASE_URL` points at the `db` host, which only exists inside Docker's network.

### Connecting to Postgres

Docker's Postgres is published on `localhost:5433` (not 5432, so it doesn't clash
with a Postgres installed on your machine). Point a database client there with the
credentials from `.env`.

### Stock Table Empty?

The stock list fills itself (see above), but if the first seed failed, e.g. a bad
`ALPHAVANTAGE_API_KEY` (check `docker compose logs migrate`), startup carries on with
an empty table until the 7 AM sync. To fill it now:

```bash
docker compose exec backend python -m src.services.seed
```

## Technology Stack

- **Framework**: FastAPI 0.115.12
- **Database**: PostgreSQL with SQLAlchemy 2.0+
- **Authentication**: JWT tokens with bcrypt password hashing
- **Email**: Resend API integration for user verification
- **Stock Data**: Yahoo Finance (yfinance) with web scraping fallbacks
- **Data Processing**: Pandas, NumPy for financial calculations
- **Migrations**: Alembic for database schema management
- **Development**: Poetry for dependency management

## Project Structure

```
investoryx-backend/
├── alembic/                    # Database migrations
├── data/                       # Static data files (ETF lists, stock lists)
├── skills/                     # Claude skill documentation
├── src/
│   ├── main.py                 # FastAPI app entry point, router registration
│   ├── celery_app.py           # Celery worker and beat schedule config
│   ├── core/
│   │   ├── config.py           # Centralized environment variable config
│   │   ├── database.py         # SQLAlchemy engine, SessionLocal, Base, get_db
│   │   └── security.py         # JWT logic, password hashing, auth dependencies
│   ├── models/                 # SQLAlchemy ORM models (database tables)
│   ├── schemas/                # Pydantic request/response models
│   │   ├── simulator.py        # Simulator-related schemas
│   │   └── requests.py         # Shared request schemas
│   ├── routes/                 # FastAPI route handlers (HTTP layer only)
│   │   ├── auth.py
│   │   ├── stocks.py
│   │   ├── watchlist.py
│   │   ├── simulator.py
│   │   ├── users.py
│   │   ├── market_data.py
│   │   └── email.py
│   ├── services/               # Business logic (no HTTP awareness)
│   │   ├── stock_data.py       # yfinance + web scraping, Redis caching
│   │   ├── email.py            # Resend API email sending
│   │   ├── email_templates/    # HTML email templates
│   │   └── seed.py             # Stock table seeding script
│   ├── trading_engine/         # Celery-based paper trading pipeline
│   │   ├── services/           # Strategy, portfolio, execution logic
│   │   ├── tasks/              # Celery tasks (fetch prices, run strategies)
│   │   └── schedules/          # Celery Beat schedule definitions
│   ├── data_types/             # Enums (Period, Interval for historical data)
│   └── utils/                  # Shared helpers (rate limiter, retry, formatters)
└── tests/                      # Test suite
```

## API Endpoints

### Authentication (`/api/auth`)

- `POST /token` - User login
- `POST /register` - User registration
- `GET /me` - Get current user info
- `GET /verify-email` - Email verification
- `POST /refresh` - Refresh access token
- `POST /logout` - User logout

### Stocks (`/api/stocks`)

- `GET /` - List all stocks
- `GET /{stock_id}` - Get stock by ID
- `GET /ticker/{ticker}` - Get stock by ticker symbol
- `GET /search/{filter_string}` - Search stocks
- `POST /` - Create new stock entry

### Users (`/api/users`)

- User management endpoints

### Watchlist (`/api/watchlist`)

- Personal stock watchlist management

### Stock Data (Root Level)

- `GET /stocks/{ticker}` - Basic stock information
- `GET /stock-overview/{ticker}` - Detailed stock overview
- `GET /stock-news` - Latest stock market news
- `GET /stock-history/{ticker}` - Historical stock data
- `GET /get-default-indexes` - Default market index ETFs

## Security Features

- **Password Hashing**: bcrypt with automatic salt generation
- **JWT Tokens**: Access and refresh token system
- **Email Verification**: Required for account activation
- **CORS Protection**: Configurable cross-origin resource sharing
- **Rate Limiting**: Protection against API abuse

## Data Sources

- **Primary**: Yahoo Finance API (yfinance)
- **Fallback**: Web scraping from stockanalysis.com
- **Local**: Curated ETF and market index data

## Development

### Code Quality

- **Black**: Code formatting (88 character line length)
- **Flake8**: Linting and style checking
- **Type Hints**: Full Python type annotation support

### Database Migrations

Run Alembic inside a container. The code is mounted, so new migration files land
in your repo:

```bash
# Apply migrations
docker compose run --rm migrate

# Create new migration
docker compose run --rm backend alembic revision --autogenerate -m "Description of changes"

# Rollback migration
docker compose run --rm backend alembic downgrade -1
```

### Changing Dependencies

The image installs from `poetry.lock`. Update it with Poetry in a throwaway
container (the version that wrote the lock file), then rebuild:

```bash
docker run --rm -v "${PWD}:/app" -w /app python:3.12-slim sh -c "pip install -q poetry==2.2.1 && poetry add --lock <package>"
docker compose up --build
```

### Testing

```bash
docker compose run --rm --no-deps -e DATABASE_URL=sqlite:// -e RATE_LIMIT_ENABLED=false backend sh -c "pip install -q pytest && python -m pytest"
```

This runs the tests in a throwaway copy of the backend container. Tests use an
in-memory SQLite database; overriding `DATABASE_URL` guarantees they never touch your
dev Postgres, and `--no-deps` leaves the running stack alone. pytest is a dev
dependency, so it's installed into the throwaway container each run.

## Environment Variables

| Variable                      | Description                       | Default          |
| ----------------------------- | --------------------------------- | ---------------- |
| `DATABASE_URL`                | PostgreSQL connection string      | Required         |
| `SECRET_KEY`                  | JWT signing key                   | Required         |
| `REFRESH_SECRET_KEY`          | Refresh token signing key         | SECRET_KEY       |
| `ALGORITHM`                   | JWT algorithm                     | HS256            |
| `RESEND_API_KEY`              | Email service API key             | Required         |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Access token lifetime             | 30               |
| `REFRESH_TOKEN_EXPIRE_DAYS`   | Refresh token lifetime            | 7                |
| `EMAIL_TOKEN_EXPIRE_MINUTES`  | Email verification token lifetime | 1440             |
| `DISABLE_EMAIL_VERIFICATION`  | Skip email verification on signup | false            |
| `CELERY_BROKER_URL`           | Celery broker URL (Redis)         | Required         |
| `CELERY_RESULT_BACKEND`       | Celery result backend (Redis)     | Required         |
| `CELERY_TIMEZONE`             | Celery timezone                   | America/New_York |

## Frontend Integration

This backend application is designed to work with the [InvestoryX Frontend](https://github.com/prestonty/investoryX) application, which provides:

- Modern React-based user interface
- Real-time data visualization with Plotly.js
- Responsive design for all device types
- JWT-based authentication integration
- Portfolio management and watchlist features

The backend provides RESTful API endpoints that the frontend consumes through a centralized API layer, ensuring clean separation of concerns and maintainable code structure.

## Support

For issues and questions:

- Check the API documentation at `/docs` when the server is running
- Review the FastAPI interactive docs at `/redoc`
- Check the logs for detailed error information

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

This project is part of the InvestoryX financial analytics platform.

---

**Note**: This backend is designed to work with the InvestoryX frontend application. Ensure proper CORS configuration for your frontend domain.
