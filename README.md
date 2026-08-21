# Company Scout

AI-powered company intelligence tool. Enter a company name, get an evidence-backed research brief.

## Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Copy env file and add your API keys
cp .env.example .env
# Edit .env with your ANTHROPIC_API_KEY and TAVILY_API_KEY
```

## Usage

### CLI
```bash
python -m backend "Spiro"
```

### API Server
```bash
uvicorn backend.main:app --reload
# Then POST to http://localhost:8000/scout with {"query": "Spiro"}
```

## Project Status

See [TASKS.md](TASKS.md) for current progress.
