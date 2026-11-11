#!/usr/bin/env python3
"""Generate the signed root policies of the current OS profile.

scripts/build-sheng-source-storage.py reads scripts/policies/<profile>/<window>/{manifest.bin,
trusted-key.bin,verification.json} and cross-checks the record against the OS profile's pinned
image sha256 and volume UUID. No branch commits those binaries for macos-27.3-26C5035r, so derive
them from the extracted IPSW images.

The generator is run from the UniXNU checkout so its ROOT-relative kit lookup finds
kits/VerifiedRoot; --tree still points at the staged tree for build outputs.

Usage: gen_root_policies.py [BUILD_LOG]
Prints the UNIXNU_SOURCE_STORAGE_POLICIES value on stdout.
"""
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

CHUNK = 8 << 20


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(CHUNK), b''):
            digest.update(block)
    return digest.hexdigest()


def find_tree(unixnu):
    root = unixnu / 'out/sheng'
    if not root.is_dir():
        return None
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
    if not ipsw_root.is_dir():
        raise SystemExit('no extracted IPSW under out/ipsw')

    images = [p for p in ipsw_root.rglob('*') if p.is_file()]
    print(f'candidate images: {len(images)}', file=sys.stderr)

    windows, chosen = [], []
    for name in ('OS', 'SystemOS', 'App'):
        meta_path = policies / name / 'verification.json'
        if not meta_path.is_file():
            continue
        meta = json.loads(meta_path.read_text())
        size = meta.get('image_bytes')
        want = (meta.get('image_sha256') or '').lower()
        volume = meta.get('volume_uuid')
        if not size or not want or not volume:
            continue
        image = None
        for candidate in images:
            if candidate.stat().st_size != size:
                continue
            if sha256_file(candidate) != want:
                continue
            image = candidate
            break
        if image is None:
            print(f'{name}: no extracted image matches {size} bytes / {want[:16]}...', file=sys.stderr)
            continue
        print(f'{name}: {image}', file=sys.stderr)
        windows.append(f'{name}={image}:{volume}')
        chosen.append(name)
    if not windows:
        raise SystemExit('no window matched an extracted image')

    # Write into the device repository so the next tree staging copies the new records too: the
    # driver re-assembles the tree before every build and would otherwise restore the repository's
    # original verification.json, whose trusted_key_sha256 names a different owner key.
    output = Path('scripts/policies') / profile
    command = [sys.executable, str(generator),
               '--tree', str(tree), '--output', str(output)]
    for window in windows:
        command += ['--window', window]
    print('running: ' + ' '.join(command), file=sys.stderr)
    subprocess.run(command, check=True, stdout=sys.stderr, stderr=sys.stderr)

    # make-root-policies.py writes manifest.header.bin; the storage adapter also wants manifest.bin.
    for name in chosen:
        header = output / name / 'manifest.header.bin'
        table = output / name / 'manifest.bin'
        if not header.is_file():
            continue
        keep = header.read_bytes()
        if table.is_file():
            bundle = table.read_bytes()
            if bundle[:544] != keep:
                table.write_bytes(keep + bundle[544:])
        else:
            table.write_bytes(keep)
    for name in chosen:
        record = json.loads((output / name / 'verification.json').read_text())
        print(f"{name}: image_sha256={record.get('image_sha256')} "
              f"volume={record.get('volume_uuid')} blocks={record.get('blocks_verified')} "
              f"real_c={record.get('real_c_signature_and_block_verification')}", file=sys.stderr)
    print(','.join(chosen))


if __name__ == '__main__':
    main()
