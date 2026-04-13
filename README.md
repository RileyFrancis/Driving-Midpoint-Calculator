# driving_midpoint

Finds the fairest driving midpoint between any number of locations — the point that minimizes the worst-case travel time for all parties.

## Setup

```bash
pip install requests python-dotenv
```

Create a `.env` file in the same directory:
```
ORS_API_KEY=your_key_here
```

Get a free API key at [openrouteservice.org](https://openrouteservice.org/).

## Usage

```bash
python driving_midpoint.py "New York, NY" "Philadelphia, PA" "Boston, MA"
```

Optional flags:
- `--radius KM` — search radius around the centroid (default: 10)
- `--grid N` — candidate grid density (default: 3, creates a 7×7 grid)