"""
Spotify Service — Voice-callable Spotify playback control for MAYA.
All public functions return plain spoken strings.
Gracefully handles missing credentials or unavailable Spotify.
"""
import logging
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

logger = logging.getLogger("AI_Companion")

# Store OAuth cache next to this file so it's found regardless of cwd
_CACHE_PATH = str(Path(__file__).parent / ".spotify_token_cache")
# ISO country of the Spotify account, e.g. NG; searches return only tracks playable there
_MARKET = os.getenv("SPOTIFY_MARKET") or None

try:
    import spotipy
    from spotipy.oauth2 import SpotifyOAuth
    _SPOTIPY_AVAILABLE = True
except ImportError:
    _SPOTIPY_AVAILABLE = False

CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
REDIRECT_URI = os.getenv("SPOTIPY_REDIRECT_URI", "http://127.0.0.1:8888/callback")

# Lazy singleton — only created on first use
_sp = None
SPOTIFY_AVAILABLE = False


def _get_sp():
    """Return authenticated Spotify client, or None if unavailable."""
    global _sp, SPOTIFY_AVAILABLE
    if _sp is not None:
        return _sp
    if not _SPOTIPY_AVAILABLE or not CLIENT_ID or not CLIENT_SECRET:
        return None
    try:
        scope = (
            "user-read-playback-state "
            "user-modify-playback-state "
            "user-read-currently-playing"
        )
        _sp = spotipy.Spotify(
            auth_manager=SpotifyOAuth(
                client_id=CLIENT_ID,
                client_secret=CLIENT_SECRET,
                redirect_uri=REDIRECT_URI,
                scope=scope,
                cache_path=_CACHE_PATH,
                open_browser=True,
            )
        )
        SPOTIFY_AVAILABLE = True
        return _sp
    except Exception as e:
        logger.warning(f"[SPOTIFY] Init failed: {e}")
        return None


def _not_available() -> str:
    if not _SPOTIPY_AVAILABLE:
        return "The spotipy library is not installed. Run pip install spotipy to enable Spotify."
    if not CLIENT_ID or not CLIENT_SECRET:
        return "Spotify is not configured. Please add SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET to your .env file."
    return "Spotify is not available right now."


def _launch_spotify_and_wait() -> bool:
    """
    Attempt to open the Spotify desktop app, then wait up to 12 s for a
    device to become visible via the Spotify API.
    Returns True if a device appeared, False otherwise.
    """
    import subprocess, time, sys

    launched = False
    # Try the Spotify URI scheme first (works on Windows/macOS/Linux)
    try:
        if sys.platform.startswith("win"):
            # os.startfile is the most reliable way to open a URI on Windows
            import os as _os
            _os.startfile("spotify:")
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "spotify:"])
        else:
            subprocess.Popen(["xdg-open", "spotify:"])
        launched = True
        logger.info("[SPOTIFY] Sent open command for Spotify app")
    except Exception as e:
        logger.warning(f"[SPOTIFY] Could not launch Spotify via URI: {e}")

    if not launched:
        return False

    # Poll for up to 9 s (Spotify typically registers within 5–8 s)
    sp = _get_sp()
    for _ in range(6):
        time.sleep(1.5)
        try:
            devices = sp.devices().get("devices", [])
            if devices:
                logger.info(f"[SPOTIFY] Device appeared after launch: {[d['name'] for d in devices]}")
                return True
        except Exception:
            pass
    return False


# Hints that refer to a remote device we cannot launch automatically
_REMOTE_HINTS = {"phone", "mobile", "android", "iphone", "smartphone"}


# Maps user hints to Spotify device type strings
_DEVICE_TYPE_HINTS = {
    "phone": "smartphone",
    "mobile": "smartphone",
    "android": "smartphone",
    "iphone": "smartphone",
    "pc": "computer",
    "computer": "computer",
    "laptop": "computer",
    "desktop": "computer",
    "windows": "computer",
    "mac": "computer",
}


def _get_device_id(device_hint=None):
    sp = _get_sp()
    if sp is None:
        return None
    try:
        devices = sp.devices().get("devices", [])
        if devices:
            names = [f"{d['name']} ({d.get('type','?')})" for d in devices]
            logger.info(f"[SPOTIFY] Available devices: {names}")
        else:
            logger.warning("[SPOTIFY] No devices returned from Spotify API")
            return None

        # If a hint was given, first try to match by device type
        if device_hint:
            target_type = _DEVICE_TYPE_HINTS.get(device_hint.lower())
            if target_type:
                # Prefer active device of that type, then any device of that type
                for d in devices:
                    if d.get("type", "").lower() == target_type and d.get("is_active"):
                        return d["id"]
                for d in devices:
                    if d.get("type", "").lower() == target_type:
                        return d["id"]
            # Fallback: try matching hint against device name
            for d in devices:
                if device_hint.lower() in d["name"].lower():
                    return d["id"]

        # No hint or no match — prefer active device, otherwise use first available
        for d in devices:
            if d.get("is_active"):
                return d["id"]
        return devices[0]["id"]
    except Exception as e:
        logger.error(f"[SPOTIFY] device detection error: {e}")
        return None


# ------------------------------------------------------------------ #
# Voice-callable playback functions
# ------------------------------------------------------------------ #

def _best_matches(query: str, tracks: list) -> list:
    """Order search results by how well title and artists match the request.
    Spotify's ranking with limit=1 can put a different song first
    ("Essence Wizkid" -> "MMS" by Asake)."""
    import re as _re
    words = set(_re.findall(r"[a-z0-9]+", query.lower()))

    def score(t):
        title = set(_re.findall(r"[a-z0-9]+", t["name"].lower()))
        artists = set(_re.findall(r"[a-z0-9]+", " ".join(a["name"] for a in t["artists"]).lower()))
        return (len(words & title) * 2 + len(words & artists), t.get("popularity", 0))

    return sorted(tracks, key=score, reverse=True)


def play_music(query: str, device_hint: str = None) -> str:
    """
    Play a song, artist, or playlist by name.
    device_hint: optional string like 'phone', 'pc', 'laptop', 'computer' to target a device.
    Tries tracks first, then playlists.
    """
    sp = _get_sp()
    if sp is None:
        return _not_available()

    try:
        # Search first (doesn't need a device)
        # Without a market, Spotify's top result can be a release that is not
        # playable in the listener's country; playback then fails silently.
        results = sp.search(q=query, type="track", limit=10, market=_MARKET)
        tracks = _best_matches(query, results.get("tracks", {}).get("items", []))

        playlist_fallback = None
        if not tracks:
            results = sp.search(q=query, type="playlist", limit=1, market=_MARKET)
            items = results.get("playlists", {}).get("items", [])
            if items:
                playlist_fallback = items[0]

        if not tracks and not playlist_fallback:
            return f"I could not find anything on Spotify matching '{query}'."

        device_id = _get_device_id(device_hint)
        if device_id is None:
            is_remote = device_hint and device_hint.lower() in _REMOTE_HINTS
            if is_remote:
                return (
                    "I found the song but Spotify isn't open on your phone. "
                    "Please open the Spotify app on your phone and ask me again."
                )
            logger.info("[SPOTIFY] No device found — attempting to launch Spotify automatically")
            appeared = _launch_spotify_and_wait()
            if appeared:
                device_id = _get_device_id(device_hint)
            if device_id is None:
                return (
                    "I found the song but Spotify isn't open on any device. "
                    "I tried to launch it but it didn't respond in time. "
                    "Please open Spotify on your PC and ask me again."
                )

        def _try_play(fn):
            """Try playback, if 403/not-active try transfer first then retry."""
            try:
                fn()
                return True
            except Exception as e1:
                logger.warning(f"[SPOTIFY] first play attempt failed ({e1}), trying transfer")
                try:
                    import time
                    sp.transfer_playback(device_id=device_id, force_play=False)
                    time.sleep(0.8)
                    fn()
                    return True
                except Exception as e2:
                    logger.error(f"[SPOTIFY] play after transfer failed: {e2}")
                    return False

        if tracks:
            track = tracks[0]
            name = track["name"]
            artist = track["artists"][0]["name"]
            uri = track["uri"]
            # Start the track inside its album: on some desktop clients a bare
            # track list is accepted (204) but never loads, while an album
            # context with an offset plays reliably.
            album_uri = track.get("album", {}).get("uri")
            if album_uri:
                ok = _try_play(lambda: sp.start_playback(device_id=device_id, context_uri=album_uri, offset={"uri": uri}))
            else:
                ok = _try_play(lambda: sp.start_playback(device_id=device_id, uris=[uri]))
            if ok:
                return f"Now playing {name} by {artist}."
            return f"I found {name} by {artist} but could not start playback. Try pressing play in Spotify manually first."

        pl = playlist_fallback
        ok = _try_play(lambda: sp.start_playback(device_id=device_id, context_uri=pl["uri"]))
        if ok:
            return f"Now playing playlist: {pl['name']}."
        return f"I found the playlist {pl['name']} but could not start playback."

    except Exception as e:
        logger.error(f"[SPOTIFY] play_music error: {e}")
        return "I ran into an issue playing that on Spotify. Make sure Spotify is open on a device."


def play_artist_music(artist: str, device_hint: str = None) -> str:
    """Play music by a specific artist."""
    sp = _get_sp()
    if sp is None:
        return _not_available()
    try:
        device_id = _get_device_id(device_hint)
        if device_id is None:
            is_remote = device_hint and device_hint.lower() in _REMOTE_HINTS
            if is_remote:
                return (
                    "Spotify isn't open on your phone. "
                    "Please open the Spotify app on your phone and ask me again."
                )
            logger.info("[SPOTIFY] No device found — attempting to launch Spotify automatically")
            appeared = _launch_spotify_and_wait()
            if appeared:
                device_id = _get_device_id(device_hint)
            if device_id is None:
                return "No active Spotify device found. I tried to launch it but it didn't respond. Please open Spotify and try again."
        results = sp.search(q=artist, type="artist", limit=1, market=_MARKET)
        artists = results.get("artists", {}).get("items", [])
        if not artists:
            return f"I could not find the artist {artist} on Spotify."
        a = artists[0]
        sp.start_playback(device_id=device_id, context_uri=a["uri"])
        return f"Now playing music by {a['name']}."
    except Exception as e:
        logger.error(f"[SPOTIFY] play_artist error: {e}")
        return f"I could not play {artist} right now."


def pause_music() -> str:
    """Pause Spotify playback."""
    sp = _get_sp()
    if sp is None:
        return _not_available()
    try:
        sp.pause_playback()
        return "Music paused."
    except Exception:
        return "I could not pause the music. Spotify may not be playing anything."


def resume_music() -> str:
    """Resume Spotify playback."""
    sp = _get_sp()
    if sp is None:
        return _not_available()
    try:
        sp.start_playback()
        return "Music resumed."
    except Exception:
        return "I could not resume the music."


def next_track() -> str:
    """Skip to the next track."""
    sp = _get_sp()
    if sp is None:
        return _not_available()
    try:
        sp.next_track()
        return "Skipping to the next track."
    except Exception:
        return "I could not skip the track right now."


def previous_track() -> str:
    """Go back to the previous track."""
    sp = _get_sp()
    if sp is None:
        return _not_available()
    try:
        sp.previous_track()
        return "Going back to the previous track."
    except Exception:
        return "I could not go back to the previous track."


def set_volume(percent: int) -> str:
    """Set Spotify playback volume (0-100)."""
    sp = _get_sp()
    if sp is None:
        return _not_available()
    try:
        percent = max(0, min(100, int(percent)))
        device_id = _get_device_id()
        sp.volume(percent, device_id=device_id)
        return f"Volume set to {percent} percent."
    except Exception:
        return "I could not change the volume right now."


def get_now_playing() -> str:
    """Return what is currently playing on Spotify."""
    sp = _get_sp()
    if sp is None:
        return _not_available()
    try:
        current = sp.current_playback()
        if current is None or not current.get("is_playing"):
            return "Nothing is currently playing on Spotify."
        item = current.get("item")
        if item:
            name = item["name"]
            artist = item["artists"][0]["name"]
            return f"Currently playing {name} by {artist}."
        return "Something is playing on Spotify but I could not get the track details."
    except Exception:
        return "I could not check what is playing on Spotify right now."


def get_now_playing_structured() -> dict:
    """Return structured info about the currently playing track (for lyrics lookup)."""
    sp = _get_sp()
    if sp is None:
        return {"is_playing": False}
    try:
        current = sp.current_playback()
        if not current or not current.get("is_playing"):
            return {"is_playing": False}
        item = current.get("item")
        if item:
            return {
                "is_playing":  True,
                "track":       item["name"],
                "artist":      item["artists"][0]["name"],
                "progress_ms": current.get("progress_ms", 0),
                "duration_ms": item.get("duration_ms", 0),
            }
    except Exception:
        pass
    return {"is_playing": False}


def close_spotify() -> str:
    """Pause playback then close/quit the Spotify desktop app."""
    import subprocess as _sp
    import sys as _sys
    # Pause playback first so it doesn't resume on next open
    sp = _get_sp()
    if sp:
        try:
            sp.pause_playback()
        except Exception:
            pass
    # Kill the desktop process
    try:
        if _sys.platform.startswith("win"):
            result = _sp.run(
                ["taskkill", "/f", "/im", "Spotify.exe"],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                return "Spotify has been closed."
            else:
                return "Music paused. Spotify desktop app wasn't running or could not be closed."
        elif _sys.platform == "darwin":
            _sp.run(["osascript", "-e", 'quit app "Spotify"'], capture_output=True)
            return "Spotify has been closed."
        else:
            _sp.run(["pkill", "-x", "spotify"], capture_output=True)
            return "Spotify has been closed."
    except Exception as e:
        logger.error(f"[SPOTIFY] close error: {e}")
        return "Music paused but I could not close the Spotify app."


# ---------------------------------------------------------------------------
# Legacy compatibility aliases (used by old main.py pipeline)
# ---------------------------------------------------------------------------
def play_song(query: str, device=None) -> bool:
    """Legacy wrapper — returns True/False for old pipeline."""
    result = play_music(query)
    return not result.startswith("I could not") and not result.startswith("No active")


def play_artist(query: str, device=None) -> bool:
    """Legacy wrapper."""
    result = play_artist_music(query)
    return not result.startswith("I could not") and not result.startswith("No active")
