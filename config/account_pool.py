"""Validate externally supplied accounts without logging their contents."""
from __future__ import annotations

import json


def decode_account_pool(raw: bytes) -> list[dict]:
    try:
        accounts = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, UnicodeError):
        raise ValueError("Account object must contain valid UTF-8 JSON") from None
    if not isinstance(accounts, list) or not accounts:
        raise ValueError("Account object must be a non-empty JSON array")
    result = []
    roles, names = set(), set()
    for index, account in enumerate(accounts, 1):
        if not isinstance(account, dict):
            raise ValueError(f"Account {index} must be an object")
        role = account.get("role_id")
        if isinstance(role, bool) or not isinstance(role, (str, int)) or not str(role).isascii() or not str(role).isdigit() or int(role) <= 0:
            raise ValueError(f"Account {index} has an invalid role_id")
        role = int(role)
        token = account.get("token")
        if not isinstance(token, str) or not token.strip():
            raise ValueError(f"Account {index} has an invalid token")
        name = str(account.get("name") or f"account-{index:03d}").strip()
        if not name or role in roles or name in names:
            raise ValueError(f"Account {index} has a duplicate role_id/name or empty name")
        roles.add(role)
        names.add(name)
        result.append({"name": name, "role_id": role, "token": token.strip()})
    return result
