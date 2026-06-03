"""Email App — FastAPI Routes

Mounted at /api/apps/email/ by the app platform loader.
"""

import asyncio
import logging
from fastapi import APIRouter, Request
from pydantic import BaseModel

from app_platform.auth import scope_user
from apps.email import data as dl_email
from apps.email import gmail_client

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class EmailRuleRequest(BaseModel):
    account_id: str
    name: str
    conditions: dict
    actions: dict
    priority: int = 100
    stop_processing: bool = True


class EmailRuleUpdateRequest(BaseModel):
    name: str | None = None
    conditions: dict | None = None
    actions: dict | None = None
    priority: int | None = None
    active: bool | None = None
    stop_processing: bool | None = None


class EmailRuleReorderRequest(BaseModel):
    rule_ids: list[str]


class EmailAccountUpdateRequest(BaseModel):
    display_name: str | None = None
    active: bool | None = None


# ---------------------------------------------------------------------------
# PKCE verifier store (in-memory, per-process)
# ---------------------------------------------------------------------------

_oauth_verifiers: dict[str, str] = {}  # state -> code_verifier


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

@router.get("/accounts")
async def api_email_accounts(request: Request, user: str = ""):
    user = scope_user(request, user)
    if not user:
        return {"error": "user query param required"}
    accounts = await asyncio.to_thread(dl_email.list_accounts, user)
    # Strip credentials from response
    for a in accounts:
        a.pop("credentials", None)
    return {"accounts": accounts}


@router.get("/oauth/start")
async def api_email_oauth_start(user: str = "", display_name: str = ""):
    """Begin OAuth flow — returns the Google consent URL."""
    if not user:
        return {"error": "user query param required"}
    state = f"{user}|{display_name}"
    url, code_verifier = gmail_client.get_oauth_url(state=state)
    # Persist code_verifier so the callback can use it for PKCE
    _oauth_verifiers[state] = code_verifier
    return {"url": url}


@router.get("/oauth/callback")
async def api_email_oauth_callback(code: str = "", state: str = "", error: str = ""):
    """OAuth callback — exchanges code for tokens and creates account."""
    from starlette.responses import HTMLResponse
    if error:
        return HTMLResponse(f"<h2>OAuth Error</h2><p>{error}</p><p>You can close this tab.</p>")
    if not code:
        return HTMLResponse("<h2>Error</h2><p>No authorization code received.</p>")

    # Parse state
    parts = state.split("|", 1)
    user_id = parts[0] if parts else ""
    display_name = parts[1] if len(parts) > 1 else ""

    if not user_id:
        return HTMLResponse("<h2>Error</h2><p>Missing user in OAuth state.</p>")

    # Retrieve PKCE code_verifier from the start step
    code_verifier = _oauth_verifiers.pop(state, None)

    try:
        # Exchange code for tokens
        credentials = await asyncio.to_thread(gmail_client.exchange_code, code, code_verifier)

        # Get the authenticated email address
        email_address = await asyncio.to_thread(gmail_client.get_user_email, credentials)

        # Create the account record
        account = await asyncio.to_thread(
            dl_email.create_account,
            user_id=user_id,
            email_address=email_address,
            display_name=display_name or email_address.split("@")[0],
            credentials=credentials,
            scopes=credentials.get("scopes", []),
        )

        return HTMLResponse(
            f"<h2>Gmail Connected!</h2>"
            f"<p>Account <b>{email_address}</b> connected successfully.</p>"
            f"<p>You can close this tab and return to SkipperBot.</p>"
            f"<script>window.close();</script>"
        )
    except Exception as e:
        logger.error("EMAIL OAuth callback error: %s", e, exc_info=True)
        return HTMLResponse(f"<h2>Error</h2><p>{type(e).__name__}: {str(e)[:500]}</p>")


@router.delete("/accounts/{account_id}")
async def api_email_delete_account(account_id: str):
    account = await asyncio.to_thread(dl_email.get_account, account_id)
    if not account:
        return {"error": "Account not found"}
    # Revoke token
    try:
        creds = account.get("credentials", {})
        if creds:
            await asyncio.to_thread(gmail_client.revoke_token, creds)
    except Exception as e:
        logger.warning("EMAIL: Token revocation failed: %s", e)
    # Delete account (cascades to rules and log)
    await asyncio.to_thread(dl_email.delete_account, account_id)
    return {"ok": True}


@router.patch("/accounts/{account_id}")
async def api_email_update_account(account_id: str, req: EmailAccountUpdateRequest):
    kwargs = {k: v for k, v in req.model_dump().items() if v is not None}
    result = await asyncio.to_thread(dl_email.update_account, account_id, **kwargs)
    if result:
        result.pop("credentials", None)
    return {"ok": True, "account": result}


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

@router.get("/rules")
async def api_email_rules(account_id: str = ""):
    if not account_id:
        return {"error": "account_id query param required"}
    rules = await asyncio.to_thread(dl_email.list_rules, account_id)
    return {"rules": rules}


@router.post("/rules")
async def api_email_create_rule(req: EmailRuleRequest):
    rule = await asyncio.to_thread(
        dl_email.create_rule,
        account_id=req.account_id,
        name=req.name,
        conditions=req.conditions,
        actions=req.actions,
        priority=req.priority,
        stop_processing=req.stop_processing,
    )
    return {"ok": True, "rule": rule}


@router.patch("/rules/{rule_id}")
async def api_email_update_rule(rule_id: str, req: EmailRuleUpdateRequest):
    kwargs = {k: v for k, v in req.model_dump().items() if v is not None}
    result = await asyncio.to_thread(dl_email.update_rule, rule_id, **kwargs)
    return {"ok": True, "rule": result}


@router.delete("/rules/{rule_id}")
async def api_email_delete_rule(rule_id: str):
    ok = await asyncio.to_thread(dl_email.delete_rule, rule_id)
    return {"ok": ok}


@router.post("/rules/reorder")
async def api_email_reorder_rules(req: EmailRuleReorderRequest):
    count = await asyncio.to_thread(dl_email.reorder_rules, req.rule_ids)
    return {"ok": True, "updated": count}


# ---------------------------------------------------------------------------
# Log & Sync
# ---------------------------------------------------------------------------

@router.get("/log")
async def api_email_log(request: Request, account_id: str = "", user: str = "", limit: int = 50, offset: int = 0):
    user = scope_user(request, user)
    rows = await asyncio.to_thread(dl_email.list_log, account_id=account_id, user_id=user, limit=limit, offset=offset)
    return {"log": rows}


@router.get("/labels")
async def api_email_labels(account_id: str = ""):
    """Fetch all Gmail labels for an account."""
    if not account_id:
        return {"error": "account_id query param required"}
    account = await asyncio.to_thread(dl_email.get_account, account_id)
    if not account:
        return {"error": "Account not found"}
    creds = account.get("credentials", {})
    if not creds:
        return {"error": "No credentials for this account"}
    try:
        labels = await asyncio.to_thread(gmail_client.list_labels, creds)
        return {"labels": labels}
    except Exception as e:
        logger.error("EMAIL labels error: %s", e, exc_info=True)
        return {"error": str(e)[:500]}


@router.get("/message")
async def api_email_message(account_id: str = "", gmail_msg_id: str = ""):
    """Fetch full email details (sender, subject, body) from Gmail."""
    if not account_id or not gmail_msg_id:
        return {"error": "account_id and gmail_msg_id required"}
    account = await asyncio.to_thread(dl_email.get_account, account_id)
    if not account:
        return {"error": "Account not found"}
    creds = account.get("credentials", {})
    if not creds:
        return {"error": "No credentials for this account"}
    try:
        body = await asyncio.to_thread(gmail_client.get_message_body, creds, gmail_msg_id)
        return {"body": body}
    except Exception as e:
        logger.error("EMAIL message error: %s", e, exc_info=True)
        return {"error": str(e)[:500]}


@router.post("/sync")
async def api_email_sync(account_id: str = ""):
    """Trigger a manual sync for one account."""
    if not account_id:
        return {"error": "account_id required"}
    from apps.email.runner import run_single_account_sync
    result = await asyncio.to_thread(run_single_account_sync, account_id)
    return result
