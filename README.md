# FinPilot DS — Financial Chatbot & Data Structures Lab

A Flask web app that combines a **financial-style dashboard**, **interactive demos** of classic data structures (backed by a **C++ engine**), **portfolio-style tools**, and a **route-aware chatbot**. Built for coursework and demos with a dark, dashboard-first UI.

**Repository:** [github.com/AtharvGore14/DSChatbot](https://github.com/AtharvGore14/DSChatbot)

---

## Features

| Area | What you get |
|------|----------------|
| **Auth** | Register, login, logout; sessions protect dashboard, analysis, compare, optimizer, and admin |
| **Dashboard** | Overview and navigation hub after sign-in |
| **Search** | Market/search flows with supporting UI |
| **Analysis** | Data analysis views with **PDF export** (`/analysis/export`) |
| **Compare** | Side-by-side comparison tooling |
| **Optimizer** | Goal/horizon-style optimizer with **live preview** API |
| **Chatbot** | Page-aware assistant (`/chatbot`, JSON API `/api/chatbot`) |
| **Demo** | Hands-on UI wired to the DS engine (sort, graph, AVL, trie) |
| **Admin** | Restricted area for administration tasks |
| **C++ engine** | Trie, sorting (merge / quick / heap), graph (BFS / DFS / Dijkstra), AVL tree — invoked via REST |

---

## Tech stack

- **Backend:** Python 3, **Flask**, SQLite (`auth_db.py`, local `finpilot_users.db` created at runtime)
- **Engine:** C++17 executable `cpp_backend/ds_engine.exe` (Windows build included; recompile from source on other OSes)
- **Data / exports:** NumPy, Pandas, **fpdf2**, **yfinance** (where used for market data)
- **Frontend:** Jinja2 templates, static CSS/JS

---

## Prerequisites

- Python **3.10+** recommended  
- **g++** with C++17 (only if you rebuild `ds_engine`)  
- Windows paths assume `.exe` for the engine; on Linux/macOS compile to a binary and adjust `CPP_ENGINE` in `app.py` if needed

---

## Quick start

### 1. Clone

```bash
git clone https://github.com/AtharvGore14/DSChatbot.git
cd DSChatbot
```

### 2. Virtual environment & dependencies

**Windows (PowerShell)**

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

If script activation is blocked, call the venv Python directly (as above) instead of `Activate.ps1`.

**macOS / Linux**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. (Optional) Rebuild the C++ engine

Prebuilt `cpp_backend/ds_engine.exe` is in the repo for Windows. To rebuild:

```bash
g++ -std=c++17 -O2 -o cpp_backend/ds_engine.exe cpp_backend/data_structures.cpp
```

On Unix-like systems, name the output `ds_engine` (no `.exe`) and point `CPP_ENGINE` in `app.py` to that file.

### 4. Configuration

| Variable | Purpose |
|----------|---------|
| `FLASK_SECRET_KEY` | Session signing (defaults to a dev placeholder — **set in production**) |

### 5. Run the app

```bash
python app.py
```

Or:

```bash
set FLASK_APP=app
flask run --debug
```

Open **http://127.0.0.1:5000** in your browser.

---

## HTTP API (high level)

Base URL: `http://127.0.0.1:5000`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/ds/health` | GET | Engine health check |
| `/api/ds/trie` | GET | Trie demo — query `prefix` |
| `/api/ds/sort` | GET | Sort — `algo` ∈ `merge`, `quick`, `heap`; `data` = comma-separated ints |
| `/api/ds/graph` | GET | Graph — `algo` ∈ `bfs`, `dfs`, `dijkstra`; `start` = node label |
| `/api/ds/avl` | GET | AVL build steps — `data` = comma-separated ints |
| `/api/optimizer/preview` | POST | Optimizer preview (JSON body per app) |
| `/api/chatbot` | POST | Chatbot API |
| `/api/market/gainers` | GET | Sample gainers list |
| `/api/market/sectors` | GET | Sector strength payload |
| `/api/market/overview` | GET | Market overview / breadth-style bundle |

Exact query parameters and payloads match validation in `app.py` (length limits, allowed enums, etc.).

---

## Project layout

```
├── app.py                 # Flask app, routes, C++ bridge
├── auth_db.py             # SQLite auth helpers
├── requirements.txt
├── cpp_backend/
│   ├── data_structures.cpp
│   └── ds_engine.exe      # Windows binary (rebuild on other OS)
├── database/
├── static/                # css, js, images
└── templates/             # Jinja HTML
```

---

## Security notes for production

- Change **`FLASK_SECRET_KEY`** and never commit real secrets.  
- The default SQLite DB file is **gitignored** — user accounts stay local unless you deploy with a proper DB.  
- Run behind a production WSGI server (e.g. Gunicorn + reverse proxy), not `flask run` / `app.run(debug=True)`.

---

## License

Add a `LICENSE` file if you want to specify terms (e.g. MIT). Until then, all rights reserved unless you state otherwise.

---

## Author

**Atharv Gore** — [DSChatbot on GitHub](https://github.com/AtharvGore14/DSChatbot)
