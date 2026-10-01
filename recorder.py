"""
Twitch live recorder: token -> master playlist -> pick quality -> download segments.

Flow:
  1. Ask Twitch's GQL endpoint for a playback access token (token + signature).
  2. Request the master playlist from usher.ttvnw.net with that token.
  3. Parse it, pick a quality, get the URL of that quality's media playlist.
  4. Loop: re-fetch the media playlist, download every segment we haven't seen
     yet, append it to one .mp4frag file. Stop when the stream ends.

NOTE: the GQL endpoint and its client ID are Twitch's own web player internals,
not an official API. They can change without notice.
"""

import logging
import random
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

import requests

import hls
from hls import Variant

log = logging.getLogger("recorder")

GQL_URL = "https://gql.twitch.tv/gql"
GQL_CLIENT_ID = (
    "kimne78kx3ncx6brgo4mv6wki5h1ko"  # public client ID of the Twitch web player :)
)
USHER_URL = "https://usher.ttvnw.net/api/channel/hls/{channel}.m3u8"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0"

GQL_QUERY = """
query PlaybackAccessToken_Template($login: String!, $isLive: Boolean!, $vodID: ID!, $isVod: Boolean!, $playerType: String!) {
  streamPlaybackAccessToken(channelName: $login, params: {platform: "web", playerBackend: "mediaplayer", playerType: $playerType}) @include(if: $isLive) {
    value
    signature
    __typename
  }
  videoPlaybackAccessToken(id: $vodID, params: {platform: "web", playerBackend: "mediaplayer", playerType: $playerType}) @include(if: $isVod) {
    value
    signature
    __typename
  }
}
"""

MAX_PLAYLIST_FAILURES = (
    15  # consecutive failed playlist fetches before the app gives up
)


class StreamOffline(Exception):
    """The channel is not live (usher returned 404)."""


class AccessTokenError(Exception):
    """Twitch did not hand out a playback access token."""


def get_access_token(session: requests.Session, channel: str) -> tuple[str, str]:
    payload = {
        "operationName": "PlaybackAccessToken_Template",
        "query": GQL_QUERY,
        "variables": {
            "isLive": True,
            "login": channel,
            "isVod": False,
            "vodID": "",
            "playerType": "site",
        },
    }
    r = session.post(
        GQL_URL,
        json=payload,
        headers={"Client-ID": GQL_CLIENT_ID},
        timeout=10,
    )
    r.raise_for_status()
    body = r.json()
    if isinstance(body, list):
        body = body[0]
    token = (body.get("data") or {}).get("streamPlaybackAccessToken")
    if not token:
        raise AccessTokenError(
            f"no access token in response: {body.get('errors') or body}"
        )
    return token["value"], token["signature"]


def get_master_playlist(session: requests.Session, channel: str) -> tuple[str, str]:
    """Returns (playlist_text, final_url). Raises StreamOffline on 404."""
    token, signature = get_access_token(session, channel)
    r = session.get(
        USHER_URL.format(channel=channel),
        params={
            "sig": signature,
            "token": token,
            "allow_source": "true",
            "allow_audio_only": "true",
            "fast_bread": "true",
            "playlist_include_framerate": "true",
            "player_backend": "mediaplayer",
            "supported_codecs": "h264",
            "type": "any",
            "p": random.randint(0, 999999),
        },
        timeout=10,
    )
    if r.status_code == 404:
        raise StreamOffline(channel)
    r.raise_for_status()
    return r.text, r.url


def resolve_variant(
    session: requests.Session, channel: str, quality: str
) -> Variant | None:
    text, url = get_master_playlist(session, channel)
    variants = hls.parse_master(text, url)
    if not variants:
        raise ValueError("master playlist contains no variants")

    variant = hls.select_variant(variants, quality)
    if variant is None:
        available = ", ".join(v.name for v in variants)
        log.warning(
            "Quality '%s' not available (have: %s), using best", quality, available
        )
        variant = hls.select_variant(variants, "best")
    return variant


def download_segment(
    session: requests.Session, url: str, out, retries: int = 3
) -> bool:
    for attempt in range(1, retries + 1):
        try:
            r = session.get(url, timeout=10)
            r.raise_for_status()
            out.write(r.content)
            out.flush()
            return True
        except requests.RequestException as e:
            log.warning("Segment download failed (%d/%d): %s", attempt, retries, e)
            time.sleep(0.5 * attempt)
    return False


def finalize(mp4frag_path: Path, remux: bool, keep_mp4frag: bool) -> Path | None:
    """Delete empty recordings, optionally remux .mp4frag -> .mp4 (stream copy, no re-encode)."""
    if not mp4frag_path.exists():
        return None
    if mp4frag_path.stat().st_size == 0:
        mp4frag_path.unlink()
        return None
    if not remux:
        return mp4frag_path
    if not shutil.which("ffmpeg"):
        log.warning("ffmpeg not found, keeping %s", mp4frag_path.name)
        return mp4frag_path

    mp4_path = mp4frag_path.with_suffix(".mp4")
    log.info("Remuxing to %s", mp4_path.name)
    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-dts_delta_threshold",
            "1",
            "-i",
            str(mp4frag_path),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(mp4_path),
        ],
        check=False,
    )
    if result.returncode != 0:
        log.warning("Remux failed, keeping %s", mp4frag_path.name)
        mp4_path.unlink(missing_ok=True)
        return mp4frag_path
    if not keep_mp4frag:
        mp4frag_path.unlink()
    return mp4_path


def record_stream(
    channel: str,
    quality: str = "best",
    output_dir: str | Path = "recordings",
    skip_ads: bool = True,
    remux: bool = True,
    keep_mp4frag: bool = False,
) -> Path | None:
    """
    Record a live channel until the stream ends. Blocks. Returns the output path,
    or None if nothing was recorded.
    """
    channel = channel.lower()
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    try:
        variant = resolve_variant(session, channel, quality)
    except StreamOffline:
        log.info("%s is offline", channel)
        return None
    except (requests.RequestException, AccessTokenError, ValueError) as e:
        log.error("Could not start recording: %s", e)
        return None

    folder = Path(output_dir) / channel
    folder.mkdir(parents=True, exist_ok=True)
    mp4frag_path = folder / f"{channel}_{datetime.now():%Y-%m-%d_%H-%M-%S}.mp4frag"  # noqa
    log.info(
        "Recording %s [%s, %s] -> %s",
        channel,
        variant.name,
        variant.resolution or "audio",
        mp4frag_path,
    )

    playlist_url = variant.url
    last_seq = -1
    failures = 0
    in_ad = False
    written_init_url: str | None = None
    saved = skipped_ads = lost = 0

    try:
        with open(mp4frag_path, "wb") as out:
            while True:
                try:
                    r = session.get(playlist_url, timeout=10)
                    r.raise_for_status()
                    playlist = hls.parse_media(r.text, playlist_url)
                    failures = 0
                except (requests.RequestException, ValueError) as e:
                    failures += 1
                    log.warning(
                        "Playlist fetch failed (%d/%d): %s",
                        failures,
                        MAX_PLAYLIST_FAILURES,
                        e,
                    )
                    if failures >= MAX_PLAYLIST_FAILURES:
                        log.info("Giving up, assuming the stream ended")
                        break
                    if failures % 3 == 0:
                        try:
                            playlist_url = resolve_variant(
                                session, channel, quality
                            ).url
                            log.info("Got a fresh playlist URL")
                        except StreamOffline:
                            log.info("%s went offline", channel)
                            break
                        except (
                            requests.RequestException,
                            AccessTokenError,
                            ValueError,
                        ) as e2:
                            log.warning("Could not refresh playlist URL: %s", e2)
                    time.sleep(1)
                    continue

                if playlist.segments and playlist.segments[-1].sequence < last_seq:
                    log.info("Segment numbering reset, resyncing")
                    last_seq = playlist.media_sequence - 1

                for seg in playlist.segments:
                    if seg.sequence <= last_seq:
                        continue
                    if last_seq != -1 and seg.sequence > last_seq + 1:
                        lost += seg.sequence - last_seq - 1
                        log.warning(
                            "Missed %d segment(s), fell behind the live edge",
                            seg.sequence - last_seq - 1,
                        )
                    last_seq = seg.sequence

                    if seg.is_ad and skip_ads:
                        if not in_ad:
                            log.info("Ad break started, skipping ad segments")
                            in_ad = True
                        skipped_ads += 1
                        continue
                    if in_ad:
                        log.info("Ad break over")
                        in_ad = False

                    if seg.init_url and seg.init_url != written_init_url:
                        if download_segment(session, seg.init_url, out):
                            written_init_url = seg.init_url
                        else:
                            lost += 1
                            log.warning(
                                "Could not fetch init segment, skipping segment %d",
                                seg.sequence,
                            )
                            continue

                    if download_segment(session, seg.url, out):
                        saved += 1
                    else:
                        lost += 1
                        log.warning("Lost segment %d", seg.sequence)

                if playlist.ended:
                    log.info("Stream ended (#EXT-X-ENDLIST)")
                    break

                time.sleep(min(max(playlist.target_duration / 2, 0.5), 2.0))
    finally:
        log.info(
            "Done: %d segments saved, %d ad segments skipped, %d lost",
            saved,
            skipped_ads,
            lost,
        )
        result = finalize(mp4frag_path, remux, keep_mp4frag)
        if result:
            log.info("Saved %s", result)

    return result
