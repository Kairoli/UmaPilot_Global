"""Mirror only verified full installers from the official signed-update publisher."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import urllib.request

SOURCE = 'Kairoli/UmaPilot-Releases'
TARGET = 'Kairoli/UmaPilot_Global'
NAMES = ('UmaPilotSetup.exe', 'UmaPilotSetup.sha256', 'setup-info.json')


def gh(*args):
    return subprocess.check_output(['gh', *args], text=True, encoding='utf-8')


def api(path):
    return json.loads(gh('api', path))


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def matches(release, source_assets):
    assets = {a['name']: a for a in release.get('assets', [])}
    return set(assets) == set(NAMES) and all(
        assets[name].get('digest') == source_assets[name]['digest']
        and assets[name]['size'] == source_assets[name]['size'] for name in NAMES)


def main(publish=False):
    source = api(f'repos/{SOURCE}/releases/latest')
    version = source['tag_name']
    assert re.fullmatch(r'v\d+\.\d+\.\d+', version), 'Unexpected version'
    assert not source['draft'] and not source['prerelease']
    assets = {a['name']: a for a in source['assets']}
    missing = [name for name in NAMES if name not in assets]
    if missing:
        # App patches can ship before (or without) a new full installer.
        # Keep the current public installer; a later scheduled run retries.
        print(f'{version}: full installer not available yet; keeping the current download. '
              f'Missing: {", ".join(missing)}')
        return
    for name in NAMES:
        assert re.fullmatch(r'sha256:[0-9a-f]{64}', assets[name].get('digest') or ''), 'Missing asset digest'
    pages = json.loads(gh('api', '--paginate', '--slurp', f'repos/{TARGET}/releases?per_page=100'))
    existing = next((r for page in pages for r in page if r['tag_name'] == version), None)
    if existing and not existing['draft']:
        assert matches(existing, assets), 'Published installer differs; refusing to overwrite it'
        print(f'{TARGET} already has the verified {version} installer')
        return
    with tempfile.TemporaryDirectory(prefix='umapilot-installer-') as temporary:
        folder = Path(temporary)
        for name in NAMES:
            asset = assets[name]
            url = asset['browser_download_url']
            assert url == f'https://github.com/{SOURCE}/releases/download/{version}/{name}'
            with urllib.request.urlopen(url, timeout=120) as incoming, (folder/name).open('wb') as output:
                while chunk := incoming.read(1024 * 1024):
                    output.write(chunk)
            assert (folder/name).stat().st_size == asset['size'], f'Size mismatch: {name}'
            assert 'sha256:' + sha(folder/name) == asset['digest'], f'Digest mismatch: {name}'
        info = json.loads((folder/'setup-info.json').read_text(encoding='utf-8'))
        checksum = (folder/'UmaPilotSetup.sha256').read_text().split()
        assert checksum == [sha(folder/'UmaPilotSetup.exe'), 'UmaPilotSetup.exe']
        assert info['version'] == version and info['sha256'] == checksum[0]
        assert info['privateDataIncluded'] is False and info['sequence'] > 0
        print(f'Verified {version}: {info["downloadMiB"]} MiB, sequence {info["sequence"]}')
        if not publish:
            return
        notes = folder/'notes.md'
        notes.write_text(
            f'## Install UmaPilot {version}\n\n'
            'Download **UmaPilotSetup.exe** below and run it. No Python, Node.js or game files need to be installed separately.\n\n'
            'Windows 10/11 x64 and Edge, Chrome or Brave are required. Choose an empty installation folder, '
            'then sign in with Google or create an UmaPilot account using your email. '
            'Email confirmation codes can be read on another device.\n\n'
            'Existing users should use the app updater and restart. The installer includes the official signed update channel, '
            'so it can receive newer versions after installation.\n\n'
            f'Installer size: **{info["downloadMiB"]} MB**; installed files: approximately **{info["installedMiB"]} MB** '
            '(allow extra space for setup, updates and your data).\n\n'
            'The installer currently has no Authenticode publisher signature. A SHA-256 checksum is provided separately. '
            'GitHub’s “Source code” downloads contain this presentation repository, not the application.\n\n'
            f'[Application changes and validation notes](https://github.com/{SOURCE}/releases/tag/{version})\n', encoding='utf-8')
        if not existing:
            gh('release', 'create', version, '--repo', TARGET, '--draft', '--title', f'UmaPilot {version} — Windows installer', '--notes-file', str(notes))
        else:
            gh('release', 'edit', version, '--repo', TARGET, '--notes-file', str(notes))
        gh('release', 'upload', version, '--repo', TARGET, '--clobber', *(str(folder/name) for name in NAMES))
        draft = next(r for page in json.loads(gh('api', '--paginate', '--slurp', f'repos/{TARGET}/releases?per_page=100')) for r in page if r['tag_name'] == version)
        assert matches(draft, assets), 'Hosted asset verification failed'
        # Do not promote a stale snapshot if the publisher advanced during this job.
        assert api(f'repos/{SOURCE}/releases/latest')['tag_name'] == version, 'Publisher advanced; rerun synchronization'
        gh('release', 'edit', version, '--repo', TARGET, '--draft=false', '--latest')
        assert matches(api(f'repos/{TARGET}/releases/latest'), assets)
        print(f'Published https://github.com/{TARGET}/releases/tag/{version}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--publish', action='store_true')
    main(parser.parse_args().publish)
