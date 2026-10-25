# Car Dealership Inventory System

A small full-stack inventory application. The FastAPI backend stores vehicles and user accounts in SQLite, protects write operations with JWT bearer authentication, and exposes inventory search, purchase, and admin management routes. The React frontend provides account forms and an inventory interface backed by those APIs.

## Implemented features

- User registration and login with bcrypt password hashes and 30-minute JWT access tokens.
- Regular-user and administrator roles. Public registration always creates a regular user.
- Optional administrator bootstrap at backend startup through `ADMIN_USERNAME` and `ADMIN_PASSWORD`.
- Vehicle creation, retrieval, updating, filtering, purchasing, restocking, and deletion.
- Atomic inventory decrement on purchase; invalid quantities and insufficient stock are rejected.
- Responsive React interface for registration/login, filtered browsing, purchasing, and administrator restock/delete controls.
- Local-development CORS for the Vite origins `http://localhost:5173` and `http://127.0.0.1:5173`.

## Technology

- Python, FastAPI, Pydantic, SQLAlchemy, SQLite
- pytest and FastAPI `TestClient`
- React 18 and Vite 6

## Project structure

```text
backend/
  main.py                 FastAPI app, database lifecycle, routes, and dependencies
  models.py               SQLAlchemy User and Vehicle models
  security.py             Password hashing and JWT creation helpers
  seed_data.py            Idempotent sample vehicle loader
  requirements.txt        Pinned Python dependencies
  tests/
    test_auth.py
    test_health.py
    test_vehicles.py
frontend/
  index.html
  package.json
  package-lock.json
  src/
    App.jsx               UI and API integration
    main.jsx              React entry point
    styles.css
pytest.ini                Root-level pytest import configuration
```

## Run the backend (Windows PowerShell)

Run these commands from the project root. The existing local environment is `backend\.venv`; create it only if it does not exist.

```powershell
if (-not (Test-Path backend\.venv\Scripts\python.exe)) { py -m venv backend\.venv }
.\backend\.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements.txt
```

Configure the database and JWT secret in the current PowerShell session. The secret should be long, random, and kept stable between restarts if existing tokens must remain valid:

```powershell
$env:DATABASE_URL = "sqlite:///./vehicles.db"
$jwtSecret = Read-Host "Enter the stable JWT signing secret" -AsSecureString
$env:JWT_SECRET_KEY = (New-Object System.Net.NetworkCredential("", $jwtSecret)).Password
```

To bootstrap an administrator, configure both variables before the first startup using that username:

```powershell
$env:ADMIN_USERNAME = Read-Host "Administrator username"
$adminPassword = Read-Host "Administrator password" -AsSecureString
$env:ADMIN_PASSWORD = (New-Object System.Net.NetworkCredential("", $adminPassword)).Password
```

If either administrator variable is unset or empty, startup logs a warning and skips bootstrap. If the username already exists, startup does not change that account. Use an administrator password of at least 8 characters and no more than 72 UTF-8 bytes: public registration/login enforces the 8-character minimum, while startup bootstrap enforces the bcrypt byte limit. Passwords should not be placed in source files or committed.

Start the API from the project root:

```powershell
python -m uvicorn backend.main:app --reload
```

The API and interactive OpenAPI documentation are available at:

- API: <http://127.0.0.1:8000>
- Swagger UI: <http://127.0.0.1:8000/docs>

`DATABASE_URL` defaults to `sqlite:///./vehicles.db`, relative to the process working directory. Set it explicitly if you want the database file in a different location. `JWT_SECRET_KEY` is generated randomly if unset; tokens will then stop validating after an application restart.

### Seed sample vehicles

From the project root, run the seed script with the backend virtual environment. It uses the same `DATABASE_URL` as the application (or the same default, `sqlite:///./vehicles.db`) and adds up to 19 sample vehicles with Indian rupee values. Existing vehicles matching the same make, model, and year are skipped; other inventory and user accounts are left untouched. The script reports inserted and skipped counts and can be run repeatedly:

```powershell
.\backend\.venv\Scripts\python.exe -m backend.seed_data
```

Set `DATABASE_URL` in the current shell first if the application uses a non-default database path.

### Capture local UI screenshots

Install frontend dependencies, then run from the frontend directory:

```powershell
npm run capture:screenshots
```

The first run generates dedicated screenshot-account credentials in the gitignored `screenshots\.env.screenshots.local` file (passwords and JWT tokens are never printed). Optional `SCREENSHOT_REGULAR_USERNAME`, `SCREENSHOT_REGULAR_PASSWORD`, `SCREENSHOT_ADMIN_USERNAME`, `SCREENSHOT_ADMIN_PASSWORD`, and `SCREENSHOT_JWT_SECRET` environment variables override those local values. The workflow starts the backend on `127.0.0.1:8010` using the isolated `screenshots\screenshot-demo.sqlite3` database, creates the admin through the existing environment bootstrap and the regular user through `/auth/register`, verifies both roles using real login tokens, then launches Vite and Microsoft Edge through Playwright on `127.0.0.1:5173`, an origin already allowed by the backend's local-development CORS configuration. It does not touch the normal application database. It saves public, regular-user, and admin views as PNGs in `screenshots\`.

## Run the frontend

In a second PowerShell window:

```powershell
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>. The frontend defaults to the API at `http://127.0.0.1:8000`. To use a different API URL, set `VITE_API_URL` before starting Vite:

```powershell
$env:VITE_API_URL = "http://127.0.0.1:8000"
npm run dev
```

## API reference

All vehicle response objects contain `id`, `make`, `model`, `year`, `price`, and `quantity`. Registration and login accept JSON with `username` and `password`. Protected routes require `Authorization: Bearer <access_token>`.

| Method | Path | Access | Behavior |
| --- | --- | --- | --- |
| `GET` | `/health` | Public | Health response: `{"status":"ok"}` |
| `POST` | `/auth/register` | Public | Create a regular user; returns `201` |
| `POST` | `/auth/login` | Public | Verify credentials and return an access token |
| `GET` | `/auth/me` | Bearer token | Return the authenticated user's ID, username, and role |
| `GET` | `/vehicles` | Public | List vehicles; optional `make`, `model`, `min_price`, `max_price` filters |
| `GET` | `/vehicles/{vehicle_id}` | Public | Retrieve one vehicle; returns `404` if absent |
| `POST` | `/vehicles` | Bearer token | Create a vehicle; returns `201` |
| `PUT` | `/vehicles/{vehicle_id}` | Bearer token | Replace vehicle fields |
| `POST` | `/vehicles/{vehicle_id}/purchase` | Bearer token | Purchase a positive quantity and decrement stock |
| `POST` | `/vehicles/{vehicle_id}/restock` | Administrator | Add a positive quantity to stock |
| `DELETE` | `/vehicles/{vehicle_id}` | Administrator | Delete a vehicle; returns `204` |

The make and model filters use case-insensitive substring matching. A purchase returns `404` for a missing vehicle and `409` when inventory is insufficient. Invalid/non-positive purchase and restock quantities are rejected by request validation.

### Example requests (PowerShell)

Register a regular account and log in:

```powershell
$baseUrl = "http://127.0.0.1:8000"
$credentials = @{ username = "buyer"; password = "replace-with-a-password" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "$baseUrl/auth/register" -ContentType "application/json" -Body $credentials
$login = Invoke-RestMethod -Method Post -Uri "$baseUrl/auth/login" -ContentType "application/json" -Body $credentials
$headers = @{ Authorization = "Bearer $($login.access_token)" }
```

Browse filtered inventory and purchase a vehicle:

```powershell
Invoke-RestMethod -Uri "$baseUrl/vehicles?make=Toyota&min_price=10000&max_price=50000"
$vehicleId = 1
$purchase = @{ quantity = 1 } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "$baseUrl/vehicles/$vehicleId/purchase" -Headers $headers -ContentType "application/json" -Body $purchase
```

Restock and delete requests use the same bearer header, but succeed only for an administrator:

```powershell
$restock = @{ quantity = 5 } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "$baseUrl/vehicles/$vehicleId/restock" -Headers $headers -ContentType "application/json" -Body $restock
Invoke-RestMethod -Method Delete -Uri "$baseUrl/vehicles/$vehicleId" -Headers $headers
```

## Tests and production build

Activate the backend virtual environment from the project root, then run:

```powershell
python -m pytest -v
```

The tests use temporary SQLite databases. Build the frontend from its directory:

```powershell
cd frontend
npm run build
```

## Known limitations

- The frontend currently supports browsing, account creation/login, purchasing, restocking, and deletion. Vehicle creation and updating are available through the API, not through frontend forms.
- Purchases update inventory only; there is no order history, payment processing, reservation, or customer receipt.
- JWTs are stored in browser `localStorage`. Keep the API and browser deployment appropriately protected against cross-site scripting.
- The backend uses `Base.metadata.create_all` and a small startup migration for the user role column; there is no general migration tool.
- The frontend has no automated test or lint script configured. `npm run build` is its available project check.
- The frontend displays vehicle prices in Indian rupees (INR); the backend does not store a currency.
## My AI Usage

### AI Tools Used

I used GitHub Copilot and ChatGPT as AI-assisted development tools during this project. They helped me understand requirements, investigate errors, plan tests, review implementation choices, and improve documentation.

### How I Used AI

AI assistance was used during the following stages:

1. **Project planning:** I reviewed the assignment requirements and broke the system into authentication, vehicle inventory, purchasing, authorization, database persistence, and frontend components.
2. **Test-driven development:** I used AI assistance to discuss test cases and expected behavior. I ran tests during development and used their results to guide debugging and implementation.
3. **Backend development:** I worked on the FastAPI application, SQLAlchemy models, SQLite persistence, JWT authentication, password hashing, vehicle search, purchasing, restocking, and access control.
4. **Testing:** I used AI assistance to investigate test failures and consider edge cases, including invalid input, insufficient stock, unauthorized requests, and database transaction behavior.
5. **Frontend development:** I used AI assistance while developing and debugging the React interface and its integration with the backend API.
6. **Documentation and screenshots:** I used AI assistance to organize setup instructions, document API endpoints, and prepare screenshots of the application's public, regular-user, and administrator views.

### Human Review and Verification

AI-generated suggestions were reviewed and adapted to the project rather than treated as automatically correct. I ran the backend test suite and frontend production build to verify the application. The reported backend test result was **29 passed**, and the frontend build completed successfully during development.

The final implementation, test results, and repository history should be used to evaluate the actual state of the project.

### Test-Driven Development and Git History

The repository contains incremental commits covering the health endpoint, persistent vehicle storage, JWT authentication, vehicle authorization and purchasing, and database transaction tests. These commits provide a record of the development process.

The test suite can be run from the project root using:

```powershell
python -m pytest -v
```

The frontend production build can be checked using:

```powershell
cd frontend
npm run build
```

### AI Conversation Records

The assignment requires the actual AI prompts and conversation logs to be included in `PROMPTS.md` or made available through public conversation links. The records must reflect the conversations that actually occurred. Any reconstructed notes or summaries should be identified as such rather than presented as verbatim conversation logs.

### Limitations

The application is a local-development project. It does not implement payment processing or order history, and vehicle creation and updating are available through the API rather than frontend forms. Additional production hardening and automated frontend tests would be appropriate future improvements.