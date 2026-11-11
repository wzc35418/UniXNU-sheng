#!/usr/bin/env python3
"""Generate the signed root policies of the current OS profile.

scripts/build-sheng-source-storage.py reads scripts/policies/<profile>/<window>/trusted-key.bin
and manifest.bin. No branch commits those binaries for macos-27.3-26C5035r, so derive them from
the extracted IPSW images: each window's verification.json records the image size and the volume
UUID that the kernel mounts.

Usage: gen_root_policies.py [BUILD_LOG]
Prints the UNIXNU_SOURCE_STORAGE_POLICIES value on stdout.
"""
import json
import re
import subprocess
import sys
from pathlib import Path


def main():
    log_path = Path(sys.argv[1] if len(sys.argv) > 1 else '/tmp/unixnu-build.log')
    log = log_path.read_text(errors='ignore')
    hits = re.findall(r'policies/([A-Za-z0-9._-]+)/([A-Za-z]+)/trusted-key\.bin', log)
    if not hits:
        raise SystemExit('no policy path in the build log')
    profile = hits[-1][0]

    unixnu = (Path('..') / 'UniXNU').resolve()
    tree = next((unixnu / 'out/sheng').glob('*/tree'), None)
    if tree is None or not tree.is_dir():
        raise SystemExit('no staged build tree')

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
    command = [sys.executable, str(tree / 'scripts/make-root-policies.py'),
               '--tree', str(tree), '--output', str(output)]
    for window in windows:
        command += ['--window', window]
    print(' '.join(command), file=sys.stderr)
    subprocess.run(command, check=True)
    print(','.join(chosen))


if __name__ == '__main__':
    main()
