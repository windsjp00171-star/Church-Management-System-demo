"""Python 版本相容：標準函式庫在新版被移除的模組（imghdr、cgi…）不可以再被 import，
否則部署平台一升級 Python，對應功能會靜靜變成 500。"""
import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
# Python 3.12／3.13 移除（或 3.13 移除）的標準函式庫模組
REMOVED = {'imghdr', 'sndhdr', 'cgi', 'cgitb', 'telnetlib', 'pipes', 'crypt', 'audioop', 'nntplib', 'uu',
           'xdrlib', 'asyncore', 'asynchat', 'smtpd', 'imp', 'distutils', 'lib2to3', 'chunk', 'mailcap',
           'msilib', 'nis', 'ossaudiodev', 'spwd', 'aifc', 'sunau'}


def _py_files():
    return [p for p in ROOT.rglob('*.py') if not {'tests', '.git', '.codegraph', 'node_modules'} & set(p.parts)]


def test_no_removed_stdlib_modules_are_imported():
    bad = []
    for p in _py_files():
        for node in ast.walk(ast.parse(p.read_text(encoding='utf-8'))):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                    [node.module or ''] if isinstance(node, ast.ImportFrom) else []
            bad += [f'{p.relative_to(ROOT)}: {n}' for n in names if n.split('.')[0] in REMOVED]
    assert not bad, bad


@pytest.mark.parametrize('data,kind', [
    (b'\x89PNG\r\n\x1a\n' + b'0' * 20, 'png'),
    (b'\xff\xd8\xff\xe0' + b'0' * 20, 'jpeg'),
    (b'GIF89a' + b'0' * 20, 'gif'),
    (b'GIF87a' + b'0' * 20, 'gif'),
    (b'RIFF\x00\x00\x00\x00WEBPVP8 ', 'webp'),
    (b'<?php echo 1; ?>', None),
    (b'RIFF\x00\x00\x00\x00WAVEfmt ', None),
    (b'', None),
])
def test_image_kind_by_header(data, kind):
    from image_kind import image_kind
    assert image_kind(data) == kind


def test_admin_uses_the_shared_image_check():
    src = (ROOT / 'routes' / 'admin.py').read_text(encoding='utf-8')
    assert 'from image_kind import image_kind' in src and 'imghdr' not in src.replace('取代 imghdr', '')
