# BEER Battleship

Engage in Explosive Rivalry (BEER) – a real-time networked Battleship game using a custom CRC-32 framed protocol, with chat, reconnection, and spectator support.

## Installation

```bash
# Clone and enter repository
git clone <repo-url>
cd beer_project

# Create and activate virtual environment
python3.11 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install the package and development tools
pip install --upgrade pip
pip install -e .
```

## Usage

```bash
# Terminal 1 – start server
beer-server --host 127.0.0.1 --port 61337

# Terminal 2 – player 1
beer-client --name Alice

# Terminal 3 – player 2
beer-client --name Bob

# (Optional) Launch two automated bots
beer-bot --host 127.0.0.1 --port 61337
```

## Testing

```bash
# Run all unit and integration tests
pytest
```

## Development

- Format code with Black:  `black src beer tests`
- Lint with Flake8:   `flake8`
- Type check with mypy:   `mypy src/beer`

## Documentation

See the `docs/` directory for protocol design, diagrams, and developer guides.

---

License: MIT
