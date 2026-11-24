"""Manage beta invitations and daily quotas on the server."""
import argparse
from datetime import datetime, timezone

from app.beta.access import BetaAccess
from app.beta.quotas import DEFAULT_ACCOUNT, GLOBAL, account_subject
from app.core.config import Settings


def show_limits(access, settings):
    used, total, default, reset, accounts = access.quotas.provider_usage(
        settings.beta_identity_daily_limit, settings.beta_total_daily_limit,
    )
    print(f"Resets at {datetime.fromtimestamp(reset, tz=timezone.utc):%Y-%m-%d %H:%M UTC}")
    print(f"Global: {used}/{total}\nDefault per account: {default}")
    for account, label, active, used, limit, overridden in accounts:
        status = "active" if active else "disabled"
        source = "custom" if overridden else "default"
        print(f"{account}\t{used}/{limit}\t{source}\t{status}\t{label}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    issue = commands.add_parser("invite", help="Create a one-time login code")
    identity = issue.add_mutually_exclusive_group(required=True)
    identity.add_argument("--label", help="Label for a new participant")
    identity.add_argument("--account", help="Issue a new code for an existing account ID")
    issue.add_argument("--hours", type=int, default=72)
    commands.add_parser("list", help="List participants")
    commands.add_parser("revoke-invite").add_argument("id")
    commands.add_parser("revoke-account").add_argument("id")
    commands.add_parser("limits", help="Show today's usage and limits")
    set_limit = commands.add_parser("set-limit", help="Set a daily limit without resetting usage")
    set_limit.add_argument("maximum", type=int, help="Requests per day (0 pauses paid features)")
    reset_limit = commands.add_parser("reset-limit", help="Restore the inherited limit")
    for command in (set_limit, reset_limit):
        target = command.add_mutually_exclusive_group(required=True)
        target.add_argument("--account", help="Participant account ID")
        target.add_argument("--default", action="store_true", help="Default for all accounts")
        target.add_argument("--global", dest="global_limit", action="store_true", help="Shared cap across the beta")
    args = parser.parse_args()
    if args.action == "invite" and not 1 <= args.hours <= 720:
        parser.error("--hours must be between 1 and 720.")
    settings = Settings()
    if not settings.beta_origin:
        parser.error("MOCKROOM_BETA_ORIGIN must be set. Run this in the beta service.")
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    access = BetaAccess(settings.data_dir / "beta.sqlite3")
    if args.action == "invite":
        try:
            account, invite, code = access.issue(args.label or "", args.hours * 3600, account_id=args.account)
        except ValueError as error:
            parser.error(str(error))
        print(f"Account: {account}\nInvitation ID: {invite}\nOne-time code: {code}")
    elif args.action == "list":
        for account, label, active in access.accounts():
            print(f"{account}\t{'active' if active else 'disabled'}\t{label}")
    elif args.action == "revoke-invite":
        if not access.revoke_invite(args.id):
            parser.error("Unused invitation not found.")
    elif args.action == "revoke-account":
        if not access.revoke_account(args.id):
            parser.error("Account not found.")
    elif args.action == "limits":
        show_limits(access, settings)
    else:
        subject = account_subject(args.account) if args.account is not None else (
            GLOBAL if args.global_limit else DEFAULT_ACCOUNT
        )
        try:
            access.quotas.set_provider_limit(subject, getattr(args, "maximum", None))
        except ValueError as error:
            parser.error(str(error))
        show_limits(access, settings)


if __name__ == "__main__":
    main()
