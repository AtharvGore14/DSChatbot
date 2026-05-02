# FinPilot DS — Financial Chatbot & Data Structures Lab

A Flask web app that combines a **financial-style dashboard**, **interactive demos** of classic data structures (backed by a **C++ engine**), **portfolio-style tools**, and a **route-aware chatbot**. Built for coursework and demos with a dark, dashboard-first UI.

**Repository:** [github.com/AtharvGore14/DSChatbot](https://github.com/AtharvGore14/DSChatbot)

---

## Project overview

FinPilot DS is split into three layers:

1. **Web layer (Python / Flask)** — Serves HTML pages, handles **login sessions**, talks to **SQLite** for user accounts, and calls the engine when a page or API needs algorithmic output.
2. **Algorithms layer (C++17)** — A small program (`cpp_backend/ds_engine.exe`) that implements classic **data structures and algorithms** and prints **JSON** to standard output. Python runs it as a **subprocess**, reads that JSON, and shows it in charts, tables, or API responses.
3. **Application features** — Finance-themed screens (dashboard, analysis, compare, optimizer, chatbot) use **sample/static market data** for repeatable demos; they are **not** a live brokerage.

**Why C++ for data structures?** The course project keeps heavy algorithm work in a compiled binary so you can demonstrate **efficient** implementations (trees, heaps, graphs) separately from the Flask UI. The website stays simple; the engine stays fast and deterministic.

---

## Data structures & algorithms

### What is a “data structure” here?

A **data structure** is a way of organizing values in memory so common operations are efficient — for example, a **trie** makes prefix search fast; an **AVL tree** keeps insert/search balanced; a **graph** models relationships between sector nodes; **sorting algorithms** reorder arrays for analysis and display. This repo **implements** those structures in C++ and **connects** them to the browser through Flask.

### Implemented in the C++ engine (`data_structures.cpp`)

The executable supports multiple commands. Below is what each part is for.

| Topic | Implementation | What it does |
|--------|----------------|--------------|
| **Trie (prefix tree)** | `Trie` + `TrieNode` (children via character map) | Inserts ticker symbols, returns **prefix suggestions** (used by `/search` and `/api/ds/trie`). |
| **Self-balancing BST** | **AVL tree** (`AVLTree`) | Inserts integers with rotations; outputs **in-order traversal** (sorted order of keys). |
| **Binary search tree** | `BSTNode`, `bst_insert`, `bst_inorder` | Classic BST insert + in-order walk (available in engine CLI as `bst`). |
| **Heap** | **Max-heap** (`MaxHeap`) + `heap_sort` uses `priority_queue` | **Top-k** extraction; heap sort builds sorted output via a min-heap priority queue. |
| **Sorting** | **Merge sort**, **Quick sort**, **Heap sort** | User-selectable (`merge` / `quick` / `heap`) over a list of integers. |
| **Searching** | **Linear search**, **Binary search** | Engine CLI `search` with `linear` or `binary` on parsed arrays. |
| **Graph** | Adjacency list (`unordered_map` + edges), **BFS** (`queue`), **DFS** (recursive / implicit stack), **Dijkstra** (`priority_queue` min-heap) | Fixed demo graph between sector-like labels (`IT`, `BANKING`, …); returns traversal order or shortest distances. |
| **Hash table** | Separate chaining (`HashTable`, bucket vector + lists) | Key→value lookup demo (engine CLI `hash`). |
| **Stack / Queue** | `SimpleStack`, `SimpleQueue` | LIFO/FIFO demos on string tokens (engine CLI `stack`, `queue`). |

**Graph detail:** BFS uses an explicit **queue** and visited map; DFS walks recursively; Dijkstra uses a **priority queue** for shortest paths on weighted edges.

### What the Flask app uses today

Not every engine command has a REST route yet. The web app **actively calls** the subprocess for:

| Engine use | Flask / UX |
|------------|------------|
| `health` | `/api/ds/health` — sanity check |
| `trie <prefix>` | **`/search`** (symbol suggestions) and **`/api/ds/trie`** |
| `sort <algo> <csv>` | **`/demo`**, **`/api/ds/sort`** — merge / quick / heap |
| `graph <algo> <start>` | **`/demo`**, **`/api/ds/graph`** — BFS / DFS / Dijkstra |
| `avl <csv>` | **`/api/ds/avl`** — balanced tree in-order result |

Other engine entry points (`search`, `heap` top-k, `hash`, `bst`, `stack`, `queue`) are implemented in the **same binary** and can be wired to new routes or tested by invoking `ds_engine.exe` from the command line with the appropriate arguments (see `main()` in `data_structures.cpp`).

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
