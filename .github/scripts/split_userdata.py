#!/usr/bin/env python3
"""把 userdata 镜像切成定长分卷，方便低于 GitHub 单 artifact 的 10 GB 上限。

用法:
    python3 split_userdata.py --chunk-mib 4096 <image> [<image> ...]

每个镜像切出 <image>.000、.001 …，并写一份 <image>.parts.json：
    {"file": ..., "bytes": ..., "sha256": ..., "chunk_bytes": ..., "parts": [{"name":..., "bytes":...}]}
"""
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

CHUNK = 8 << 20


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(CHUNK), b''):
            digest.update(block)
    return digest.hexdigest()


def split(path, chunk_bytes):
    parts = []
    with path.open('rb') as source:
        index = 0
        while True:
            block = source.read(min(chunk_bytes, 1 << 30))
            if not block:
                break
            # 一次最多读 1 GiB，超过 chunk 的部分继续写同一个分卷
            written = 0
            first = True
            while block:
                name = Path(f'{path}.{index:03d}')
                remaining = chunk_bytes - written
                piece, block = block[:remaining], block[remaining:]
                mode = 'wb' if first else 'ab'
                with name.open(mode) as out:
                    out.write(piece)
                written += len(piece)
                first = False
                if written >= chunk_bytes:
                    parts.append((name.name, name.stat().st_size))
                    index += 1
                    written = 0
                    first = True
            if not first:
                parts.append((f'{path}.{index:03d}', (Path(f'{path}.{index:03d}')).stat().st_size))
                index += 1
    return parts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--chunk-mib', type=int, default=4096)
    parser.add_argument('images', nargs='+')
    args = parser.parse_args()
    chunk_bytes = args.chunk_mib << 20
    for image in args.images:
        path = Path(image)
        if not path.is_file():
            raise SystemExit(f'{path}: not a file')
        size = path.stat().st_size
        parts = split(path, chunk_bytes)
        report = {'file': path.name, 'bytes': size, 'sha256': sha256_file(path),
                  'chunk_bytes': chunk_bytes,
                  'parts': [{'name': n, 'bytes': b} for n, b in parts]}
        (path.parent / f'{path.name}.parts.json').write_text(json.dumps(report, indent=2) + '\n')
        print(f'{path}: {size} bytes -> {len(parts)} parts of <= {args.chunk_mib} MiB; '
              f'sha256 {report["sha256"]}')


if __name__ == '__main__':
    main()
