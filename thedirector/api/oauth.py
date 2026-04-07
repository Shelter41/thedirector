import json
import logging
import hashlib
import base64
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from google_auth_oauthlib.flow import Flow

from ..config import settings
from ..connectors.db import execute, fetch_one

logger = logging.getLogger("thedirector.oauth")

router = APIRouter()

# ─── Gmail OAuth ─────────────────────────────────────────────────────────────

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
]


def _build_gmail_flow(redirect_uri: str) -> Flow:
    client_config = {
        "web": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri],
        }
    }
    flow = Flow.from_client_config(client_config, scopes=GMAIL_SCOPES)
    flow.redirect_uri = redirect_uri
    return flow


@router.get("/auth/gmail/url")
async def gmail_auth_url(request: Request):
    redirect_uri = str(request.url_for("gmail_callback"))
    flow = _build_gmail_flow(redirect_uri)

    code_verifier = secrets.token_urlsafe(64)
    code_challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )

    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        code_challenge=code_challenge,
        code_challenge_method="S256",
    )

    oauth_state = {"state": state, "code_verifier": code_verifier}
    await execute(
        """INSERT INTO credentials (provider, data, updated_at)
        VALUES ('gmail_oauth_state', %s, now())
        ON CONFLICT (provider) DO UPDATE SET data = %s, updated_at = now()""",
        (json.dumps(oauth_state), json.dumps(oauth_state)),
    )
    return {"auth_url": auth_url}


@router.get("/auth/gmail/callback", name="gmail_callback")
async def gmail_callback(code: str, state: str):
    row = await fetch_one(
        "SELECT data FROM credentials WHERE provider = 'gmail_oauth_state'"
    )
    if not row:
        return RedirectResponse(f"{settings.frontend_url}?gmail=error&reason=invalid_state")

    stored = row["data"] if isinstance(row["data"], dict) else json.loads(row["data"])
    if stored.get("state") != state:
        return RedirectResponse(f"{settings.frontend_url}?gmail=error&reason=state_mismatch")

    redirect_uri = f"{settings.backend_url}/auth/gmail/callback"
    flow = _build_gmail_flow(redirect_uri)

    try:
        flow.fetch_token(code=code, code_verifier=stored.get("code_verifier"))
    except Exception as e:
        logger.error("Gmail token exchange failed: %s", e)
        return RedirectResponse(f"{settings.frontend_url}?gmail=error&reason=token_exchange_failed")

    creds = flow.credentials
    token_data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes) if creds.scopes else GMAIL_SCOPES,
        "expiry": creds.expiry.isoformat() if creds.expiry else None,
    }

    await execute(
        """INSERT INTO credentials (provider, data, updated_at)
        VALUES ('gmail', %s, now())
        ON CONFLICT (provider) DO UPDATE SET data = %s, updated_at = now()""",
        (json.dumps(token_data), json.dumps(token_data)),
    )

    logger.info("Gmail connected")
    return RedirectResponse(f"{settings.frontend_url}?gmail=connected")


@router.get("/auth/gmail/status")
async def gmail_status():
    row = await fetch_one(
        "SELECT data, updated_at FROM credentials WHERE provider = 'gmail'"
    )
    if not row:
        return {"connected": False}

    data = row["data"] if isinstance(row["data"], dict) else json.loads(row["data"])

    needs_reconnect = False
    if data.get("refresh_token"):
        try:
            from google.auth.transport.requests import Request as GoogleRequest
            from google.oauth2.credentials import Credentials

            creds = Credentials(
                token=data.get("token"),
                refresh_token=data.get("refresh_token"),
                token_uri=data.get("token_uri", "https://oauth2.googleapis.com/token"),
                client_id=data.get("client_id", settings.google_client_id),
                client_secret=data.get("client_secret", settings.google_client_secret),
                scopes=data.get("scopes"),
            )
            if creds.expired or not creds.token:
                creds.refresh(GoogleRequest())
                refreshed = {
                    "token": creds.token,
                    "refresh_token": creds.refresh_token,
                    "token_uri": creds.token_uri,
                    "client_id": creds.client_id,
                    "client_secret": creds.client_secret,
                    "scopes": list(creds.scopes) if creds.scopes else [],
                    "expiry": creds.expiry.isoformat() if creds.expiry else None,
                }
                await execute(
                    """UPDATE credentials SET data = %s, updated_at = now()
                    WHERE provider = 'gmail'""",
                    (json.dumps(refreshed),),
                )
        except Exception:
            needs_reconnect = True
    else:
        needs_reconnect = True

    return {
        "connected": True,
        "needs_reconnect": needs_reconnect,
        "connected_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
    }


@router.delete("/auth/gmail")
async def gmail_disconnect():
    await execute("DELETE FROM credentials WHERE provider = 'gmail'")
    return {"disconnected": True}


# ─── Slack OAuth ─────────────────────────────────────────────────────────────

SLACK_AUTH_URL = "https://slack.com/oauth/v2/authorize"
SLACK_TOKEN_URL = "https://slack.com/api/oauth.v2.access"
SLACK_SCOPES = [
    "channels:read",
    "channels:history",
    "groups:read",
    "groups:history",
    "im:read",
    "im:history",
    "mpim:read",
    "mpim:history",
    "users:read",
]


@router.get("/auth/slack/url")
async def slack_auth_url(request: Request):
    state = secrets.token_urlsafe(32)
    state_data = {"state": state}
    await execute(
        """INSERT INTO credentials (provider, data, updated_at)
        VALUES ('slack_oauth_state', %s, now())
        ON CONFLICT (provider) DO UPDATE SET data = %s, updated_at = now()""",
        (json.dumps(state_data), json.dumps(state_data)),
    )

    redirect_uri = f"{settings.backend_url}/auth/slack/callback"
    params = {
        "client_id": settings.slack_client_id,
        "scope": ",".join(SLACK_SCOPES),
        "redirect_uri": redirect_uri,
        "state": state,
    }
    auth_url = f"{SLACK_AUTH_URL}?{urlencode(params)}"
    return {"auth_url": auth_url}


@router.get("/auth/slack/callback", name="slack_callback")
async def slack_callback(code: str, state: str = ""):
    row = await fetch_one(
        "SELECT data FROM credentials WHERE provider = 'slack_oauth_state'"
    )
    if not row:
        return RedirectResponse(f"{settings.frontend_url}?slack=error&reason=invalid_state")

    stored = row["data"] if isinstance(row["data"], dict) else json.loads(row["data"])
    if stored.get("state") != state:
        return RedirectResponse(f"{settings.frontend_url}?slack=error&reason=state_mismatch")

    redirect_uri = f"{settings.backend_url}/auth/slack/callback"

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                SLACK_TOKEN_URL,
                data={
                    "client_id": settings.slack_client_id,
                    "client_secret": settings.slack_client_secret,
                    "code": code,
                    "redirect_uri": redirect_uri,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        if not data.get("ok"):
            logger.error("Slack token exchange failed: %s", data.get("error"))
            return RedirectResponse(
                f"{settings.frontend_url}?slack=error&reason={data.get('error', 'unknown')}"
            )
    except Exception as e:
        logger.error("Slack token exchange failed: %s", e)
        return RedirectResponse(f"{settings.frontend_url}?slack=error&reason=token_exchange_failed")

    token_data = {
        "access_token": data.get("access_token"),
        "token_type": data.get("token_type", "bot"),
        "team_id": data.get("team", {}).get("id"),
        "team_name": data.get("team", {}).get("name"),
        "bot_user_id": data.get("bot_user_id"),
    }

    await execute(
        """INSERT INTO credentials (provider, data, updated_at)
        VALUES ('slack', %s, now())
        ON CONFLICT (provider) DO UPDATE SET data = %s, updated_at = now()""",
        (json.dumps(token_data), json.dumps(token_data)),
    )

    logger.info("Slack connected (team: %s)", token_data.get("team_name"))
    return RedirectResponse(f"{settings.frontend_url}?slack=connected")


@router.get("/auth/slack/status")
async def slack_status():
    row = await fetch_one(
        "SELECT data, updated_at FROM credentials WHERE provider = 'slack'"
    )
    if not row:
        return {"connected": False}

    data = row["data"] if isinstance(row["data"], dict) else json.loads(row["data"])
    return {
        "connected": True,
        "team_name": data.get("team_name"),
        "connected_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
    }


@router.delete("/auth/slack")
async def slack_disconnect():
    await execute("DELETE FROM credentials WHERE provider = 'slack'")
    return {"disconnected": True}


# ─── Notion (token-based, not OAuth) ─────────────────────────────────────────
#
# Notion integrations use a static "Internal Integration Token" rather than
# an OAuth flow. The user creates the integration at notion.so/my-integrations,
# copies the token, and pastes it into the UI. We validate it by hitting
# /users/me, then store it in the credentials table like the others.

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


from pydantic import BaseModel


class NotionConnectRequest(BaseModel):
    token: str


@router.post("/auth/notion")
async def notion_connect(req: NotionConnectRequest):
    token = (req.token or "").strip()
    if not token:
        return {"connected": False, "error": "token required"}

    # Validate by hitting /users/me — this also tells us the bot's name
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{NOTION_API}/users/me",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Notion-Version": NOTION_VERSION,
                },
            )
        if resp.status_code != 200:
            logger.warning("Notion token validation failed: %s %s", resp.status_code, resp.text[:200])
            return {"connected": False, "error": f"Notion rejected the token (HTTP {resp.status_code})"}
        user = resp.json()
    except httpx.HTTPError as e:
        logger.error("Notion validation failed: %s", e)
        return {"connected": False, "error": f"validation failed: {e}"}

    bot_name = (
        user.get("name")
        or (user.get("bot") or {}).get("workspace_name")
        or "Notion"
    )

    token_data = {"token": token, "bot_name": bot_name}
    await execute(
        """INSERT INTO credentials (provider, data, updated_at)
        VALUES ('notion', %s, now())
        ON CONFLICT (provider) DO UPDATE SET data = %s, updated_at = now()""",
        (json.dumps(token_data), json.dumps(token_data)),
    )
    logger.info("Notion connected (%s)", bot_name)
    return {"connected": True, "bot_name": bot_name}


@router.get("/auth/notion/status")
async def notion_status():
    row = await fetch_one(
        "SELECT data, updated_at FROM credentials WHERE provider = 'notion'"
    )
    if not row:
        return {"connected": False}
    data = row["data"] if isinstance(row["data"], dict) else json.loads(row["data"])
    return {
        "connected": True,
        "bot_name": data.get("bot_name"),
        "connected_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
    }


@router.delete("/auth/notion")
async def notion_disconnect():
    await execute("DELETE FROM credentials WHERE provider = 'notion'")
    return {"disconnected": True}
