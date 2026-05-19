"""
ops CLI — operator-side credential management for clawbot.

Use this when you don't want the agent to auto-sign-up (anti-bot will
zombie the attempt) and you'd rather provide a credential yourself.

Writes credentials directly into the Fernet-encrypted vault. `_LiveSecret.get`
checks the vault first, so publishing skills pick up the new credential
on the next cycle — no container restart, no .env edit, no rebuild.

Usage:
    python -m clawbot.ops_cli add-account bluesky <handle> <app-password>
    python -m clawbot.ops_cli add-account devto <api-key>
    python -m clawbot.ops_cli add-account mastodon <instance> <access-token>
    python -m clawbot.ops_cli add-account hashnode <pat> <publication-id>
    python -m clawbot.ops_cli list-accounts
    python -m clawbot.ops_cli remove-account bluesky
    python -m clawbot.ops_cli test-credential bluesky    # live API smoke test

Pass `-` for any value to be prompted interactively (input hidden — won't
land in shell history):
    python -m clawbot.ops_cli add-account bluesky my.handle.bsky.social -

VPS usage via the wrapper script:
    ssh clawbot /opt/clawbot/ops add-account bluesky my.handle.bsky.social <pwd>
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys
from typing import Callable


# Per-service: ordered list of (secret_name, prompt_label) the operator
# must provide. The cycle runner's publishing skills read these via
# ctx.secret.get(<name>).
SERVICE_SCHEMA: dict[str, list[tuple[str, str]]] = {
    "bluesky": [
        ("BSKY_HANDLE", "Bluesky handle (e.g. clawbot-tools.bsky.social)"),
        ("BSKY_APP_PASSWORD", "Bluesky app password (xxxx-xxxx-xxxx-xxxx)"),
    ],
    "mastodon": [
        ("MASTODON_INSTANCE", "Mastodon instance hostname (e.g. mastodon.uk)"),
        ("MASTODON_ACCESS_TOKEN", "Mastodon access token"),
    ],
    "devto": [
        ("DEVTO_API_KEY", "Dev.to API key"),
    ],
    "hashnode": [
        ("HASHNODE_PAT", "Hashnode Personal Access Token"),
        ("HASHNODE_PUBLICATION_ID", "Hashnode publication ID (24-char hex)"),
    ],
    "medium": [
        ("MEDIUM_INTEGRATION_TOKEN", "Medium integration token"),
        ("MEDIUM_USER_ID", "Medium user ID"),
    ],
    "substack": [
        ("SUBSTACK_EMAIL", "Substack login email"),
        ("SUBSTACK_PASSWORD", "Substack password"),
        ("SUBSTACK_PUBLICATION_URL", "Substack publication URL"),
    ],
}


def _open_vault():
    """Load AccountsStore using the env-configured vault key + db path.
    Raises a clear error if ACCOUNTS_VAULT_KEY is unset."""
    vault_key = os.environ.get("ACCOUNTS_VAULT_KEY", "").strip()
    if not vault_key:
        # Fall back to Settings (reads .env)
        try:
            from clawbot.config import settings
            vault_key = settings.accounts_vault_key
        except Exception:
            pass
    if not vault_key:
        sys.stderr.write(
            "ERROR: ACCOUNTS_VAULT_KEY not set. Either export it in the shell\n"
            "or run this command inside the container where .env is loaded:\n"
            "  ssh clawbot /opt/clawbot/ops add-account ...\n"
        )
        sys.exit(2)
    db_path = os.environ.get("ACCOUNTS_DB_PATH", "")
    if not db_path:
        try:
            from clawbot.config import settings
            db_path = settings.accounts_db_path
        except Exception:
            db_path = "data/accounts.db"
    from clawbot.accounts_store import AccountsStore
    store = AccountsStore(db_path=db_path, encryption_key=vault_key)
    store.init_schema()
    store.init_secrets_schema()
    return store


def _resolve_value(label: str, raw: str | None) -> str:
    """If raw is empty or '-', prompt interactively with hidden input.
    Otherwise use raw verbatim. Strip surrounding whitespace."""
    if raw and raw.strip() and raw.strip() != "-":
        return raw.strip()
    return getpass.getpass(f"{label}: ").strip()


def cmd_add_account(args: argparse.Namespace) -> int:
    service = args.service.lower()
    if service not in SERVICE_SCHEMA:
        sys.stderr.write(
            f"ERROR: unknown service {service!r}. Known: {sorted(SERVICE_SCHEMA)}\n"
        )
        return 2
    schema = SERVICE_SCHEMA[service]
    provided = list(args.values)
    if len(provided) > len(schema):
        sys.stderr.write(
            f"ERROR: too many values; {service} expects {len(schema)}, got {len(provided)}\n"
        )
        return 2
    # Pad with None so each schema entry gets either a positional or interactive prompt
    while len(provided) < len(schema):
        provided.append("")
    store = _open_vault()
    stored: list[str] = []
    for (name, label), raw in zip(schema, provided):
        value = _resolve_value(label, raw)
        if not value:
            sys.stderr.write(f"ERROR: empty value for {name}; aborting.\n")
            return 2
        store.set_secret(name=name, value=value, source="operator")
        stored.append(name)
    # Mark a row in the accounts table so list_accounts() shows operator-provided
    # entries alongside agent-created ones. Email is synthetic for operator
    # accounts since we don't capture the underlying account email here.
    try:
        store.store(
            service=service, email=f"operator-provided@{service}",
            password="(operator-managed, not vaulted here)",
            cookies_json="",
            notes=f"Operator-provided credentials via ops_cli; secrets: {','.join(stored)}",
        )
    except Exception as exc:
        # Account-row creation is bookkeeping; failure shouldn't reverse the secrets
        sys.stderr.write(f"WARN: account row marker failed (secrets are saved): {exc}\n")
    print(f"✓ {service}: stored {len(stored)} secret(s): {', '.join(stored)}")
    print(f"  Skills will pick this up on the next cycle (no restart needed).")
    return 0


def cmd_list_accounts(args: argparse.Namespace) -> int:
    store = _open_vault()
    names = store.list_secret_names()
    print(f"Vault contains {len(names)} secret(s):")
    for n in names:
        print(f"  {n}")
    print()
    # Per-service: which are complete?
    print("Per-service status:")
    for service, schema in sorted(SERVICE_SCHEMA.items()):
        expected = {n for n, _ in schema}
        have = expected & set(names)
        missing = expected - set(names)
        status = "✓" if not missing else "✗"
        detail = f"have: {sorted(have)}" if have else "(none)"
        miss = f"  MISSING: {sorted(missing)}" if missing else ""
        print(f"  {status} {service:12s} {detail}{miss}")
    return 0


def cmd_remove_account(args: argparse.Namespace) -> int:
    service = args.service.lower()
    if service not in SERVICE_SCHEMA:
        sys.stderr.write(f"ERROR: unknown service {service!r}\n")
        return 2
    store = _open_vault()
    import sqlite3
    schema = SERVICE_SCHEMA[service]
    names = [n for n, _ in schema]
    removed = 0
    with sqlite3.connect(store._db_path) as conn:
        for n in names:
            cur = conn.execute("DELETE FROM agent_secrets WHERE name=?", (n,))
            if cur.rowcount > 0:
                removed += 1
        # Also retire the accounts table row
        try:
            conn.execute(
                "UPDATE accounts SET status='revoked' WHERE service=? AND email=?",
                (service, f"operator-provided@{service}"),
            )
        except sqlite3.OperationalError:
            pass
    print(f"✓ {service}: removed {removed} secret(s)")
    return 0


def cmd_test_credential(args: argparse.Namespace) -> int:
    """Live API smoke test for a stored credential. Calls each platform's
    auth-verify endpoint to confirm the secrets actually work."""
    import json as _json
    import urllib.request
    import urllib.error
    service = args.service.lower()
    store = _open_vault()

    def _g(name: str) -> str:
        return store.get_secret(name) or ""

    if service == "bluesky":
        handle = _g("BSKY_HANDLE")
        pw = _g("BSKY_APP_PASSWORD")
        if not (handle and pw):
            print(f"✗ bluesky: missing credentials in vault"); return 1
        body = _json.dumps({"identifier": handle, "password": pw}).encode()
        req = urllib.request.Request(
            "https://bsky.social/xrpc/com.atproto.server.createSession",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                data = _json.loads(r.read().decode())
                print(f"✓ bluesky auth ok: did={data.get('did', '?')[:50]}")
                return 0
        except urllib.error.HTTPError as e:
            err = e.read().decode()[:200]
            print(f"✗ bluesky auth failed ({e.code}): {err}")
            return 1
        except Exception as e:
            print(f"✗ bluesky test error: {e!r}")
            return 1
    elif service == "mastodon":
        instance = _g("MASTODON_INSTANCE")
        token = _g("MASTODON_ACCESS_TOKEN")
        if not (instance and token):
            print(f"✗ mastodon: missing credentials"); return 1
        if not instance.startswith("http"):
            instance = f"https://{instance}"
        req = urllib.request.Request(
            f"{instance.rstrip('/')}/api/v1/accounts/verify_credentials",
            headers={"Authorization": f"Bearer {token}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                data = _json.loads(r.read().decode())
                print(f"✓ mastodon auth ok: @{data.get('username', '?')}@{instance.split('://')[1]}")
                return 0
        except urllib.error.HTTPError as e:
            print(f"✗ mastodon auth failed ({e.code}): {e.read().decode()[:200]}")
            return 1
        except Exception as e:
            print(f"✗ mastodon test error: {e!r}")
            return 1
    elif service == "devto":
        key = _g("DEVTO_API_KEY")
        if not key:
            print(f"✗ devto: missing credential"); return 1
        req = urllib.request.Request("https://dev.to/api/users/me", headers={"api-key": key})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                data = _json.loads(r.read().decode())
                print(f"✓ devto auth ok: username={data.get('username', '?')}")
                return 0
        except urllib.error.HTTPError as e:
            print(f"✗ devto auth failed ({e.code}): {e.read().decode()[:200]}")
            return 1
        except Exception as e:
            print(f"✗ devto test error: {e!r}")
            return 1
    else:
        print(f"test-credential not implemented for {service!r}; supported: bluesky, mastodon, devto")
        return 2


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ops",
        description="Operator-side credential management for clawbot.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    aa = sub.add_parser(
        "add-account",
        help="Store credentials for a service (Bluesky, Mastodon, Dev.to, Hashnode, Medium, Substack).",
    )
    aa.add_argument("service", help="Service key: " + ", ".join(sorted(SERVICE_SCHEMA)))
    aa.add_argument(
        "values", nargs="*",
        help="Positional credential values in service-schema order. Use - to prompt interactively.",
    )
    aa.set_defaults(func=cmd_add_account)

    la = sub.add_parser("list-accounts", help="List vault secrets + per-service completeness.")
    la.set_defaults(func=cmd_list_accounts)

    ra = sub.add_parser("remove-account", help="Remove all secrets for a service.")
    ra.add_argument("service", help="Service key")
    ra.set_defaults(func=cmd_remove_account)

    tc = sub.add_parser("test-credential", help="Live API verification of a stored credential.")
    tc.add_argument("service", help="Service key: bluesky, mastodon, or devto")
    tc.set_defaults(func=cmd_test_credential)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    fn: Callable[[argparse.Namespace], int] = args.func
    return fn(args)


if __name__ == "__main__":
    sys.exit(main())
