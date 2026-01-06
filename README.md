# Medici di medicina generale ASUIT

Scrapes ASUIT medical doctors (medici di medicina generale) and posts changes to Telegram.

> [!CAUTION]
> This project was vibe-coded with Claude Code, read and use at your own risk and don't judge :)

## Features

- Tracks doctor availability changes
- Supports ambito or comune search modes
- Caches doctor locations (7-day expiry by default)
- Groups notifications by availability status
- First-run initialization (no spam on initial setup)
- Detects both list changes (doctors added/removed) and availability status changes

## Setup

### Prerequisites

- Python 3.11 or higher
- uv package manager ([installation instructions](https://github.com/astral-sh/uv))

### Installation

1. Clone or download this repository
2. Install dependencies:

```bash
cd asuit-mmg
uv sync
```

3. Create `.env` file from template:

```bash
cp .env.example .env
```

4. Edit `.env` with your credentials and configuration

## Configuration

Edit the `.env` file with the following variables:

### Required Variables

- `BOT_TOKEN`: Your Telegram bot token (get from [@BotFather](https://t.me/botfather))
- `CHANNEL_ID`: Telegram channel ID (e.g., `-1001234567890`) or username (e.g., `@your_channel`)
- `SEARCH_MODE`: Either `ambito` or `comune`

### Search Mode Configuration

**For ambito mode:**
- `AMBITO_ID`: The ambito number (e.g., `46`)

Example:
```bash
SEARCH_MODE=ambito
AMBITO_ID=46
```

**For comune mode:**
- `COMUNE_CODE`: The comune code (e.g., `022006-46`)

Example:
```bash
SEARCH_MODE=comune
COMUNE_CODE=022006-46
```

### Optional Variables

- `DATA_DIR`: Directory where `doctor_state.json` will be stored (default: current directory)
- `LOCATION_CACHE_DAYS`: Number of days before location cache expires (default: `7`)

## Usage

Run the scraper manually:

```bash
uv run python main.py
```

### First Run

On the first run, the script will:
1. Scrape the current list of doctors
2. Save the state to `doctor_state.json`
3. Exit without posting to Telegram

This prevents spamming your channel with all existing doctors.

### Subsequent Runs

On subsequent runs, the script will:
1. Scrape the current list of doctors
2. Compare with previous state
3. Detect changes (added doctors, removed doctors, availability changes)
4. Post changes to Telegram (if any)
5. Update the state file

## Automation

Schedule the scraper to run periodically using cron.

## How It Works

1. **State Management**: The script maintains a `doctor_state.json` file that tracks:
   - All doctors and their availability status
   - Cached location information with timestamps

2. **Change Detection**: On each run, the script compares the current scrape with the saved state to detect:
   - New doctors added to the list
   - Doctors removed from the list
   - Changes in availability status for existing doctors

3. **Location Scraping**:
   - For new doctors or doctors with changed status, the script scrapes their individual detail page
   - Locations are cached for 7 days (configurable) to reduce load on the ASUIT server

4. **Telegram Notifications**:
   - Changes are grouped by type (added/removed/changed)
   - Added doctors are further grouped by availability status
   - Each notification includes doctor names and their locations
   - A button links to the search page

## Telegram Message Example

```
🏥 Aggiornamento Medici di Base

➕ Medici Aggiunti (2):

Disponibile:
  • Mario Rossi (ARCO, RIVA DEL GARDA)

Nessuna Disponibilità:
  • Laura Bianchi (TRENTO)

➖ Medici Rimossi (1):
  • Giovanni Verdi (ROVERETO)

🔄 Cambio Disponibilità (1):
  • Paolo Neri (ARCO)
    Nessuna Disponibilità → Disponibile
```
