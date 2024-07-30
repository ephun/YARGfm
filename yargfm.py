# --- YARGfm - Scrobble YARG plays to Last.fm! ---
# Author: Ethan Kendrick / Assisted by Gemini 1.5 Pro
# License: GNU General Public License v3

import os
import sqlite3 
import time 
import datetime
import webbrowser
import pytz

import pylast


# --- Configuration ---
API_KEY = "YOUR_LAST_FM_API_KEY" # Generated with API acct at https://www.last.fm/api/account/create
API_SECRET = "YOUR_LAST_FM_API_" # Generated with API acct at https://www.last.fm/api/account/create
USERNAME = "YOUR_LAST_FM_USERNAME"
PASSWORD_HASH = pylast.md5("YOUR_LAST_FM_PASSWORD")

DB_PATH = (
    r"C:\PATH\TO\YOUR\scores.db" # Path to scores.db file that YARG uses. Typical install looks somthing like "C:\Users\USER_NAME\AppData\LocalLow\YARC\YARG\release\scores\scores.db"
)
POLLING_INTERVAL = 60 # How frequently to poll the SQLite database for new YARG plays
SCROBBLE_BATCH_SIZE = 10 # It is wise to keep this value low to prevent rate-limiting

LAST_SCROBBLED_FILE = (
    r"C:\PATH\TO\YOUR\last_scrobbled.txt" # Sets up a simple persistent text file at given location to prevent excess repeat scrobble requests. This should be stored in a place separate from YARG folder structure. NOTE: Current imperfect implementation duplicates some scrobble queries, but Last.FM should prevent these automatically
)

# --- Last.fm Setup ---
network = pylast.LastFMNetwork(
    api_key=API_KEY,
    api_secret=API_SECRET,
    username=USERNAME,
    password_hash=PASSWORD_HASH,
)


# --- Functions ---
def ticks_to_struct_time(ticks):
    """Converts .NET-style ticks to a struct_time tuple. Scores.db keeps `Date` in ticks, and Last.fm API requires UTC."""
    ticks_since_epoch = ticks / 10000000  # Ticks per second
    epoch_start = datetime.datetime(1, 1, 1)  # .NET epoch start
    datetime_value = epoch_start + datetime.timedelta(
        seconds=ticks_since_epoch
    )
    return datetime_value.timetuple()


def scrobble_tracks(tracks):
    """Scrobbles tracks to Last.fm."""
    try:
        network.scrobble_many(tracks)
        for track in tracks:
            print(
                f"Scrobbled: {track['artist']} - {track['title']} ({track['timestamp']})"
            )
    except pylast.WSError as e:
        print(f"Scrobble error: {e}")


def get_new_records(last_checked_timestamp=None):
    """Retrieves new game records from score.db."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    if last_checked_timestamp:
        """Convert last_checked_timestamp back to a tick value to check against the database"""
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

    """Convert date_value to struct_time tuples"""
    converted_records = []
    for record in new_records:
        date_value, song_name, song_artist = record
        if isinstance(date_value, int):
            date_value = ticks_to_struct_time(date_value)
        elif isinstance(date_value, str):
            date_value = datetime.datetime.strptime(
                date_value, "%Y-%m-%d %H:%M:%S"
            ).timetuple()
        converted_records.append((date_value, song_name, song_artist))
    return converted_records


def first_time_setup():
    """Handles initial Last.fm authorization if needed."""
    session_key_file = os.path.join(
        os.path.expanduser("~"), ".yargfm_session_key"
    )

    if not os.path.exists(session_key_file):
        skg = pylast.SessionKeyGenerator(network)
        url = skg.get_web_auth_url()

        print(f"First-time setup: Please authorize YARGfm:\n{url}\n")
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

    """Load Last Scrobbled Timestamp"""
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

            """Update last_checked_timestamp here"""
            last_checked_timestamp = new_records[-1][0]

            """Save Last Scrobbled Timestamp"""
            with open(LAST_SCROBBLED_FILE, "w") as f:
                # Convert to datetime if it's a struct_time
                if isinstance(last_checked_timestamp, time.struct_time):
                    last_checked_timestamp = datetime.datetime.fromtimestamp(time.mktime(last_checked_timestamp))
                f.write(last_checked_timestamp.strftime("%Y-%m-%d %H:%M:%S"))

        time.sleep(POLLING_INTERVAL)
