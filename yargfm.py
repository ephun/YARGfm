import os
import sqlite3
import time
import datetime
import webbrowser
import requests
import json
from dotenv import load_dotenv

import pylast

# Load environment variables
load_dotenv()

# --- YARGfm: Scrobble your rhythm game grooves to Last.fm and ListenBrainz! ---
__author__ = "Ethan Kendrick, powered by Google Gemini and pylast"

# --- Configuration (from .env) ---
LASTFM_API_KEY = os.environ.get("LASTFM_API_KEY")
LASTFM_API_SECRET = os.environ.get("LASTFM_API_SECRET")
LASTFM_USERNAME = os.environ.get("LASTFM_USERNAME")
LASTFM_PASSWORD_HASH_RAW = os.environ.get("LASTFM_PASSWORD_HASH", "")

LISTENBRAINZ_URL = os.environ.get("LISTENBRAINZ_URL", "https://api.listenbrainz.org").rstrip("/")
LISTENBRAINZ_TOKEN = os.environ.get("LISTENBRAINZ_TOKEN")

DB_PATH = os.environ.get("YARG_DB_PATH", r"C:\Users\ethan\AppData\LocalLow\YARC\YARG\release\scores\scores.db")

POLLING_INTERVAL = 60
SCROBBLE_BATCH_SIZE = 50

# --- File Persistence Setup ---
LAST_SCROBBLED_FILE = os.path.join(os.path.dirname(__file__), "last_scrobbled.txt")

# --- Last.fm Setup ---
network = None
if LASTFM_API_KEY and LASTFM_API_SECRET and LASTFM_USERNAME and LASTFM_PASSWORD_HASH_RAW:
    network = pylast.LastFMNetwork(
        api_key=LASTFM_API_KEY,
        api_secret=LASTFM_API_SECRET,
        username=LASTFM_USERNAME,
        password_hash=pylast.md5(LASTFM_PASSWORD_HASH_RAW),
    )

def listenbrainz_enabled():
    return bool(LISTENBRAINZ_URL and LISTENBRAINZ_TOKEN)

# --- Functions ---

def ticks_to_struct_time(ticks):
    """Converts .NET-style ticks to a struct_time tuple."""
    ticks_since_epoch = ticks / 10000000  # Ticks per second
    epoch_start = datetime.datetime(1, 1, 1)  # .NET epoch start
    datetime_value = epoch_start + datetime.timedelta(
        seconds=ticks_since_epoch
    )
    return datetime_value.timetuple()

def submit_to_listenbrainz(tracks):
    """Submits a batch of tracks to ListenBrainz."""
    if not listenbrainz_enabled():
        return
        
    payload = {
        "listen_type": "import",
        "payload": []
    }
    
    for track in tracks:
        payload["payload"].append({
            "listened_at": track["timestamp"],
            "track_metadata": {
                "artist_name": track["artist"],
                "track_name": track["title"]
            }
        })
        
    endpoint = f"{LISTENBRAINZ_URL}/submit-listens" if LISTENBRAINZ_URL.endswith("/1") else f"{LISTENBRAINZ_URL}/1/submit-listens"
    headers = {
        "Authorization": f"Token {LISTENBRAINZ_TOKEN}",
        "Content-Type": "application/json",
    }
    
    try:
        response = requests.post(endpoint, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        for track in tracks:
            print(f"Scrobbled to ListenBrainz: {track['artist']} - {track['title']} ({track['timestamp']})")
    except requests.RequestException as e:
        print(f"ListenBrainz Scrobble error: {e}")

def scrobble_tracks(tracks):
    """Scrobbles a batch of tracks to Last.fm and ListenBrainz."""
    # Scrobble to Last.fm
    if network:
        try:
            network.scrobble_many(tracks)
            for track in tracks:
                print(
                    f"Scrobbled to Last.fm: {track['artist']} - {track['title']} ({track['timestamp']})"
                )
        except pylast.WSError as e:
            print(f"Last.fm Scrobble error: {e}")
    else:
        print("Last.fm credentials missing or disabled in .env; skipping Last.fm scrobble")
        
    # Scrobble to ListenBrainz
    if listenbrainz_enabled():
        submit_to_listenbrainz(tracks)
    else:
        print("ListenBrainz credentials missing; skipping ListenBrainz scrobble")


def get_new_records(last_checked_timestamp=None):
    """Retrieves new game records from the database."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    if last_checked_timestamp:
        # Convert last_checked_timestamp to a tick value
        last_checked_tick = (last_checked_timestamp - datetime.datetime(1, 1, 1)).total_seconds() * 10000000
        query = (
            f"SELECT Date, SongName, SongArtist FROM GameRecords "
            f"WHERE Date > {last_checked_tick} "
            f"ORDER BY Date"
        )
    else:
        query = (
            "SELECT Date, SongName, SongArtist FROM GameRecords ORDER BY Date"
        )

    print("SQL Query:", query)
    cursor.execute(query)
    new_records = cursor.fetchall()
    print("New Records Found:", len(new_records))
    conn.close()

    # Convert date_value to struct_time tuples
    converted_records = []
    for record in new_records:
        date_value, song_name, song_artist = record
        if isinstance(date_value, int) or isinstance(date_value, float):  # Assuming ticks are numbers
            date_value = ticks_to_struct_time(date_value)
        elif isinstance(date_value, str):
            date_value = datetime.datetime.strptime(
                date_value, "%Y-%m-%d %H:%M:%S"
            ).timetuple()  # Call timetuple() here
        converted_records.append((date_value, song_name, song_artist))
    return converted_records


def first_time_setup():
    """Handles initial Last.fm authorization if needed."""
    if not network:
        return
        
    session_key_file = os.path.join(
        os.path.dirname(__file__), ".yargfm_session_key"
    )

    if not os.path.exists(session_key_file):
        skg = pylast.SessionKeyGenerator(network)
        url = skg.get_web_auth_url()

        print(f"First-time setup: Please authorize YARGfm on Last.fm:\n{url}\n")
        webbrowser.open(url)
        input("Press Enter after authorizing...")

        while True:
            try:
                session_key = skg.get_web_auth_session_key(url)
                with open(session_key_file, "w") as f:
                    f.write(session_key)
                network.session_key = session_key
                print("Authorization successful!")
                break
            except pylast.WSError:
                time.sleep(1)
    else:
        with open(session_key_file, "r") as f:
            network.session_key = f.read()


# --- Main Program ---

if __name__ == "__main__":
    print("Starting YARGfm...")
    first_time_setup()

    # --- Load Last Scrobbled Timestamp ---
    if os.path.exists(LAST_SCROBBLED_FILE):
        with open(LAST_SCROBBLED_FILE, "r") as f:
            try:
                last_checked_timestamp = datetime.datetime.strptime(
                    f.read().strip(), "%Y-%m-%d %H:%M:%S"
                )
            except ValueError:
                last_checked_timestamp = None
    else:
        last_checked_timestamp = None

    while True:
        new_records = get_new_records(last_checked_timestamp)
        if new_records:
            scrobble_queue = []
            for date_value, song_name, song_artist in new_records:
                unix_timestamp = int(time.mktime(date_value))
                scrobble_queue.append(
                    {
                        "artist": song_artist,
                        "title": song_name,
                        "timestamp": unix_timestamp,
                    }
                )

                if len(scrobble_queue) >= SCROBBLE_BATCH_SIZE:
                    scrobble_tracks(scrobble_queue)
                    scrobble_queue = []

            if scrobble_queue:
                scrobble_tracks(scrobble_queue)

            # Update last_checked_timestamp here
            last_checked_timestamp = new_records[-1][0]

            # --- Save Last Scrobbled Timestamp ---
            with open(LAST_SCROBBLED_FILE, "w") as f:
                # Convert to datetime if it's a struct_time
                if isinstance(last_checked_timestamp, time.struct_time):
                    last_checked_timestamp = datetime.datetime.fromtimestamp(time.mktime(last_checked_timestamp))
                f.write(last_checked_timestamp.strftime("%Y-%m-%d %H:%M:%S"))

        time.sleep(POLLING_INTERVAL)
