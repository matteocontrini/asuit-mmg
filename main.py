import asyncio
import json
import os
import re
import time
from typing import Any

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup


# Configuration Functions

def get_data_file_path() -> str:
    """Get path to doctor_state.json file."""
    data_dir = os.getenv('DATA_DIR', '.')
    return os.path.join(data_dir, 'doctor_state.json')


def load_state() -> dict[str, Any]:
    """
    Load doctor state from JSON file.

    Returns:
        dict with keys 'doctors' and 'location_cache'
        Empty dicts if file doesn't exist
    """
    file_path = get_data_file_path()
    if os.path.exists(file_path):
        try:
            with open(file_path, encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            print(f"Warning: Failed to parse state file: {e}")
            print("Starting with empty state")
            return {'doctors': {}, 'location_cache': {}}
    return {'doctors': {}, 'location_cache': {}}


def save_state(state: dict[str, Any]) -> None:
    """
    Save doctor state to JSON file.

    Args:
        state: dict with 'doctors' and 'location_cache' keys
    """
    file_path = get_data_file_path()
    os.makedirs(os.path.dirname(file_path) or '.', exist_ok=True)
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def get_doctor_detail_url(doctor_id: str) -> str:
    """
    Build detail URL for a doctor.

    Args:
        doctor_id: Doctor code

    Returns:
        Full URL to doctor detail page
    """
    return f"https://servizi.apss.tn.it/ricmedico/medico.php?codMedicoMg={doctor_id}"


def get_search_url() -> str:
    """
    Build search URL based on SEARCH_MODE env variable.

    Returns:
        Full URL for scraping doctor list

    Raises:
        ValueError: if SEARCH_MODE is invalid or required params missing
    """
    base_url = 'https://servizi.apss.tn.it/ricmedico/listamedici.php'
    search_mode = os.getenv('SEARCH_MODE', '').lower()

    if search_mode == 'ambito':
        ambito_id = os.getenv('AMBITO_ID')
        if not ambito_id:
            raise ValueError("AMBITO_ID required when SEARCH_MODE=ambito")
        return f"{base_url}?tipoRicerca=ambito&tipoMedico=MMG&ambito={ambito_id}"

    elif search_mode == 'comune':
        comune_code = os.getenv('COMUNE_CODE')
        if not comune_code:
            raise ValueError("COMUNE_CODE required when SEARCH_MODE=comune")
        return f"{base_url}?tipoMedico=MMG&tipoRicerca=comune&comune={comune_code}&Ricerca=ricerca"

    else:
        raise ValueError(f"Invalid SEARCH_MODE: {search_mode}. Must be 'ambito' or 'comune'")


def scrape_doctor_list() -> list[dict[str, str]]:
    """
    Scrape list of doctors from APSS website.

    Returns:
        List of doctor dicts with keys:
        - id: doctor code (from medico.php?codMedicoMg=XXX)
        - first_name: doctor's first name
        - last_name: doctor's last name
        - availability: availability status string

    Raises:
        requests.RequestException: on HTTP errors
        ValueError: if table structure doesn't match expected format
    """
    url = get_search_url()
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')

    doctors = []

    # Find table with doctor information
    table = soup.find('table')
    if not table:
        raise ValueError("Doctor table not found in page")

    # Find tbody and get rows from there
    tbody = table.find('tbody')
    if not tbody:
        raise ValueError("Table body (tbody) not found in doctor table")

    rows = tbody.find_all('tr')

    # Process data rows
    for row in rows:
        cols = row.find_all('td')

        if len(cols) < 4:
            raise ValueError(f"Expected at least 4 columns in doctor row, found {len(cols)}")

        first_name = cols[0].get_text(strip=True)
        last_name = cols[1].get_text(strip=True)
        availability = cols[2].get_text(strip=True)

        # Extract doctor ID from detail link
        detail_link = cols[3].find('a')
        if not detail_link or 'href' not in detail_link.attrs:
            raise ValueError(f"No detail link found for doctor: {first_name} {last_name}")

        detail_url = detail_link['href']

        # Extract doctor ID from URL (medico.php?codMedicoMg=XXX)
        match = re.search(r'codMedicoMg=([^&]+)', detail_url)
        if not match:
            raise ValueError(f"Could not extract doctor ID from URL: {detail_url}")

        doctor_id = match.group(1)

        doctors.append({
            'id': doctor_id,
            'first_name': first_name,
            'last_name': last_name,
            'availability': availability
        })

    return doctors


def scrape_doctor_locations(detail_url: str) -> list[str]:
    """
    Scrape location information from individual doctor page.

    Args:
        detail_url: URL to doctor detail page (medico.php?codMedicoMg=XXX)

    Returns:
        List of location strings (e.g., ["ARCO", "RIVA DEL GARDA"])
        Empty list if no locations found or on error
    """
    try:
        response = requests.get(detail_url, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        locations = []

        # Find all <b> tags that contain "Comune:"
        bold_tags = soup.find_all('b')

        for tag in bold_tags:
            text = tag.get_text(strip=True)
            if text.startswith('Comune:'):
                # Remove the "Comune: " prefix
                location = text.replace('Comune:', '').strip()
                if location and location not in locations:
                    locations.append(location)

        return locations

    except Exception as e:
        print(f"Warning: Failed to scrape locations from {detail_url}: {e}")
        return []


def get_doctor_locations(doctor_id: str, detail_url: str, location_cache: dict[str, Any]) -> list[str]:
    """
    Get doctor locations from cache or scrape if needed.

    Args:
        doctor_id: Doctor code
        detail_url: URL to doctor detail page
        location_cache: Current location cache dict

    Returns:
        List of location strings
        Updates location_cache with new data if scraped
    """
    cache_days = int(os.getenv('LOCATION_CACHE_DAYS', '7'))
    cache_expiry_seconds = cache_days * 24 * 3600
    current_time = int(time.time())

    # Check if cached and not expired
    if doctor_id in location_cache:
        cached = location_cache[doctor_id]
        if current_time - cached['timestamp'] < cache_expiry_seconds:
            return cached['locations']

    # Cache miss or expired - scrape
    print(f"Scraping locations for doctor {doctor_id}...")
    locations = scrape_doctor_locations(detail_url)

    # Update cache
    location_cache[doctor_id] = {
        'locations': locations,
        'timestamp': current_time
    }

    # Rate limiting
    time.sleep(1)

    return locations


def detect_changes(
        current_doctors: list[dict[str, str]],
        previous_state: dict[str, Any],
        location_cache: dict[str, Any]
) -> dict[str, Any]:
    """
    Detect changes between current scrape and previous state.

    Args:
        current_doctors: List of doctor dicts from scrape_doctor_list()
        previous_state: Previous state dict with 'doctors' key
        location_cache: Location cache dict (will be updated)

    Returns:
        dict with keys:
        - added: list of doctor dicts (new doctors)
        - removed: list of doctor dicts (removed doctors)
        - changed: list of tuples (doctor_dict, old_availability, new_availability)
        - location_cache: updated location cache
    """
    changes = {
        'added': [],
        'removed': [],
        'changed': [],
        'location_cache': location_cache
    }

    current_ids = {d['id']: d for d in current_doctors}
    previous_ids = previous_state.get('doctors', {})

    # Detect added doctors
    for doc_id, doctor in current_ids.items():
        if doc_id not in previous_ids:
            # New doctor - fetch locations
            locations = get_doctor_locations(
                doctor['id'],
                get_doctor_detail_url(doctor['id']),
                location_cache
            )
            doctor['locations'] = locations
            changes['added'].append(doctor)

    # Detect removed doctors
    for doc_id, doctor in previous_ids.items():
        if doc_id not in current_ids:
            # Get locations from cache (may be stale but that's ok)
            cached = location_cache.get(doc_id, {})
            doctor['locations'] = cached.get('locations', [])
            changes['removed'].append(doctor)

    # Detect availability changes
    for doc_id, current_doctor in current_ids.items():
        if doc_id in previous_ids:
            previous_doctor = previous_ids[doc_id]
            if current_doctor['availability'] != previous_doctor['availability']:
                # Status changed - fetch fresh locations
                locations = get_doctor_locations(
                    current_doctor['id'],
                    get_doctor_detail_url(current_doctor['id']),
                    location_cache
                )
                current_doctor['locations'] = locations
                changes['changed'].append((
                    current_doctor,
                    previous_doctor['availability'],
                    current_doctor['availability']
                ))

    return changes


def escape_markdown(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    return text


def format_doctor(doctor: dict[str, Any]) -> str:
    """Format single doctor entry."""
    name = f"{doctor['first_name']} {doctor['last_name']}"
    locations = ', '.join(doctor.get('locations', [])) if doctor.get('locations') else 'N/A'
    return f"  • *{escape_markdown(name)}* \\({escape_markdown(locations)}\\)"


def format_telegram_message(changes: dict[str, Any]) -> str:
    """
    Format changes into a Telegram message with MarkdownV2.

    Args:
        changes: dict from detect_changes()

    Returns:
        Formatted message string with proper escaping
    """
    message_parts = []

    # Header
    message_parts.append("🏥 *Aggiornamento medici di medicina generale*")

    # Added doctors
    if changes['added']:
        message_parts.append(f"➕ *Medici aggiunti* \\({len(changes['added'])}\\):")

        # Group added doctors by availability
        availability_groups: dict[str, list] = {}
        for doctor in changes['added']:
            avail = doctor['availability']
            if avail not in availability_groups:
                availability_groups[avail] = []
            availability_groups[avail].append(doctor)

        for avail_status, doctors in availability_groups.items():
            message_parts.append(f"\n_{escape_markdown(avail_status)}_:")
            for doctor in doctors:
                message_parts.append(format_doctor(doctor))

    # Removed doctors
    if changes['removed']:
        message_parts.append(f"\n➖ *Medici rimossi* \\({len(changes['removed'])}\\):")
        for doctor in changes['removed']:
            message_parts.append(format_doctor(doctor))

    # Changed availability
    if changes['changed']:
        message_parts.append(f"\n🔄 *Cambio disponibilità* \\({len(changes['changed'])}\\):")
        for doctor, old_avail, new_avail in changes['changed']:
            name = f"{doctor['first_name']} {doctor['last_name']}"
            locations = ', '.join(doctor.get('locations', [])) if doctor.get('locations') else 'N/A'
            message_parts.append(
                f"  • *{escape_markdown(name)}* \\({escape_markdown(locations)}\\)\n"
                f"    {escape_markdown(old_avail)} → {escape_markdown(new_avail)}"
            )

    return '\n'.join(message_parts)


async def post_to_telegram(changes: dict[str, Any]) -> None:
    """
    Post changes to Telegram channel.

    Args:
        changes: dict from detect_changes()

    Raises:
        telegram.error.TelegramError: on posting failures
    """
    bot = Bot(token=os.getenv('BOT_TOKEN'))
    channel_id = os.getenv('CHANNEL_ID')

    message = format_telegram_message(changes)

    # Check message length (Telegram limit is 4096 characters)
    if len(message) > 4000:
        print("Warning: Message exceeds 4000 characters, might be truncated")

    # Create inline keyboard with link to search page
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 Cerca medico", url=get_search_url())]
    ])

    await bot.send_message(
        chat_id=channel_id,
        text=message,
        parse_mode='MarkdownV2',
        reply_markup=keyboard,
        disable_web_page_preview=True
    )


def main() -> int:
    # Load environment variables
    load_dotenv()

    # Validate required env vars
    required_vars = ['BOT_TOKEN', 'CHANNEL_ID', 'SEARCH_MODE']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        print(f"Error: Missing required env vars: {', '.join(missing_vars)}")
        return 1

    # Validate search URL can be built
    search_url = get_search_url()
    print(f"Search URL: {search_url}")

    # Check if first run
    is_first_run = not os.path.exists(get_data_file_path())

    # Load previous state
    state = load_state()
    print(f"Loaded state with {len(state.get('doctors', {}))} doctors")

    # Scrape current doctor list
    current_doctors = scrape_doctor_list()
    print(f"Scraped {len(current_doctors)} doctors")

    if not current_doctors:
        print("Error: No doctors found in scrape")
        return 1

    # First run: initialize state without posting
    if is_first_run:
        print("First run: initializing state")

        # Build initial state (don't fetch locations on first run)
        new_state = {
            'doctors': {d['id']: d for d in current_doctors},
            'location_cache': {}
        }

        save_state(new_state)
        print(f"✓ Initialized state with {len(current_doctors)} doctors")
        print("Future runs will detect and post changes")
        return 0

    # Detect changes
    location_cache = state.get('location_cache', {})
    changes = detect_changes(current_doctors, state, location_cache)

    total_changes = len(changes['added']) + len(changes['removed']) + len(changes['changed'])
    print(f"Detected {total_changes} changes:")
    print(f"  Added: {len(changes['added'])}")
    print(f"  Removed: {len(changes['removed'])}")
    print(f"  Changed: {len(changes['changed'])}")

    # Update state with current doctors
    new_state = {
        'doctors': {d['id']: d for d in current_doctors},
        'location_cache': changes['location_cache']
    }

    # Post to Telegram if there are changes
    if total_changes > 0:
        asyncio.run(post_to_telegram(changes))
        print("✓ Posted changes to Telegram")
    else:
        print("No changes to post")

    # Save updated state
    save_state(new_state)
    print("✓ State saved")

    return 0


if __name__ == '__main__':
    exit(main())
