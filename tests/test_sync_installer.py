import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('sync_installer', Path(__file__).parents[1] / 'scripts/sync-installer.py')
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


class InstallerSyncTests(unittest.TestCase):
    def release(self, names):
        return {'tag_name': 'v0.2.16', 'draft': False, 'prerelease': False,
                'assets': [{'name': name, 'digest': 'sha256:' + 'a' * 64, 'size': 12} for name in names]}

    def test_missing_or_partial_installer_does_not_publish(self):
        for names in ([], [sync.NAMES[0]], list(sync.NAMES[:2])):
            with self.subTest(names=names), patch.object(sync, 'api', return_value=self.release(names)), patch.object(sync, 'gh') as gh:
                sync.main(publish=True)
                gh.assert_not_called()

    def test_complete_installer_still_validates_digests(self):
        release = self.release(sync.NAMES)
        release['assets'][0]['digest'] = 'invalid'
        with patch.object(sync, 'api', return_value=release), patch.object(sync, 'gh') as gh:
            with self.assertRaisesRegex(AssertionError, 'Missing asset digest'):
                sync.main(publish=True)
            gh.assert_not_called()

    def test_existing_identical_installer_is_unchanged(self):
        import json
        release = self.release(sync.NAMES)
        with patch.object(sync, 'api', return_value=release), patch.object(sync, 'gh', return_value=json.dumps([[release]])) as gh:
            sync.main(publish=True)
            self.assertEqual(gh.call_count, 1)


if __name__ == '__main__':
    unittest.main()
