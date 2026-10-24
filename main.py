import logging
import os
import sys
import time
import threading

import requests
from dotenv import load_dotenv

import recorder

print("""
    IMPORTANT:
    In order to use this instrument you have to do following steps:

    Create an .env file IN THE SAME FOLDER AS THE SCRIPT with following information (you will also find the template in the .env-template file on GitHub):
    CHANNEL_NAMES=channel_name1,channel_name2,...
    CLIENT_ID=client_id...
    CLIENT_SECRET=client_secret...
    VIDEO_QUALITY=...   (best, worst, source, audio_only, or a name like 720p60)

    Go to https://dev.twitch.tv/console and log in with your Twitch account 
    (Twitch requires 2FA to be enabled on the account to register apps).

    Click Register Your Application.

    Give it any name, set the OAuth Redirect URL to http://localhost (the field is required),
    choose a category such as "Application Integration" or "Other", and set the client type to Confidential.

    After creating it, open Manage. You'll see the Client ID, and you can click New Secret to generate the Client Secret. 
    Save the secret right away, because it's only shown once.
    """)

if not load_dotenv():
    print(
        "\033[31mNo env file detected. Please follow the instructions and create one WITH VALID CREDENTIALS\033[0m"
    )
    sys.exit(1)

# Global Constants
POLL_INTERVAL = 30  # seconds

CHANNEL_NAMES = [str for str in os.getenv("CHANNEL_NAMES").replace(" ", "").split(",") if str]
if not CHANNEL_NAMES:
    print(
        "\033[31mNo channel names detected >~<. Please follow the instructions and create one WITH VALID CREDENTIALS\033[0m"
    )
    sys.exit(1)
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
VIDEO_QUALITY = os.getenv("VIDEO_QUALITY", "best")


class TwitchAPI:
    def __init__(self, channel_name, client_id, client_secret):
        self.channel_name = channel_name
        self.client_id = client_id
        self.client_secret = client_secret
        self._token = None
        self._expires_at = 0.0

    def _get_token(self):
        if self._token and time.time() < self._expires_at - 60:
            return self._token
        r = requests.post(
            "https://id.twitch.tv/oauth2/token",
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "client_credentials",
            },
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        self._token = data["access_token"]
        self._expires_at = time.time() + data["expires_in"]
        return self._token

    def get_stream(self):
        """Return stream info (dict) if the channel is live, else None."""
        for attempt in range(2):
            r = requests.get(
                "https://api.twitch.tv/helix/streams",
                params={"user_login": self.channel_name},
                headers={
                    "Client-ID": self.client_id,
                    "Authorization": f"Bearer {self._get_token()}",
                },
                timeout=10,
            )
            if r.status_code == 401 and attempt == 0:
                self._token = None
                continue
            r.raise_for_status()
            data = r.json()["data"]
            return data[0] if data else None
        return None

stop = threading.Event()

def on_live(stream, channel_name: str, output_dir: str = "recordings"):
    """
    Called when the channel is live. Blocks until the recording is finished,
    then returns so the main loop can start listening again.

    `stream` has keys such as: title, game_name, started_at, viewer_count.
    """
    print(f"{channel_name} is live: {stream['title']} (since {stream['started_at']})")
    recorder.record_stream(channel_name, output_dir=output_dir, quality=VIDEO_QUALITY, stop_event=stop)

def loop(api: TwitchAPI, output_dir: str):
    errors = 0
    while not stop.is_set():
        try:
            stream = api.get_stream()
            errors = 0
        except requests.RequestException as e:
            errors += 1
            delay = min(POLL_INTERVAL * 2**errors, 600)
            print(f"API error: {e}. Retrying in {delay}s")
            stop.wait(delay)
            continue

        if stream:
            on_live(stream, api.channel_name, output_dir)
            stop.wait(10)
        else:
            stop.wait(POLL_INTERVAL)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    output_dir = input("Enter output directory (default: directory of the executable): ") or "recordings"

    print("Listening... :3")
    threads = []
    for channel_name in CHANNEL_NAMES:
        api = TwitchAPI(channel_name, CLIENT_ID, CLIENT_SECRET)
        threads.append(threading.Thread(target=loop, args=(api, output_dir)))
        print(f"Streamer: {channel_name}")


    for thread in threads:
        thread.start()

    try:
        for t in threads:
            t.join()
    except KeyboardInterrupt:
        print("Stopping, finishing recordings...")
        stop.set()
        for t in threads:
            t.join()
        sys.exit(0)


if __name__ == "__main__":
        main()
