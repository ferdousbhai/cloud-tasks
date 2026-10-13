"""Provider-backed task lists; never a second local task store."""
from datetime import date, timedelta
from urllib.parse import quote, unquote
from .common import Context, Failure, array, scoped_id, split_id


def google_due(value):
    if not value:
        return None
    if value == 'today':
        value = date.today().isoformat()
    elif value == 'tomorrow':
        value = (date.today() + timedelta(days=1)).isoformat()
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise Failure('unsupported_due_time', 'Google Tasks supports due dates only; use YYYY-MM-DD, today, or tomorrow. No due time was discarded.') from error
    return parsed.isoformat() + 'T00:00:00.000Z'


def task_pair(list_id, task_id):
    return quote(list_id, safe='') + '/' + quote(task_id, safe='')


def google_task(name, list_row, row):
    if not row.get('id'):
        raise Failure('bad_response', 'Google task has no ID')
    due = row.get('due')
    return {'id': scoped_id(name, task_pair(list_row['raw_id'], row['id'])),
            'account': name, 'provider': 'google', 'list_id': list_row['id'], 'list': list_row['name'],
            'title': row.get('title', ''), 'notes': row.get('notes', ''),
            'completed': row.get('status') == 'completed', 'completed_at': row.get('completed'),
            'due': {'date': due[:10], 'time': None, 'all_day': True, 'time_zone': None, 'at': None} if due else None,
            'capabilities': {'due_time': False, 'recurrence': False}, 'source': row}


def cloud_task(name, row, task_list=None):
    if not row.get('id'):
        raise Failure('bad_response', 'Task response lacks an ID; inspect before retrying a write')
    task_list = task_list or {'id': scoped_id(name, row['list']['id']), 'name': row['list']['name']}
    return {**row, 'id': scoped_id(name, row['id']), 'account': name, 'provider': 'icloud',
            'list_id': task_list['id'], 'list': task_list['name'], 'source': row,
            'capabilities': {'due_time': True, 'recurrence': False}}


class Tasks(Context):
    def __init__(self, config=None):
        super().__init__('cloud-tasks', config)

    def provider_lists(self, name, cfg):
        if cfg['provider'] == 'icloud':
            rows = array(self.icloud(['lists']))
            return [{**row, 'id': scoped_id(name, row['id']), 'raw_id': row['id'], 'account': name,
                     'provider': 'icloud', 'capabilities': {'due_time': True}} for row in rows]
        rows = self.pages(name, ['tasks', 'tasklists', 'list'], {'maxResults': 100}, 'items')
        return [{'id': scoped_id(name, row['id']), 'raw_id': row['id'], 'account': name, 'provider': 'google',
                 'name': row['title'], 'capabilities': {'due_time': False}} for row in rows]

    def background(self):
        # Continue existing notification history after retiring the old package.
        self.migrate_legacy()
        if not any(cfg['provider'] == 'icloud' for cfg in self.accounts().values()):
            return {'skipped': True, 'reason': 'no linked Apple account'}
        return self.icloud(['background'])

    def lists(self, account=None):
        return self.collect(self.provider_lists, account)

    def list(self, list_id=None, account=None, include_completed=False, completed=False):
        selected_name = None
        selected_raw = None
        if list_id:
            selected_name, selected_raw = split_id(list_id)
            if account and account != selected_name:
                raise Failure('invalid_request', '--account and --list disagree')
            account = selected_name
        extra_warnings = []
        def load(name, cfg):
            lists = self.provider_lists(name, cfg)
            if selected_raw is not None:
                lists = [row for row in lists if row['raw_id'] == selected_raw]
                if not lists:
                    raise Failure('not_found', 'No list with that ID')
            output = []
            succeeded = 0
            for task_list in lists:
                try:
                    if cfg['provider'] == 'icloud':
                        rows = array(self.icloud(['list', task_list['raw_id'], '--all']))
                        output.extend(cloud_task(name, row, task_list) for row in rows)
                    else:
                        rows = self.pages(name, ['tasks', 'tasks', 'list'], {'tasklist': task_list['raw_id'],
                            'maxResults': 100, 'showCompleted': True, 'showHidden': True, 'showAssigned': True}, 'items')
                        output.extend(google_task(name, task_list, row) for row in rows if not row.get('deleted'))
                    succeeded += 1
                except Failure as error:
                    extra_warnings.append({'account': name, 'list_id': task_list['id'], 'code': error.code, 'message': str(error)})
            if lists and not succeeded:
                raise Failure('lists_unavailable', 'Every selected task list failed')
            return output
        rows, warnings = self.collect(load, account)
        if completed:
            rows = [row for row in rows if row.get('completed')]
        elif not include_completed:
            rows = [row for row in rows if not row.get('completed')]
        rows.sort(key=lambda row: ((row.get('due') or {}).get('date') or '9999-12-31', row['title'].casefold(), row['id']))
        return rows, warnings + extra_warnings

    def target(self, identity):
        name, raw = split_id(identity)
        cfg = self.account(name)
        if cfg['provider'] == 'google':
            pair = raw.split('/', 1)
            if len(pair) != 2 or not all(pair):
                raise Failure('invalid_request', 'Use the complete task ID returned by list')
            return name, {'tasklist': unquote(pair[0]), 'task': unquote(pair[1])}, cfg
        return name, raw, cfg

    def show(self, identity):
        name, target, cfg = self.target(identity)
        if cfg['provider'] == 'icloud':
            row = self.icloud(['show', target])
            return cloud_task(name, row)
        row = self.google(name, ['tasks', 'tasks', 'get'], target)
        task_list = {'raw_id': target['tasklist'], 'id': scoped_id(name, target['tasklist']), 'name': target['tasklist']}
        return google_task(name, task_list, row)

    def add(self, title, list_id, notes=None, due=None):
        if not title.strip():
            raise Failure('invalid_request', 'A task needs a non-empty title')
        name, raw = split_id(list_id)
        cfg = self.account(name)
        if cfg['provider'] == 'icloud':
            args = ['add', title, '--list', raw]
            if notes is not None:
                args += ['--notes', notes]
            if due:
                args += ['--due', due]
            result = self.icloud(args)
            return {**{key: value for key, value in result.items() if key != 'reminder'}, 'task': cloud_task(name, result.get('reminder', {}))}
        body = {'title': title}
        if notes is not None:
            body['notes'] = notes
        if due:
            body['due'] = google_due(due)
        result = self.google(name, ['tasks', 'tasks', 'insert'], {'tasklist': raw}, body)
        return {'action': 'add', 'task': google_task(name, {'raw_id': raw, 'id': list_id, 'name': raw}, result)}

    def edit(self, identity, title=None, notes=None, due=None, no_due=False, completion=None):
        if title is not None and not title.strip():
            raise Failure('invalid_request', 'A task needs a non-empty title')
        if title is None and notes is None and due is None and not no_due and completion is None:
            raise Failure('invalid_request', 'No task change supplied')
        name, target, cfg = self.target(identity)
        if cfg['provider'] == 'icloud':
            if completion is not None:
                result = self.icloud(['complete' if completion else 'uncomplete', target])
                return {**{key: value for key, value in result.items() if key != 'reminder'}, 'task': cloud_task(name, result.get('reminder', {}))}
            args = ['edit', target]
            for key, value in [('title', title), ('notes', notes), ('due', due)]:
                if value is not None:
                    args += ['--' + key, value]
            if no_due:
                args += ['--no-due']
            result = self.icloud(args)
            reminder = result.get('reminder', {})
            if (due or no_due) and reminder.get('alerts'):
                result['warning'] = 'Existing Apple alarms retain their original time; change them on an Apple device.'
            return {**{key: value for key, value in result.items() if key != 'reminder'}, 'task': cloud_task(name, reminder)}
        body = {key: value for key, value in [('title', title), ('notes', notes)] if value is not None}
        if due is not None:
            body['due'] = google_due(due)
        elif no_due:
            body['due'] = None
        if completion is not None:
            body['status'] = 'completed' if completion else 'needsAction'
        result = self.google(name, ['tasks', 'tasks', 'patch'], target, body)
        task_list = {'raw_id': target['tasklist'], 'id': scoped_id(name, target['tasklist']), 'name': target['tasklist']}
        return {'action': 'edit' if completion is None else 'complete' if completion else 'uncomplete', 'task': google_task(name, task_list, result)}

    def delete(self, identity, yes=False):
        name, target, cfg = self.target(identity)
        # Assigned Google tasks can also remove the original task in Docs/Chat.
        preview = self.show(identity)
        if not yes:
            return {'task': preview, 'applied': False, 'warning': 'Deletion affects the source account; assigned Google tasks can also be deleted from Docs/Chat.'}
        if cfg['provider'] == 'icloud':
            self.icloud(['delete', target, '--yes'])
        else:
            self.google(name, ['tasks', 'tasks', 'delete'], target)
        return {'id': identity, 'applied': True}
