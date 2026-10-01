import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from urllib.parse import urljoin

ATTR_RE = re.compile(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)')


def parse_attributes(text: str) -> dict[str, str]:
    return {key: value.strip('"') for key, value in ATTR_RE.findall(text)}


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _clean_lines(text: str) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines or lines[0] != "#EXTM3U":
        raise ValueError("not an m3u8 playlist (missing #EXTM3U)")
    return lines


@dataclass
class Variant:
    name: str
    bandwidth: int
    resolution: str
    frame_rate: float
    url: str


def parse_master(text: str, base_url: str = "") -> list[Variant]:
    group_names: dict[str, str] = {}
    variants: list[Variant] = []
    pending: dict[str, str] | None = None

    for line in _clean_lines(text):
        if line.startswith("#EXT-X-MEDIA:"):
            attrs = parse_attributes(line.split(":", 1)[1])
            if attrs.get("TYPE") == "VIDEO":
                group_id = attrs.get("GROUP-ID", "")
                group_names[group_id] = attrs.get("NAME", group_id)
        elif line.startswith("#EXT-X-STREAM-INF:"):
            pending = parse_attributes(line.split(":", 1)[1])
        elif not line.startswith("#") and pending is not None:
            group_id = pending.get("VIDEO", "")
            variants.append(
                Variant(
                    name=group_names.get(
                        group_id, group_id or pending.get("RESOLUTION", "unknown")
                    ),
                    bandwidth=int(pending.get("BANDWIDTH", 0)),
                    resolution=pending.get("RESOLUTION", ""),
                    frame_rate=float(pending.get("FRAME-RATE") or 0),
                    url=urljoin(base_url, line),
                )
            )
            pending = None

    return variants


def _is_audio_only(variant: Variant) -> bool:
    return "audio_only" in variant.name.lower()


def select_variant(variants: list[Variant], quality: str) -> Variant | None:
    """
    quality: "best" / "source", "worst", "audio_only", or a name like "720p60" / "720p".
    Returns None if an explicit name matches nothing (caller decides on a fallback).
    """
    if not variants:
        return None

    video = [v for v in variants if not _is_audio_only(v)] or variants
    q = quality.strip().lower()

    if q in ("", "best", "source"):
        return max(video, key=lambda v: v.bandwidth)
    if q == "worst":
        return min(video, key=lambda v: v.bandwidth)

    def base_name(v: Variant) -> str:
        return v.name.lower().replace("(source)", "").strip()

    for v in variants:
        if base_name(v) == q:
            return v
    prefix = [v for v in variants if base_name(v).startswith(q)]
    return max(prefix, key=lambda v: v.bandwidth) if prefix else None


@dataclass
class Segment:
    sequence: int
    url: str
    duration: float
    start_time: datetime | None = None
    is_ad: bool = False
    init_url: str | None = None


@dataclass
class MediaPlaylist:
    media_sequence: int
    target_duration: float
    segments: list[Segment] = field(default_factory=list)
    ended: bool = False


def is_ad_daterange(attrs: dict[str, str]) -> bool:
    return (
        attrs.get("CLASS") == "twitch-stitched-ad"
        or attrs.get("ID", "").startswith("stitched-ad")
        or any(key.startswith("X-TV-TWITCH-AD-") for key in attrs)
    )


def parse_media(text: str, base_url: str = "") -> MediaPlaylist:
    playlist = MediaPlaylist(media_sequence=0, target_duration=2.0)
    ad_ranges: list[tuple[datetime, datetime]] = []

    pending_duration: float | None = None
    pending_time: datetime | None = None
    next_time: datetime | None = None
    init_url: str | None = None

    for line in _clean_lines(text):
        if line.startswith("#EXT-X-MEDIA-SEQUENCE:"):
            playlist.media_sequence = int(line.split(":", 1)[1])
        elif line.startswith("#EXT-X-TARGETDURATION:"):
            playlist.target_duration = float(line.split(":", 1)[1])
        elif line.startswith("#EXT-X-ENDLIST"):
            playlist.ended = True
        elif line.startswith("#EXT-X-PROGRAM-DATE-TIME:"):
            pending_time = parse_time(line.split(":", 1)[1])
        elif line.startswith("#EXT-X-MAP:"):
            attrs = parse_attributes(line.split(":", 1)[1])
            if "URI" in attrs:
                init_url = urljoin(base_url, attrs["URI"])
        elif line.startswith("#EXT-X-DATERANGE:"):
            attrs = parse_attributes(line.split(":", 1)[1])
            if is_ad_daterange(attrs) and "START-DATE" in attrs:
                start = parse_time(attrs["START-DATE"])
                duration = float(
                    attrs.get("DURATION") or attrs.get("PLANNED-DURATION") or 0
                )
                ad_ranges.append((start, start + timedelta(seconds=duration)))
        elif line.startswith("#EXTINF:"):
            pending_duration = float(line[len("#EXTINF:") :].split(",", 1)[0])
        elif not line.startswith("#"):
            if pending_duration is None:
                continue
            start_time = pending_time or next_time
            playlist.segments.append(
                Segment(
                    sequence=playlist.media_sequence + len(playlist.segments),
                    url=urljoin(base_url, line),
                    duration=pending_duration,
                    start_time=start_time,
                    init_url=init_url,
                )
            )
            next_time = (
                start_time + timedelta(seconds=pending_duration) if start_time else None
            )
            pending_duration = None
            pending_time = None

    for seg in playlist.segments:
        if seg.start_time and any(
            start <= seg.start_time < end for start, end in ad_ranges
        ):
            seg.is_ad = True

    return playlist
