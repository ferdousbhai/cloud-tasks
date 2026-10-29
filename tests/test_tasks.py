import os
import tempfile
import unittest
from unittest.mock import patch
from cloud_tasks.common import Failure, scoped_id
from cloud_tasks.service import Tasks, google_due, task_pair


class TaskTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = patch.dict(os.environ, {'HOME': self.tmp.name, 'XDG_CONFIG_HOME': self.tmp.name})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.service = Tasks()
        self.service.add_account('google')
        self.service.add_account('icloud')
        self.list_id = scoped_id('google', 'list-id')
        self.task_id = scoped_id('google', task_pair('list-id', 'task-id'))

    def test_due_time_is_rejected_before_any_write(self):
        for due in ['tomorrow 09:00', '2026-10-20T09:00:00Z', '2026-02-30']:
            with patch.object(self.service, 'google') as call:
                with self.assertRaises(Failure):
                    self.service.add('Task', self.list_id, due=due)
                call.assert_not_called()
        self.assertEqual(google_due('2026-10-20'), '2026-10-20T00:00:00.000Z')

    def test_google_patch_preserves_unnamed_fields_and_scopes_target(self):
        with patch.object(self.service, 'google', return_value={'id': 'task-id', 'title': 'Fixture'}) as call:
            self.service.edit(self.task_id, completion=True)
        name, route, params, body = call.call_args.args
        self.assertEqual(name, 'google')
        self.assertEqual(route, ['tasks', 'tasks', 'patch'])
        self.assertEqual(params, {'tasklist': 'list-id', 'task': 'task-id'})
        self.assertEqual(body, {'status': 'completed'})

    def test_partial_lists_preserve_successful_results(self):
        lists = [{'id': self.list_id, 'raw_id': 'list-id', 'account': 'google', 'provider': 'google', 'name': 'Good'},
                 {'id': scoped_id('google', 'bad'), 'raw_id': 'bad', 'account': 'google', 'provider': 'google', 'name': 'Bad'}]
        def pages(_name, _route, params, _field):
            if params['tasklist'] == 'bad':
                raise Failure('offline', 'fixture list failed')
            self.assertTrue(params['showHidden'])
            self.assertTrue(params['showAssigned'])
            return [{'id': 'task-id', 'title': 'Keep me', 'status': 'needsAction', 'due': '2026-10-20T00:00:00Z'},
                    {'id': 'done', 'title': 'Completed', 'status': 'completed'}]
        with patch.object(self.service, 'provider_lists', return_value=lists), patch.object(self.service, 'pages', side_effect=pages):
            rows, warnings = self.service.list(account='google')
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['id'], self.task_id)
            self.assertFalse(rows[0]['capabilities']['due_time'])
            self.assertEqual(warnings[0]['list_id'], lists[1]['id'])
            self.assertEqual(len(self.service.list(account='google', include_completed=True)[0]), 2)

    def test_icloud_due_time_is_forwarded_without_a_google_downgrade(self):
        with patch.object(self.service, 'icloud', return_value={'reminder': {'id': 'Reminder/uuid', 'list': {'id': 'List/uuid', 'name': 'Reminders'}, 'title': 'Dentist'}}) as call:
            self.service.add('Dentist', scoped_id('icloud', 'List/uuid'), due='tomorrow 09:00')
        self.assertEqual(call.call_args.args[0], ['add', 'Dentist', '--list', 'List/uuid', '--due', 'tomorrow 09:00'])

    def test_delete_is_preview_until_explicitly_applied(self):
        with patch.object(self.service, 'show', return_value={'id': self.task_id, 'source': {'assignmentInfo': {}}}), \
             patch.object(self.service, 'google', return_value={}) as call:
            self.assertFalse(self.service.delete(self.task_id)['applied'])
            call.assert_not_called()
            self.assertTrue(self.service.delete(self.task_id, yes=True)['applied'])
            self.assertEqual(call.call_args.args[1], ['tasks', 'tasks', 'delete'])

    def test_account_and_list_mismatch_is_rejected(self):
        with self.assertRaises(Failure):
            self.service.list(self.list_id, account='icloud')

    def test_created_tasks_return_the_same_opaque_ids_as_list(self):
        with patch.object(self.service, 'google', return_value={'id': 'task-id', 'title': 'Task'}):
            result = self.service.add('Task', self.list_id)
            self.assertEqual(result['task']['id'], self.task_id)
        row = {'id': 'Reminder/one', 'title': 'Task', 'list': {'id': 'List/one', 'name': 'Home'}}
        with patch.object(self.service, 'icloud', return_value={'action': 'add', 'reminder': row}):
            result = self.service.add('Task', scoped_id('icloud', 'List/one'))
            self.assertEqual(result['task']['id'], scoped_id('icloud', 'Reminder/one'))
            self.assertNotIn('reminder', result)

    def snapshot(self):
        return {'lists': [{'id': str(i), 'name': f'List {i}', 'color': '#123456', 'open': 1} for i in range(10)],
                'reminders': [{'id': f'task-{i}', 'title': f'Task {i}', 'completed': i % 2 == 0,
                               'list': {'id': str(i), 'name': f'List {i}'}, 'unknown_field': {'keep': True}}
                              for i in range(10)]}

    def test_icloud_listing_uses_one_snapshot_for_every_list(self):
        with patch.object(self.service, 'icloud', return_value=self.snapshot()) as call:
            rows, warnings = self.service.list(account='icloud', include_completed=True)
        call.assert_called_once_with(['snapshot'])
        self.assertEqual(len(rows), 10)
        self.assertEqual(warnings, [])
        self.assertEqual(rows[0]['source']['unknown_field'], {'keep': True})
        self.assertTrue(all(row['list_id'] == scoped_id('icloud', row['source']['list']['id']) for row in rows))

    def test_icloud_snapshot_filters_selected_list_and_completion(self):
        with patch.object(self.service, 'icloud', return_value=self.snapshot()) as call:
            rows, _ = self.service.list(scoped_id('icloud', '3'))
            self.assertEqual([row['id'] for row in rows], [scoped_id('icloud', 'task-3')])
            rows, _ = self.service.list(account='icloud', completed=True)
            self.assertEqual(len(rows), 5)
            self.assertTrue(all(row['completed'] for row in rows))
            with self.assertRaises(Failure):
                self.service.list(scoped_id('icloud', 'missing'))
        self.assertEqual([args.args[0] for args in call.call_args_list], [['snapshot', '--list', '3'], ['snapshot'], ['snapshot', '--list', 'missing']])

    def test_icloud_snapshot_keeps_partial_sync_warning(self):
        snapshot = self.snapshot()
        snapshot['warning'] = 'Skipped an unreadable reminder; cached copy retained'
        with patch.object(self.service, 'icloud', return_value=snapshot):
            rows, warnings = self.service.list(account='icloud')
        self.assertEqual(len(rows), 5)
        self.assertEqual(warnings, [{'account': 'icloud', 'code': 'partial_sync', 'message': snapshot['warning']}])

    def test_invalid_icloud_snapshot_does_not_discard_other_account_results(self):
        valid = self.snapshot()
        for snapshot in [[], {}, {**valid, 'warning': 12}, {**valid, 'reminders': [{'id': 'broken', 'list': {}}]}]:
            with self.subTest(snapshot=snapshot), patch.object(self.service, 'icloud', return_value=snapshot), \
                 patch.object(self.service, 'pages', return_value=[{'id': 'google-task', 'title': 'Google survives', 'status': 'needsAction'}]):
                rows, warnings = self.service.list()
                self.assertEqual([row['title'] for row in rows], ['Google survives'])
                self.assertEqual(len(warnings), 1)
                self.assertEqual(warnings[0]['code'], 'bad_response')

    def test_empty_icloud_snapshot_is_successful(self):
        with patch.object(self.service, 'icloud', return_value={'lists': [], 'reminders': []}):
            self.assertEqual(self.service.list(account='icloud'), ([], []))
