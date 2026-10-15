import argparse
import json
import sys
from pathlib import Path
from . import __version__, agent_skill, cli_output
from .common import Failure
from . import recall_client
from .service import Tasks


Parser = cli_output.Parser


def parser():
    p = Parser(prog='cloud-tasks', description='Unified iCloud Reminders and Google Tasks')
    p.add_argument('--config', help='account config JSON (default XDG config directory)')
    p.add_argument('--app', action='store_true', help='open the native GTK app')
    p.add_argument('--version', action='version', version='cloud-tasks 0.2.0')
    sub = p.add_subparsers(dest='command')
    skill = sub.add_parser('skill', help='print the agent skill; install/remove it for coding agents (~/.agents/skills, linked for Claude Code)')
    skill.add_argument('action', nargs='?', choices=['install', 'remove'])
    sub.add_parser('background', help='sync the Apple provider and deliver due notifications')
    sub.add_parser('migrate', help='adopt an existing legacy Apple cache without moving data')
    sub.add_parser('status', help='check configured accounts with provider reads')
    account = sub.add_parser('account').add_subparsers(dest='action', required=True)
    account.add_parser('list', help='list configuration; no credential access')
    add = account.add_parser('add')
    add.add_argument('provider', choices=['icloud', 'google'])
    add.add_argument('--name')
    add.add_argument('--gws-config', help='explicit existing gws account directory, or omit for a product-owned directory')
    login = account.add_parser('login')
    login.add_argument('name')
    remove = account.add_parser('remove')
    remove.add_argument('name')
    remove.add_argument('--yes', action='store_true')
    lists = sub.add_parser('lists')
    lists.add_argument('--account')
    listing = sub.add_parser('list')
    listing.add_argument('--semantic', metavar='QUERY', help='rank current account/list records with local Recall; text fallback when unavailable')
    listing.add_argument('--list', dest='list_id')
    listing.add_argument('--account')
    mode = listing.add_mutually_exclusive_group()
    mode.add_argument('--all', action='store_true')
    mode.add_argument('--completed', action='store_true')
    show = sub.add_parser('show')
    show.add_argument('id')
    add = sub.add_parser('add')
    add.add_argument('title')
    add.add_argument('--list', dest='list_id', required=True)
    add.add_argument('--notes')
    add.add_argument('--due')
    edit = sub.add_parser('edit')
    edit.add_argument('id')
    edit.add_argument('--title')
    edit.add_argument('--notes')
    due = edit.add_mutually_exclusive_group()
    due.add_argument('--due')
    due.add_argument('--no-due', action='store_true')
    for verb in ['complete', 'uncomplete', 'delete']:
        change = sub.add_parser(verb)
        change.add_argument('id')
        if verb == 'delete':
            change.add_argument('--yes', action='store_true')
    return p


def dispatch(service, args):
    if args.command == 'lists':
        return service.lists(args.account)
    if args.command == 'list':
        rows, warnings = service.list(args.list_id, args.account, args.all, args.completed)
        if args.semantic:
            ids = recall_client.rank('cloud-tasks', args.semantic, recall_client.records(rows))
            if ids is None:
                warnings = warnings + [{'account': '', 'message': 'Recall unavailable or warming up; showing text matches'}]
                rows = [row for row in rows if args.semantic.casefold() in json.dumps(row, ensure_ascii=False).casefold()]
            else:
                by_id = {row['id']: row for row in rows}
                rows = [by_id[identity] for identity in ids]
        return rows, warnings
    if args.command == 'show':
        return service.show(args.id)
    if args.command == 'add':
        return service.add(args.title, args.list_id, args.notes, args.due)
    if args.command == 'edit':
        return service.edit(args.id, args.title, args.notes, args.due, args.no_due)
    if args.command in ['complete', 'uncomplete']:
        return service.edit(args.id, completion=args.command == 'complete')
    if args.command == 'delete':
        return service.delete(args.id, args.yes)
    if args.command == 'background':
        return service.background()
    if args.command == 'migrate':
        return service.migrate_legacy()
    if args.command == 'status':
        rows, warnings = service.list()
        return {'accounts': service.accounts(), 'visible_records': len(rows), 'healthy': not warnings}, warnings
    if args.command == 'account':
        if args.action == 'list':
            return service.accounts()
        if args.action == 'add':
            return service.add_account(args.provider, args.name, args.gws_config)
        if args.action == 'login':
            return service.login(args.name)
        if args.action == 'remove':
            if not args.yes:
                service.account(args.name)
                return {'remove': args.name, 'applied': False, 'credentials_deleted': False}
            return service.remove_account(args.name)
    raise Failure('invalid_request', 'Choose a command; see --help')


SKILL = agent_skill.Skill('cloud-tasks', 'cloud-tasks', __version__, Path(__file__).resolve().parent.parent / 'skills' / 'cloud-tasks' / 'SKILL.md')


def skill(action):
    if action is None:
        sys.stdout.write(SKILL.body)
        return None
    home = agent_skill.home()
    if home is None:
        raise Failure('local_error', 'no home directory to install the skill into')
    try:
        return agent_skill.install(home, SKILL) if action == 'install' else agent_skill.remove(home, SKILL)
    except agent_skill.Unmanaged as error:
        raise Failure('skill_unmanaged', str(error)) from None


def summary(args, data):
    """A one-line summary of a command's result, for the envelope and text output."""
    words = [w for w in (args.command, getattr(args, 'action', None)) if w]
    if isinstance(data, list):
        noun = 'lists' if args.command == 'lists' else 'tasks'
        return cli_output.summarize(data, 'candidates' if args.command == 'candidates' else noun)
    return ' '.join(words) if words else 'cloud-tasks'


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    args = parser().parse_args(argv)
    mode = cli_output.mode_of(args)
    home = agent_skill.home()
    if home is not None:
        agent_skill.refresh(home, SKILL)
    try:
        if args.command == 'skill':
            result = skill(args.action)
            if result is not None:
                cli_output.emit(result, mode, f'skill {args.action}')
            return 0
        service = Tasks(args.config)
        if args.app or args.command is None:
            from .app import launch
            return launch(service)
        result = dispatch(service, args)
        warnings = []
        if isinstance(result, tuple):
            result, warnings = result
        return cli_output.emit(result, mode, summary(args, result), warnings)
    except Failure as error:
        raise SystemExit(cli_output.fail(error.code, str(error), mode, details=error.details)) from None
    except (OSError, ValueError) as error:
        raise SystemExit(cli_output.fail('local_error', str(error), mode)) from None
