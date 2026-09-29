# TwitchRecorder

A simple Python script that automatically records a Twitch channel when it goes live.

The script periodically checks the channel using the Twitch Helix API. When the channel goes live, it obtains the HLS stream playlist, selects the requested quality, and downloads the stream segments until the stream ends.

Recordings are saved as `.ts` files and are automatically remuxed to `.mp4` when `ffmpeg` is available.

## Features

* Automatically monitors a Twitch channel
* Starts recording when the channel goes live
* Supports different video qualities
* Supports audio-only streams
* Skips Twitch stitched ad segments when possible
* Saves recordings in a separate directory for each channel
* Remuxes recordings to `.mp4` without re-encoding
* Retries failed segment downloads
* Refreshes the HLS playlist URL when necessary
* Keeps track of HLS media sequence numbers to avoid downloading the same segment twice

## Requirements

* Python 3.10 or newer
* `ffmpeg` (optional, required for automatic `.mp4` output)
* A Twitch application with a Client ID and Client Secret

Python dependencies:

```text
requests
python-dotenv
```

## Installation

Clone the repository:

```bash
git clone https://github.com/smilhin/TwitchRecorder.git
cd TwitchRecorder
```

Install the Python dependencies:

```bash
pip install -r requirements.txt
```

If you want recordings to be converted to `.mp4`, install `ffmpeg` and make sure it is available in your `PATH`.

You can check it with:

```bash
ffmpeg -version
```

If `ffmpeg` is not available, the recorder will keep the original `.ts` recording instead.

## Twitch Application

The recorder uses the Twitch Helix API to check whether the channel is live.

Create a Twitch application from the Twitch Developer Console:

https://dev.twitch.tv/console

Your Twitch account must have two-factor authentication enabled in order to register an application.

When creating the application, use:

* OAuth Redirect URL: `http://localhost`
* Client Type: `Confidential`
* Category: `Application Integration` or `Other`

After creating the application, open it in the Developer Console and copy the Client ID.

Generate a Client Secret using `New Secret` and keep it private.

## Configuration

Create an `.env` file in the same folder as the script.

You can use `.env-template` as a starting point:

```env
CHANNEL_NAME=channel_name
CLIENT_ID=your_client_id
CLIENT_SECRET=your_client_secret
VIDEO_QUALITY=best
```

### Configuration options

| Variable        | Description                              |
| --------------- | ---------------------------------------- |
| `CHANNEL_NAME`  | Twitch channel to monitor                |
| `CLIENT_ID`     | Client ID of your Twitch application     |
| `CLIENT_SECRET` | Client Secret of your Twitch application |
| `VIDEO_QUALITY` | Quality to record                        |

`VIDEO_QUALITY` supports:

* `best`
* `source`
* `worst`
* `audio_only`
* A quality name such as `720p`
* A quality name such as `720p60`

`best` and `source` select the available video variant with the highest bandwidth.

`worst` selects the available video variant with the lowest bandwidth.

For a specific quality name, the recorder first tries an exact match and then a matching prefix. If the requested quality is not available, it falls back to `best`.

## Usage

Start the recorder with:

```bash
python main.py
```

The script will continue running and monitor the configured channel.

While the channel is offline, it checks the Twitch API every 30 seconds.

When the channel goes live, recording starts automatically.

Press `Ctrl+C` to stop the recorder.

## Recordings

Recordings are stored in the `recordings` directory.

The directory structure looks like this:

```text
recordings/
└── channel_name/
    └── channel_name_2026-01-01_12-30-00.mp4
```

The timestamp in the filename is the time when the recording started.

The recorder initially writes the stream to a `.ts` file.

If `ffmpeg` is available, the `.ts` file is remuxed to `.mp4` using stream copy:

```text
-c copy
```

This means the audio and video streams are not re-encoded.

The `.ts` file is removed after a successful remux.

If `ffmpeg` is unavailable or the remux fails, the `.ts` file is kept instead.

## How it works

The recording process is roughly:

```text
Twitch Helix API
       |
       v
Check if channel is live
       |
       v
Request Twitch playback access token
       |
       v
Request HLS master playlist
       |
       v
Select requested quality
       |
       v
Download new HLS segments
       |
       v
Stream ends
       |
       v
Remux .ts -> .mp4
```

The recorder uses Twitch's web player's GraphQL endpoint to obtain a playback access token and then requests the HLS playlist from Twitch's streaming infrastructure.

The HLS code parses Twitch master and media playlists, handles media sequence numbers and program date/time information, and detects Twitch ad markers.

## Ads

The recorder can skip Twitch stitched ad segments.

It identifies ad ranges using Twitch-specific HLS `DATERANGE` markers and does not download segments that fall within those ranges.

This depends on the ad markers provided by Twitch, so it is not guaranteed to detect every possible type of advertisement.

## Error handling

The recorder retries failed segment downloads up to three times.

If fetching the media playlist fails, it retries the request. After every three consecutive playlist failures, it attempts to obtain a fresh playlist URL.

After 15 consecutive playlist failures, the recorder assumes that the stream has ended.

The main Twitch API polling loop also retries API errors using an increasing delay, up to 10 minutes.

## Limitations

The recorder uses an internal GraphQL endpoint and client ID from the Twitch web player to obtain the playback access token.

This endpoint is not part of Twitch's official public API and may change without notice. Changes to Twitch's web player or streaming infrastructure may therefore break the recorder.

The recorder also depends on Twitch's HLS stream being available.

Network problems can result in missing stream segments. Failed segment downloads are retried, but segments that are no longer available cannot be recovered.

## Project structure

```text
TwitchRecorder/
├── .github/
│   └── workflows/
├── .env-template
├── .gitignore
├── LICENSE
├── README.md
├── hls.py
├── main.py
├── recorder.py
└── requirements.txt
```

### `main.py`

Monitors the configured Twitch channel using the Twitch Helix API and starts a recording when the channel goes live.

### `recorder.py`

Handles playback access tokens, HLS playlist retrieval, quality selection, segment downloading, ad skipping, error handling, and finalizing recordings.

### `hls.py`

Contains the Twitch HLS master and media playlist parser and the video quality selection logic.

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
