# Quanlaidian Quote Service

FastAPI backend for Quanlaidian quotation generation.

## Setup

1. Clone this repo (private)
2. `python -m venv .venv && source .venv/bin/activate`
3. `pip install -e ".[dev]"`
4. Copy `.env.example` to `.env` and configure
5. Place `pricing_baseline.json` in `data/`
6. `uvicorn app.main:app --reload`
