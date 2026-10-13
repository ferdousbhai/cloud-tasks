import argparse
import json
import sys
from .common import Failure
from .service import Tasks


class Parser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.add_argument('--json', action='store_true', default=argparse.SUPPRESS, help='JSON envelope (also the default)')


def parser():
    p = Parser(prog='cloud-tasks', description='Unified iCloud Reminders and Google Tasks')
    p.add_argument('--config', help='account config JSON (default XDG config directory)')
    p.add_argument('--app', action='store_true', help='open the native GTK app')
    p.add_argument('--version', action='version', version='cloud-tasks 0.1.0')
    sub = p.add_subparsers(dest='command')
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
        return service.list(args.list_id, args.account, args.all, args.completed)
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


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    args = parser().parse_args(argv)
    try:
        service = Tasks(args.config)
        if args.app or args.command is None:
            from .app import launch
            return launch(service)
        result = dispatch(service, args)
        warnings = []
        if isinstance(result, tuple):
            result, warnings = result
        print(json.dumps({'ok': True, 'data': result, 'meta': {'warnings': warnings}}, ensure_ascii=False))
        return 0
    except Failure as error:
        print(json.dumps({'ok': False, 'error': {'code': error.code, 'message': str(error), 'details': error.details}}, ensure_ascii=False))
        raise SystemExit(1)
    except (OSError, ValueError) as error:
        print(json.dumps({'ok': False, 'error': {'code': 'local_error', 'message': str(error)}}))
        raise SystemExit(1)
