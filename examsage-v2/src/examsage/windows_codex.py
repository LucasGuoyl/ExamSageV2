"""Find the current user's registered Windows desktop package after Store updates."""
import ctypes
import os
from pathlib import Path
import re


FAMILY = 'OpenAI.Codex_2p2nqsd0c76g0'
PACKAGE = re.compile(r'OpenAI\.Codex_(\d+\.\d+\.\d+\.\d+)_(?:x64|x86|arm64|neutral)__2p2nqsd0c76g0', re.I)
BUFFER_REQUIRED = 122
UINT = ctypes.c_uint32
WSTRING = ctypes.c_wchar_p


def _package_names():
    if os.name != 'nt':
        return []
    query = ctypes.WinDLL('kernel32').GetPackagesByPackageFamily
    query.argtypes = [WSTRING,ctypes.POINTER(UINT),ctypes.POINTER(WSTRING),ctypes.POINTER(UINT),WSTRING]
    count, size = UINT(), UINT()
    if query(FAMILY,ctypes.byref(count),None,ctypes.byref(size),None) != BUFFER_REQUIRED:
        return []
    names = (WSTRING * count.value)()
    buffer = ctypes.create_unicode_buffer(size.value)
    if query(FAMILY,ctypes.byref(count),names,ctypes.byref(size),buffer) != 0:
        return []
    return list(names[:count.value])


def _install_path(package):
    query = ctypes.WinDLL('kernel32').GetPackagePathByFullName
    query.argtypes = [WSTRING,ctypes.POINTER(UINT),WSTRING]
    size = UINT()
    if query(package,ctypes.byref(size),None) != BUFFER_REQUIRED:
        return None
    buffer = ctypes.create_unicode_buffer(size.value)
    if query(package,ctypes.byref(size),buffer) == 0 and buffer.value:
        return Path(buffer.value)
    return None


def registered_cli():
    versions = []
    for name in _package_names():
        match = PACKAGE.fullmatch(name)
        if match:
            versions.append((tuple(map(int,match.group(1).split('.'))),name))
    for _,name in sorted(versions,reverse=True):
        root = _install_path(name)
        if root is not None and root.is_absolute():
            program = root/'app'/'resources'/'codex.exe'
            if program.is_file():
                return program
    return None
