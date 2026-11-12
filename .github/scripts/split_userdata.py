#!/usr/bin/env python3
"""把 userdata 镜像切成定长分卷，低于 GitHub 单 artifact 的 10 GB 上限。

用法:
    python3 split_userdata.py --chunk-mib 3072 [--delete-source] <image> [<image> ...]

每个镜像切出 <image>.000、.001 …，并写一份 <image>.parts.json：
    {"file": ..., "bytes": ..., "sha256": ..., "chunk_bytes": ..., "parts": [{"name":..., "bytes":...}]}
"""
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

READ = 8 << 20


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(READ), b''):
            digest.update(block)
    return digest.hexdigest()


def split(path, chunk_bytes):
    parts = []
    index = 0
    written = 0
    out = None
    out_path = None

    def close_part():
        nonlocal out, out_path
        if out is not None:
            out.close()
            parts.append({'name': out_path.name, 'bytes': out_path.stat().st_size})
            out = None

    with path.open('rb') as source:
        while True:
            block = source.read(READ)
            if not block:
                break
            if out is None or written >= chunk_bytes:
                close_part()
                out_path = Path(f'{path}.{index:03d}')
                index += 1
                out = out_path.open('wb')
                written = 0
            out.write(block)
            written += len(block)
    close_part()
    return parts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--chunk-mib', type=int, default=3072)
    parser.add_argument('--delete-source', action='store_true',
                        help='切完后删除原镜像，给 runner 腾出空间')
    parser.add_argument('images', nargs='+')
    args = parser.parse_args()
    chunk_bytes = args.chunk_mib << 20

    for image in args.images:
        path = Path(image)
        if not path.is_file():
            raise SystemExit(f'{path}: not a file')
        size = path.stat().st_size
        digest = sha256_file(path)
        parts = split(path, chunk_bytes)
        report = {'file': path.name, 'bytes': size, 'sha256': digest,
                  'chunk_bytes': chunk_bytes, 'parts': parts}
        (path.parent / f'{path.name}.parts.json').write_text(json.dumps(report, indent=2) + '\n')
        print(f'{path}: {size} bytes -> {len(parts)} parts of <= {args.chunk_mib} MiB, '
              f'sha256 {digest}')
        if args.delete_source:
            path.unlink()
            print(f'{path}: removed after splitting')


if __name__ == '__main__':
    main()
