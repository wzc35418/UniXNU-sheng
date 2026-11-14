#!/usr/bin/env python3
"""Give the first login a Dock.

The kernel boots the seed's Data volume and loginwindow logs the user in without Setup Assistant, so
nothing ever fills the Dock: it comes up with no tiles and the desktop looks empty. The seed script is
patched where it lives (the tree) so its own ROOT keeps resolving packed_ramdisk and seed-data-grow.py.
"""
import pathlib
import sys

DOCK = '''def add_dock_defaults(mount, name, uid=501, gid=20):
    """The Dock a fresh user needs; loginwindow alone leaves it without tiles."""
    apps = [('Finder', '/System/Library/CoreServices/Finder.app'),
            ('Safari', '/Applications/Safari.app'),
            ('System Settings', '/System/Applications/System Settings.app'),
            ('Terminal', '/System/Applications/Utilities/Terminal.app')]
    tiles = []
    for label, path in apps:
        url = 'file://' + path.replace(' ', '%20') + '/'
        tiles.append({'tile-type': 'file-tile',
                      'tile-data': {'file-label': label,
                                    'file-data': {'_CFURLString': url, '_CFURLStringType': 15}}})
    prefs = {'autohide': False, 'orientation': 'bottom', 'tilesize': 48,
             'mineffect': 'genie', 'show-process-indicators': True,
             'persistent-apps': tiles}
    target = mount / 'Users' / name / 'Library/Preferences/com.apple.dock.plist'
    target.parent.mkdir(parents=True, exist_ok=True)
    write_root(target, plistlib.dumps(prefs, fmt=plistlib.FMT_BINARY), 0o644)


'''

OLD_CALL = "add_home(template, scratch, args.user.split(':', 1)[0])"
NEW_CALL = ("user_name = args.user.split(':', 1)[0]\n"
            "                add_home(template, scratch, user_name)\n"
            "                add_dock_defaults(scratch, user_name)")


def patch(path):
    text = path.read_text()
    if 'add_dock_defaults' in text:
        return False
    if 'def add_home(' not in text or OLD_CALL not in text:
        raise SystemExit(f'{path}: add_home not found')
    text = text.replace('def add_home(', DOCK + 'def add_home(', 1)
    text = text.replace(OLD_CALL, NEW_CALL, 1)
    path.write_text(text)
    return True


def main():
    root = pathlib.Path('..') / 'UniXNU' / 'out' / 'sheng'
    scripts = sorted(root.glob('*/*/tree/scripts/make-macos-data-seed.py'))
    if not scripts:
        raise SystemExit(f'no seed script under {root.resolve()}')
    done = [p for p in scripts if patch(p)]
    print(f'{len(done)} seed script(s) patched, {len(scripts)} found')
    for p in done:
        print('  ', p)
    return 0


if __name__ == '__main__':
    sys.exit(main())
