# TwitchRecorder

A small Python script that automatically records a Twitch channel when it goes live.

The script periodically checks the channel using the Twitch Helix API. When the channel goes live, it obtains the HLS stream playlist, selects the requested quality, and starts downloading the stream segments until the stream ends.

Recordings are saved locally and are converted from `.ts` to `.mp4` by default.

## Features

* Automatically waits for a Twitch channel to go live
* Records the stream until it ends
* Supports different video qualities
* Can skip Twitch stitched ad segments
* Saves recordings in separate folders for each channel
* Remuxes recordings to `.mp4` without re-encoding
* Handles temporary API and playlist failures
* Keeps track of HLS segments to avoid downloading the same segment twice

## Requirements

* Python 3.9 or newer
* `ffmpeg`
* A Twitch application with a Client ID and Client Secret

The Python dependencies are:

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

Make sure `ffmpeg` is installed and available in your `PATH`.

You can check it with:

```bash
ffmpeg -version
```

## Twitch Application

The recorder uses the Twitch API to check whether the channel is live, so you need to create a Twitch application.

Go to:

https://dev.twitch.tv/console

Log in with your Twitch account and create a new application.

Use the following settings:

* OAuth Redirect URL: `http://localhost`
* Client Type: `Confidential`
* Category: `Application Integration` or `Other`

After creating the application, open it and copy the Client ID. Generate a Client Secret as well.

Keep the Client Secret private.

## Configuration

Create a `.env` file in the project directory.

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

If the requested quality is not available, the recorder falls back to the best available quality.

## Usage

Start the recorder with:

```bash
python main.py
```

The script will keep running and check the configured channel periodically.

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

By default, the recorder first writes a `.ts` file and then remuxes it to `.mp4` using `ffmpeg`.

The remux uses stream copy, so the video and audio are not re-encoded.

If `ffmpeg` is unavailable or the remux fails, the `.ts` file is kept instead.

## Ads

The recorder detects Twitch stitched ad segments and skips them by default.

This is based on the ad markers present in the HLS playlist. It is not a guarantee that every type of advertisement will always be detected or removed.

## Limitations

This project relies partly on Twitch's internal web-player GraphQL endpoint to obtain the playback access token.

That endpoint is not part of Twitch's official public API and can change without notice. If Twitch changes its web player or HLS infrastructure, the recorder may stop working until the implementation is updated.

The recorder also depends on the stream being available as an HLS stream.

Network interruptions can result in missing segments. The recorder retries failed segment downloads, but it cannot recover segments that are no longer available from Twitch.

## Project structure

```text
TwitchRecorder/
├── main.py
├── recorder.py
├── hls.py
├── requirements.txt
├── .env-template
├── .gitignore
└── LICENSE
```

### `main.py`

Monitors the configured Twitch channel and starts the recorder when the channel goes live.

### `recorder.py`

Handles playback access tokens, HLS playlist retrieval, segment downloading, ad skipping, and finalizing recordings.

### `hls.py`

Contains the HLS playlist parser and video quality selection logic.

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
