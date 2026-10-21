"""Administrative command line.

    python -m app.cli create-api-key --name admin --role ADMIN
    python -m app.cli list-api-keys
    python -m app.cli revoke-api-key <id>

Inside Docker:  docker compose exec api python -m app.cli create-api-key --name admin --role ADMIN
"""

import argparse
import sys
import uuid
from datetime import timedelta

from sqlalchemy import select

from app.config import get_settings
from app.db import create_db_engine, make_session_factory
from app.models import ApiKey, ApiKeyRole
from app.services.api_keys import create_api_key
from app.timeutil import utcnow


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="InfraScope admin CLI")
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create-api-key", help="Create a key and print its secret once")
    create.add_argument("--name", required=True)
    create.add_argument(
        "--role", type=str.upper, choices=[r.value for r in ApiKeyRole], default="VIEWER"
    )
    create.add_argument("--expires-in-days", type=int, default=None)

    commands.add_parser("list-api-keys", help="List keys (no secrets)")

    revoke = commands.add_parser("revoke-api-key", help="Revoke a key by id")
    revoke.add_argument("key_id", type=uuid.UUID)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    engine = create_db_engine(get_settings().database_url.get_secret_value())
    session_factory = make_session_factory(engine)
    try:
        with session_factory() as session:
            if args.command == "create-api-key":
                expires_at = (
                    utcnow() + timedelta(days=args.expires_in_days)
                    if args.expires_in_days
                    else None
                )
                api_key, raw_key = create_api_key(
                    session, name=args.name, role=ApiKeyRole(args.role), expires_at=expires_at
                )
                session.commit()
                print(f"Created {api_key.role} key '{api_key.name}' (id {api_key.id})")
                print("Store this key now; it will not be shown again:")
                print(raw_key)
            elif args.command == "list-api-keys":
                for key in session.scalars(select(ApiKey).order_by(ApiKey.created_at)):
                    state = "revoked" if key.revoked_at else "active"
                    print(f"{key.id}  {key.key_prefix}…  {key.role:<6}  {state:<7}  {key.name}")
            elif args.command == "revoke-api-key":
                key = session.get(ApiKey, args.key_id)
                if key is None:
                    print("API key not found", file=sys.stderr)
                    return 1
                key.revoked_at = key.revoked_at or utcnow()
                session.commit()
                print(f"Revoked key '{key.name}'")
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
