#!/usr/bin/env python3
"""Generate the signed root policies of the current OS profile.

scripts/build-sheng-source-storage.py reads scripts/policies/<profile>/<window>/trusted-key.bin
and manifest.bin. No branch commits those binaries for macos-27.3-26C5035r, so derive them from
the extracted IPSW images: each window's verification.json records the image size and the volume
UUID that the kernel mounts.

The generator is run from the UniXNU checkout (not from the staged tree), so its ROOT-relative
kit lookup finds kits/VerifiedRoot; --tree still points at the staged tree for build outputs.

Usage: gen_root_policies.py [BUILD_LOG]
Prints the UNIXNU_SOURCE_STORAGE_POLICIES value on stdout.
"""
import json
import re
import subprocess
import sys
from pathlib import Path


def find_tree(unixnu):
    root = unixnu / 'out/sheng'
    if not root.is_dir():
        return None
    # out/sheng/<profile>/<config>/tree
    candidates = sorted(root.glob('*/*/tree')) + sorted(root.glob('*/tree'))
    return next((path for path in candidates if path.is_dir()), None)


def main():
    log_path = Path(sys.argv[1] if len(sys.argv) > 1 else '/tmp/unixnu-build.log')
    log = log_path.read_text(errors='ignore')
    hits = re.findall(r'policies/([A-Za-z0-9._-]+)/([A-Za-z]+)/trusted-key\.bin', log)
    if not hits:
        raise SystemExit('no policy path in the build log')
    profile = hits[-1][0]

    unixnu = (Path('..') / 'UniXNU').resolve()
    tree = find_tree(unixnu)
    if tree is None:
        raise SystemExit('no staged build tree under out/sheng')

    generator = unixnu / 'scripts/make-root-policies.py'
    if not generator.is_file():
        generator = tree / 'scripts/make-root-policies.py'
    if not generator.is_file():
        raise SystemExit('make-root-policies.py not found')

    policies = Path('scripts/policies') / profile
    ipsw_root = unixnu / 'out/ipsw'
    windows, chosen = [], []
    for name in ('OS', 'SystemOS', 'App'):
        meta_path = policies / name / 'verification.json'
        if not meta_path.is_file():
            continue
        meta = json.loads(meta_path.read_text())
        size = meta.get('image_bytes')
        volume = meta.get('volume_uuid')
        if not size or not volume:
            continue
        image = next((p for p in ipsw_root.rglob('*')
                      if p.is_file() and p.stat().st_size == size), None)
        if image is None:
            print(f'{name}: no extracted image of {size} bytes', file=sys.stderr)
            continue
        windows.append(f'{name}={image}:{volume}')
        chosen.append(name)
    if not windows:
        raise SystemExit('no window matched an extracted image')

    output = tree / 'scripts/policies' / profile
    command = [sys.executable, str(generator),
               '--tree', str(tree), '--output', str(output)]
    for window in windows:
        command += ['--window', window]
    print('running: ' + ' '.join(command), file=sys.stderr)
    subprocess.run(command, check=True, stdout=sys.stderr, stderr=sys.stderr)
    print(','.join(chosen))


if __name__ == '__main__':
    main()
