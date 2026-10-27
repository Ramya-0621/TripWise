# TripWise: Intelligent Travel Planning Bot

TripWise recommends trips across India from your starting city, budget (in rupees), trip length,
destination type, transport and accommodation preference, interests and number of travelers.
A Python/Flask backend does the real work (constraint filtering, breadth-first search,
heuristic scoring, ranking, cost calculation). A plain HTML/CSS/JavaScript page shows the results.

No Node.js, React, paid API or API key is needed.

> **Important: all prices are illustrative estimates.** Fares, distances, travel times and hotel
> prices are rough planning figures stored in JSON and computed from coordinates. They are not live data.

---

## 1. Project structure

```
TripWise/
├── frontend/
│   ├── index.html        page structure
│   ├── style.css         responsive design (CSS Grid + Flexbox)
│   └── script.js         form handling, fetch() calls, rendering
├── backend/
│   ├── app.py            Flask REST API (also serves the frontend)
│   ├── recommender.py    recommendation workflow, validation, scoring, ranking
│   ├── search_algorithms.py   constraint filter, BFS, heap-based top-k
│   ├── rules.py          rule-based reasoning + cost model + heuristic components
│   ├── knowledge_base.py loads and validates the JSON knowledge
│   ├── data/
│   │   ├── destinations.json   18 destinations, activities, illustrative costs
│   │   └── reference.json      categories, interests, transport rates, start cities
│   └── tests/test_recommender.py   20 automated tests
├── requirements.txt      (Flask only)
├── README.md
└── .gitignore
```

---

## 2. Run it on Windows (step by step)

You need **Python 3.10 or newer** (check with `python --version` or `py --version`).
Install it from <https://www.python.org/downloads/> if needed and tick **"Add python.exe to PATH"**.

1. **Open the project in VS Code.** `File > Open Folder...` and choose the `TripWise` folder.
2. **Open a terminal.** `Terminal > New Terminal`. It should show a PowerShell prompt ending in `TripWise>`.
3. **Create a virtual environment** (once):
   ```powershell
   py -m venv .venv
   ```
4. **Activate it:**
   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```
   You should see `(.venv)` at the start of the prompt. If PowerShell refuses to run the script, run this once and retry:
   ```powershell
   Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
   ```
5. **Install the packages:**
   ```powershell
   pip install -r requirements.txt
   ```
6. **Start the backend (Terminal 1):**
   ```powershell
   cd backend
   python app.py
   ```
   You should see `TripWise running at http://127.0.0.1:5000`. Leave this terminal open.
7. **Open the frontend.** Choose one:
   - **Simplest:** open <http://127.0.0.1:5000> in your browser. Flask serves the frontend too.
   - **VS Code Live Server:** install the *Live Server* extension, right-click `frontend/index.html`,
     choose **Open with Live Server** (usually `http://127.0.0.1:5500/frontend/index.html`).
     The page then calls the Flask API on port 5000. The backend allows this with development CORS headers.

The status pill in the top bar says **Backend online** when the page can reach Flask.

### Run the automated tests
From the `TripWise` folder (not `backend`), with the virtual environment active:
```powershell
python -m unittest discover -s backend/tests -v
```

### Test each API endpoint (PowerShell)
```powershell
Invoke-RestMethod http://127.0.0.1:5000/api/health
Invoke-RestMethod http://127.0.0.1:5000/api/options
(Invoke-RestMethod http://127.0.0.1:5000/api/destinations).destinations | Select-Object id, name, category
Invoke-RestMethod http://127.0.0.1:5000/api/destination/goa

$body = @{ starting_city="Hyderabad"; budget=40000; days=5; travelers=2; category="beach"; interests=@("water_sports","food") } | ConvertTo-Json
$result = Invoke-RestMethod -Uri http://127.0.0.1:5000/api/recommend -Method Post -ContentType "application/json" -Body $body
$result.itineraries | Select-Object rank, @{n="place";e={$_.destination.name}}, score
```
You can also open the GET URLs directly in a browser.

| Method | URL | Purpose |
|---|---|---|
| GET | `/api/health` | server status |
| GET | `/api/options` | cities, categories, interests for the form |
| GET | `/api/destinations` | all destinations (optional `?category=beach`) |
| GET | `/api/destination/<id>` | one destination, for example `goa` |
| POST | `/api/recommend` | JSON preferences in, ranked itineraries out |

Invalid input returns **400** with a list of problems. Unknown destination ids return **404**.
A search with no feasible trip returns **200** with `count: 0`, a message and suggestions.

### Troubleshooting

| Problem | Fix |
|---|---|
| `python` is not recognised | Install Python and tick "Add to PATH", then reopen VS Code. Try `py` instead of `python`. |
| `Activate.ps1 cannot be loaded` | Run `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`. |
| `No module named flask` | The virtual environment is not active. Run the activate command, then `pip install -r requirements.txt`. |
| `can't open file ... app.py` | You are in the wrong folder. Run `cd backend` first (the prompt should end in `backend>`). |
| Test command finds no tests | Run it from the `TripWise` folder, not from `backend`. |
| `pip` fails to install | Check your internet connection, then `python -m pip install --upgrade pip` and retry. |
| `Address already in use` / port 5000 busy | Run `$env:PORT=5001; python app.py`. Open `http://127.0.0.1:5001`. (For Live Server, also change `FLASK_URL` at the top of `frontend/script.js`.) |
| Page says "Backend offline" / cannot reach server | Start the backend (step 6) and reload. Check the URL in the error message. |
| Photos are missing | Photos load from Wikipedia. Offline or blocked networks show a coloured fallback instead. |

---

## 3. Academic documentation

### Problem statement
Planning a trip means juggling budget, time, transport, stay and interests at once. Search sites list
options but do not reason about which *combination* fits a traveler. TripWise automates that reasoning
for domestic Indian trips and explains its choices.

### Objectives
- Recommend destinations, transport, accommodation and activities that fit a stated budget.
- Use real, inspectable AI techniques (search, heuristics, rules) rather than canned replies.
- Calculate a transparent cost breakdown and show the remaining budget.
- Explain every recommendation in plain language.

### System architecture
```
Browser (HTML/CSS/JS)                       Flask server (Python)
 form -> fetch POST /api/recommend  ----->  app.py          validates HTTP, returns JSON
 cards, budget bars  <-----  JSON            recommender.py  workflow: validate, filter, search, score, rank
                                             search_algorithms.py   filter, BFS, top-k
                                             rules.py        rules + cost model + score components
                                             knowledge_base.py  reads data/*.json
```
The frontend contains **no** recommendation logic. It only displays what Python returns.

### Knowledge representation
- `destinations.json`: one object per destination: category and secondary categories, minimum/ideal/maximum
  days, coordinates, which transport modes can reach it, accommodation rate per room per night for three tiers,
  food per person per day, local transport per vehicle per day, interest tags, and 5 activities (each with cost, half-day slots and tags).
- `reference.json`: categories, interests, transport-mode rates and speeds, and start cities with coordinates.
- Loaded into Python dictionaries and lists by `knowledge_base.py`. Edit the JSON to add destinations; no code changes needed.

Transport fares are **computed**, not stored per route: `fare = max(minimum, base + rate x km)`, doubled for a round trip,
plus the destination's transfer cost. Distance comes from the haversine formula on coordinates
(x1.25 for road/rail). Bus, train and flight each have a usable distance range.

### Search techniques (all implemented)
1. **Constraint-based pruning** (`filter_destinations`): removes destinations that are too close to the start city,
   outside the preferred category, share no interest with the user, or need more days than the trip has.
2. **Breadth-first search** (`bfs_search`, a FIFO queue): explores the state space
   `start -> destination -> transport -> accommodation -> activities -> complete`.
   Activities are added one at a time in index order, so each subset is generated once.
3. **Early pruning inside BFS**: a child state is dropped *before* it is queued if
   the travel time is too long (R7), the cheapest possible stay already exceeds the budget (R5),
   the cost with the chosen activities exceeds the budget (R5), or the activities need more half-day slots than exist (R10).
4. **Heuristic scoring**: a weighted sum of five components, each between 0 and 1:

   | Component | Default weight | Meaning |
   |---|---|---|
   | Interest match | 0.35 | share of your interests covered by the destination tags or chosen activities |
   | Category match | 0.20 | 1.0 primary category, 0.6 secondary, 0.5 if "any" |
   | Budget fit | 0.20 | 1.0 when 60-95% of the budget is used; lower for very cheap or nearly over-budget trips |
   | Duration suitability | 0.15 | 1.0 inside ideal-max days; rising from 0.7 between minimum and ideal; penalised beyond the maximum |
   | Transport preference | 0.10 | 1.0 for your chosen mode, 0.3 for others; in "auto", faster routes score higher |

   Weights live in `rules.DEFAULT_WEIGHTS` and can be overridden per request with a `weights` object (they are normalised to sum to 1).
5. **Priority-based ranking** (`top_k`, using `heapq.nlargest`): the best itinerary per destination is kept, then the top 5 are returned.

### Rule-based reasoning (`rules.py`)
| Rule | Behaviour |
|---|---|
| R1 | Reject a destination less than 40 km from the start city. |
| R2 | Category match scores 1.0 (primary) or 0.6 (secondary). |
| R3 | Interests that overlap destination or activity tags raise the interest score. |
| R4 | Reject if days < minimum; penalise if days > maximum. |
| R5 | Reject any itinerary whose estimated total exceeds the budget. |
| R6 | Offer a transport mode only if the destination can be reached by it within a sensible distance. |
| R7 | Reject a transport mode if round-trip travel time exceeds 40% of the trip. |
| R8 | The preferred transport is explored first and kept whenever a feasible itinerary uses it. |
| R9 | Accommodation is priced with the chosen tier's rate (luxury uses luxury rates). |
| R10 | Activities must fit the available half-day slots (2 per day, minus 2 for arrival and departure). |
| R11 | If nothing matches exactly, relax interests, then category, and say so. Budget and trip length are never relaxed. |

### Cost model
All costs are counted once:
- **Transport** = round-trip fare per person x travelers (+ transfer cost per person)
- **Accommodation** = rate **per room per night** x rooms x nights. Two travelers share a room, so 5 travelers need 3 rooms. Nights = days - 1.
- **Food** = food per person per day x tier multiplier (budget 0.8, standard 1.0, luxury 1.5) x days x travelers
- **Local transport** = cost per vehicle per day x vehicles x days (one vehicle per 4 travelers)
- **Activities** = sum of activity cost per person x travelers
- **Remaining budget** = budget - total

### Recommendation workflow
1. Validate input (HTTP 400 with a list of problems if wrong).
2. Load the knowledge base.
3. Apply hard constraints to destinations.
4. Run BFS with early pruning to build every affordable itinerary.
5. Score each finished itinerary with the weighted heuristic.
6. Keep the best itinerary per destination (respecting the transport preference).
7. Rank with a heap and return up to 5.
8. Attach reasons, the score breakdown and the rules applied.
9. If nothing fits, relax interests/category (R11) or return a diagnosis with suggestions.

### Worked example
**Input:** start Hyderabad, budget Rs 40,000, 5 days, 2 travelers, type Beaches, interests water sports and food, transport Auto, accommodation Any.

- **Filtering:** 14 of 18 destinations are removed by the category constraint. Gokarna, Goa, Pondicherry and Andaman remain.
- **BFS:** it explores the remaining destinations. Andaman (flight only, about Rs 27,000 in fares for two) never gets a complete itinerary within Rs 40,000, so its branches are pruned.
- **Result (rank 1, Goa, score 98.6):** flight (about 4.7 h each way, estimated) with budget accommodation and four activities.
  Estimated cost: transport Rs 15,240 + accommodation Rs 6,000 (1 room x 4 nights x Rs 1,500) + food Rs 7,200 + local transport Rs 3,500 + activities Rs 5,000 = **Rs 36,940**, leaving **Rs 3,060**.
- **Score:** interest 1.0 x 35 + category 1.0 x 20 + budget fit 1.0 x 20 + duration 1.0 x 15 + transport 0.86 x 10 = **98.6**.
  Pondicherry (95.5) and Gokarna (78.5) follow. Gokarna scores lower because its tags cover only one of the two interests.

Try it and compare with the numbers shown on screen. The "How the search ran" panel shows how many BFS states were expanded and pruned.

### Limitations
- Prices, distances and travel times are illustrative estimates, not live data.
- 18 destinations and 27 start cities; everything is within India.
- Seasonality is shown as text but is not used in the score.
- No live availability, no booking, no multi-city routes.
- Photos depend on Wikipedia being reachable.
- The development server and the open CORS setting are for local use only.

### Future enhancements (NOT implemented)
- Live fares and hotel prices from real APIs.
- Season-aware and weather-aware scoring.
- Multi-city itineraries and day-by-day schedules.
- A* search with an admissible cost heuristic, or learning-to-rank from user feedback.
- User accounts and saved trips.
- Natural-language chat input for the preferences.

---

## 4. Credits and licences
Destination photos are loaded at runtime from the Wikipedia REST API and remain under their own licences.
Fonts come from Google Fonts and icons from the Lucide CDN (the page works without Lucide).
