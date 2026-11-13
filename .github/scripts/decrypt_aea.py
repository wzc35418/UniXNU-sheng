#!/usr/bin/env python3
"""把 out/ipsw 下所有 .aea 解密成明文镜像。

`unixnu ipsw fetch` 只做原始解包；政策生成要按 sha256 匹配**解密后**的镜像
（Cryptex1,SystemOS 是 AEA 加密的），所以这里直接调用驱动自己的 decrypt_aea()。

用法（在 device 目录下执行）： python3 .github/scripts/decrypt_aea.py
"""
import sys
from pathlib import Path

workspace = Path(__file__).resolve().parents[3]
unixnu = (workspace / 'UniXNU').resolve()
sys.path.insert(0, str(unixnu / 'scripts'))

from unixnu.ipsw import decrypt_aea  # noqa: E402

root = unixnu / 'out/ipsw'
if not root.is_dir():
    raise SystemExit(f'no IPSW cache at {root}')

decrypted = 0
for path in sorted(root.rglob('*.aea')):
    plain = path.with_suffix('')
    if plain.is_file() and plain.stat().st_size > 0:
        print(f'plain image present: {plain.name} ({plain.stat().st_size} bytes)')
        continue
    print(f'decrypting {path.name} ({path.stat().st_size} bytes) ...')
    decrypt_aea(path)
    decrypted += 1
    if plain.is_file():
        print(f'  -> {plain.name} ({plain.stat().st_size} bytes)')

if not decrypted:
    print('no AEA archive needed decryption')
