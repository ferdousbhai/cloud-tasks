import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from cloud_tasks import agent_skill
from cloud_tasks.cli import SKILL

ROOT = Path(__file__).resolve().parent.parent


class SkillTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        (self.home / '.claude').mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_ships_the_repository_skill(self):
        self.assertTrue(SKILL.body.startswith('---\nname: cloud-tasks\n'))

    def test_installs_links_refreshes_and_removes(self):
        out = agent_skill.install(self.home, SKILL)
        installed = self.home / '.agents/skills/cloud-tasks/SKILL.md'
        self.assertEqual(installed.read_text(), SKILL.body)
        link = self.home / '.claude/skills/cloud-tasks'
        self.assertEqual(os.readlink(link), '../../.agents/skills/cloud-tasks')
        self.assertEqual(len(out['paths']), 2)
        agent_skill.install(self.home, SKILL)  # idempotent
        (installed.parent / '.installed-version').write_text('0.0.0')
        installed.write_text('old')
        self.assertTrue(agent_skill.refresh(self.home, SKILL))
        self.assertFalse(agent_skill.refresh(self.home, SKILL))
        self.assertEqual(installed.read_text(), SKILL.body)
        agent_skill.remove(self.home, SKILL)
        self.assertFalse(installed.parent.exists())
        self.assertFalse(link.is_symlink())

    def test_never_touches_what_it_did_not_create(self):
        checkout = self.home / 'checkout'
        checkout.mkdir()
        (checkout / 'SKILL.md').write_text('mine')
        (self.home / '.agents/skills').mkdir(parents=True)
        (self.home / '.agents/skills/cloud-tasks').symlink_to(checkout)
        with self.assertRaises(agent_skill.Unmanaged):
            agent_skill.install(self.home, SKILL)
        self.assertFalse(agent_skill.refresh(self.home, SKILL))
        agent_skill.remove(self.home, SKILL)
        self.assertEqual((checkout / 'SKILL.md').read_text(), 'mine')
        (self.home / '.agents/skills/cloud-tasks').unlink()
        (self.home / '.claude/skills/cloud-tasks').mkdir(parents=True)
        out = agent_skill.install(self.home, SKILL)
        self.assertEqual(len(out['notices']), 1)
        agent_skill.remove(self.home, SKILL)
        self.assertTrue((self.home / '.claude/skills/cloud-tasks').is_dir())

    def test_cli_reports_an_unmanaged_skill_as_json(self):
        env = dict(os.environ, HOME=str(self.home), XDG_CONFIG_HOME=str(self.home))
        (self.home / '.agents/skills/cloud-tasks').mkdir(parents=True)
        (self.home / '.agents/skills/cloud-tasks/SKILL.md').write_text('mine')
        result = subprocess.run([sys.executable, str(ROOT / 'bin/cloud-tasks'), 'skill', 'install'], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)['error']['code'], 'skill_unmanaged')
