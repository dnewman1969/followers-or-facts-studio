"""Signing in to your YouTube channel (free YouTube Data API), for Settings and the Upload step.

One-time setup (docs/YOUTUBE.md): make a free Google Cloud project, turn on YouTube Data API v3,
make an OAuth client of type "Desktop app", download its JSON, then in Settings → YouTube press
"Choose client file" and "Sign in". The sign-in is saved in the data folder; nothing is sent
anywhere except to Google.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from .config import Paths, save_settings, settings
from .util import StageError

# upload + manage (thumbnails, captions, reading your channel name)
SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube.force-ssl"]


def token_path() -> Path:
    return Paths().root / "youtube-token.json"


def account_path() -> Path:
    return Paths().root / "youtube-account.json"


def client_file() -> Path | None:
    p = settings()["youtube"]["client_secrets"]
    return Path(p) if p and Path(p).exists() else None


def use_client_file(src: str | Path) -> Path:
    """Check the Google OAuth client JSON and keep a copy in the data folder."""
    src = Path(src)
    try:
        data = json.loads(src.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise StageError(f"That file couldn't be read as a Google client file: {exc}")
    if "installed" not in data:
        kind = next(iter(data), "unknown")
        raise StageError("That's not a Desktop app client file. In Google Cloud, create an OAuth client of "
                         f"type 'Desktop app' and download its JSON (this one is '{kind}').")
    dest = Paths().root / "youtube-client.json"
    if src.resolve() != dest.resolve():
        shutil.copy2(src, dest)
    cfg = settings()
    cfg["youtube"]["client_secrets"] = str(dest)
    save_settings(cfg)
    return dest


def _libs():
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError:
        raise StageError("YouTube upload needs two free packages. Run Update Studio.cmd (it installs them), "
                         "or: .venv\\Scripts\\pip install google-api-python-client google-auth-oauthlib")
    return Request, Credentials, InstalledAppFlow, build


def credentials(interactive: bool = True):
    """Saved sign-in, refreshed if needed. If there isn't one (or it expired) and interactive is True,
    opens the browser to sign in."""
    Request, Credentials, InstalledAppFlow, _ = _libs()
    token = token_path()
    creds = Credentials.from_authorized_user_file(str(token), SCOPES) if token.exists() else None
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            token.write_text(creds.to_json(), encoding="utf-8")
            return creds
        except Exception:  # noqa: BLE001 - e.g. a 7-day "Testing" sign-in ran out: sign in again
            creds = None
    if not interactive:
        return None
    secrets = client_file()
    if not secrets:
        raise StageError("Choose your Google client file first: Settings → YouTube → Choose client file. "
                         "docs/YOUTUBE.md explains how to make one (free, about 10 minutes).")
    flow = InstalledAppFlow.from_client_secrets_file(str(secrets), SCOPES)
    creds = flow.run_local_server(port=0, open_browser=True, prompt="consent", access_type="offline",
                                  authorization_prompt_message="",
                                  success_message="Signed in. You can close this tab and go back to the Studio.")
    token.write_text(creds.to_json(), encoding="utf-8")
    return creds


def service(interactive: bool = True):
    _, _, _, build = _libs()
    creds = credentials(interactive)
    if not creds:
        raise StageError("Not signed in to YouTube. Settings → YouTube → Sign in.")
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def sign_in() -> dict[str, Any]:
    """Open the browser, sign in, and remember which channel it is."""
    yt = service(interactive=True)
    return _remember_channel(yt)


def _remember_channel(yt) -> dict[str, Any]:
    items = yt.channels().list(part="snippet", mine=True).execute().get("items", [])
    if not items:
        raise StageError("Signed in, but that Google account has no YouTube channel. Sign out and pick the "
                         "account (or Brand Account) that owns Followers or Facts.")
    ch = items[0]
    info = {"channel_id": ch["id"], "title": ch["snippet"]["title"],
            "url": f"https://www.youtube.com/channel/{ch['id']}"}
    account_path().write_text(json.dumps(info, indent=1), encoding="utf-8")
    return info


def account() -> dict[str, Any] | None:
    """Who we're signed in as (from the last sign-in), or None."""
    if not token_path().exists() or not account_path().exists():
        return None
    try:
        return json.loads(account_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def sign_out() -> None:
    for p in (token_path(), account_path()):
        p.unlink(missing_ok=True)
