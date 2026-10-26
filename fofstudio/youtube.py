"""Signing in to your YouTube channel (free YouTube Data API), for Settings and the Upload step.

One-time setup (Settings → YouTube → Set up YouTube, step by step; docs/YOUTUBE.md): make a free Google
Cloud project, turn on YouTube Data API v3, fill in Branding, set Audience to External and PUBLISH the app
("In production" - in "Testing", Google signs you out every 7 days, the likely cause of the failed uploads),
make a "Desktop app" client, download its JSON, sign in (tick "Manage your YouTube videos").

Why PowerDirector needs none of this (research "Easy YouTube upload like PowerDirector"): CyberLink ships its
own Google project, approved by Google, inside the program. A personal app can't borrow that; for one user,
your own project "In production" is allowed without Google's verification. If YouTube still locks API uploads
as private, or anything goes wrong, Publish → "Upload in my browser" needs no setup at all (publishkit.py).
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


UPLOAD_SCOPE = SCOPES[0]
SETUP_LINKS = [
    ("Make a free Google Cloud project (any name, e.g. 'Followers or Facts Studio')",
     "https://console.cloud.google.com/projectcreate"),
    ("Turn on 'YouTube Data API v3' (press Enable)",
     "https://console.cloud.google.com/apis/library/youtube.googleapis.com"),
    ("Branding: app name 'Followers or Facts Studio', your email twice, Save",
     "https://console.cloud.google.com/auth/branding"),
    ("Audience: External, then press PUBLISH APP so it says 'In production' (stops the 7-day sign-out)",
     "https://console.cloud.google.com/auth/audience"),
    ("Clients: Create client, type 'Desktop app', then Download JSON (it lands in Downloads; the Studio finds it)",
     "https://console.cloud.google.com/auth/clients/create"),
]


def explain(exc: Exception | str) -> str:
    """Google's errors in plain words, with the fix."""
    t = str(exc)
    low = t.lower()
    if "invalid_grant" in low or "token has been expired or revoked" in low:
        return ("Google signed the Studio out. If your Google app is still in 'Testing', Google does that every 7 "
                "days: Settings → YouTube → Set up YouTube → step 4 (Audience → PUBLISH APP), then Sign in again.")
    if "access_denied" in low or "has not completed the google verification" in low:
        return ("Google refused the sign-in: in Testing mode only listed test users may sign in. Publish the app "
                "(Settings → YouTube → Set up YouTube → step 4), or add your Google account as a test user.")
    if "redirect_uri_mismatch" in low:
        return ("The client file isn't a 'Desktop app' client. Make a new client of type Desktop app (step 5) and "
                "download its JSON.")
    if "youtubesignuprequired" in low or "unlinked" in low:
        return "That Google account has no YouTube channel. Sign out and pick the account that owns the channel."
    if "insufficientpermissions" in low or "insufficient authentication scopes" in low:
        return ("Google didn't give permission to upload: Sign out, Sign in again and tick the box 'Manage your "
                "YouTube videos' on Google's permission page.")
    if "quotaexceeded" in low or "uploadlimitexceeded" in low:
        return ("YouTube's daily upload limit for the app is used up. Try again tomorrow, or use Publish → Upload "
                "in my browser now.")
    if "timed out" in low or "timeout" in low:
        return ("The sign-in didn't come back to the Studio. Finish the sign-in in the browser tab; if it never "
                "returns, a firewall may be blocking the Studio's local sign-in page (allow Python).")
    return t


def expired_path() -> Path:
    return Paths().root / "youtube-expired.json"


def token_path() -> Path:
    return Paths().root / "youtube-token.json"


def account_path() -> Path:
    return Paths().root / "youtube-account.json"


def client_file() -> Path | None:
    """The Google client file: the one chosen in Settings, or one found in the usual places (the data
    folder, the Studio folder, its fof_data folder - where Google's own uploader looked - Downloads, Desktop)."""
    p = settings()["youtube"]["client_secrets"]
    if p and Path(p).exists():
        return Path(p)
    found = find_client_file()
    if found:
        try:
            return use_client_file(found)
        except StageError:
            return None
    return None


def find_client_file() -> Path | None:
    from .config import REPO
    home = Path.home()
    places = [Paths().root, REPO, REPO / "fof_data", home / "Downloads", home / "Desktop",
              home / "OneDrive" / "Desktop", home / "OneDrive" / "Downloads"]
    for folder in places:
        try:
            files = sorted(folder.glob("client_secret*.json"), key=lambda f: f.stat().st_mtime, reverse=True) + \
                sorted(folder.glob("youtube-client.json"))
        except OSError:
            continue
        for f in files:
            try:
                if "installed" in json.loads(f.read_text(encoding="utf-8")):
                    return f
            except (OSError, ValueError):
                continue
    return None


def status() -> dict[str, Any]:
    """What's ready for uploading, in plain words, for the Publish page."""
    try:
        _libs()
        libs = True
    except StageError:
        libs = False
    cf = client_file()
    acct = account()
    signed = False
    if acct and libs:
        try:
            signed = credentials(interactive=False) is not None
        except Exception:  # noqa: BLE001 - a broken token counts as signed out
            signed = False
    expired = None
    if expired_path().exists():
        try:
            expired = json.loads(expired_path().read_text(encoding="utf-8")).get("why")
        except (OSError, ValueError):
            expired = None
    return {"libs": libs, "client_file": str(cf) if cf else "", "account": acct, "signed_in": signed,
            "expired": expired if not signed else None}


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
            expired_path().unlink(missing_ok=True)
            return creds
        except Exception as exc:  # noqa: BLE001 - e.g. a 7-day "Testing" sign-in ran out: sign in again
            from .util import utc_now
            expired_path().write_text(json.dumps({"at": utc_now(), "why": explain(exc), "error": str(exc)[:300]}),
                                      encoding="utf-8")
            creds = None
    if not interactive:
        return None
    secrets = client_file()
    if not secrets:
        raise StageError("Choose your Google client file first: Settings → YouTube → Choose client file. "
                         "docs/YOUTUBE.md explains how to make one (free, about 10 minutes).")
    flow = InstalledAppFlow.from_client_secrets_file(str(secrets), SCOPES)
    try:
        creds = flow.run_local_server(port=0, open_browser=True, prompt="consent", access_type="offline",
                                      authorization_prompt_message="", timeout_seconds=600,
                                      success_message="Signed in. You can close this tab and go back to the Studio.")
    except Exception as exc:  # noqa: BLE001 - say what went wrong in plain words
        raise StageError(explain(exc))
    if creds is None:
        raise StageError(explain("timed out"))
    granted = set(getattr(creds, "granted_scopes", None) or creds.scopes or [])
    if granted and UPLOAD_SCOPE not in granted:
        raise StageError(explain("insufficientPermissions"))
    token.write_text(creds.to_json(), encoding="utf-8")
    expired_path().unlink(missing_ok=True)
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


def sanitize_tags(tags: list[str]) -> list[str]:
    """YouTube allows 500 characters of tags in total; no angle brackets; no duplicates."""
    seen, out = set(), []
    for tag in tags:
        t = " ".join(str(tag).replace("<", "").replace(">", "").replace(",", " ").split())[:100]
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    # YouTube counts a tag with a space as if it had quotes around it
    while out and sum(len(t) + (2 if " " in t else 0) for t in out) + len(out) - 1 > 500:
        out.pop()
    return out


def studio_url(video_id: str) -> str:
    """Where to check YouTube's checks (copyright, ad suitability) before making the video public."""
    return f"https://studio.youtube.com/video/{video_id}/edit"


def video_url(video_id: str) -> str:
    return f"https://youtu.be/{video_id}"
