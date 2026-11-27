import os
from pathlib import Path
from urllib.parse import quote


def source_path(path: Path) -> Path:
    """Absolute filesystem spelling for source copies and their staging trees."""
    value = str(path.resolve())
    if os.name == 'nt' and not value.startswith('\\\\?\\'):
        value = '\\\\?\\UNC\\' + value[2:] if value.startswith('\\\\') else '\\\\?\\' + value
    return Path(value)


def sqlite_readonly_uri(path: Path) -> str:
    path = source_path(path)
    # SQLite must treat a Windows device prefix as part of the filename.
    uri = 'file:' + quote(str(path), safe='') if os.name == 'nt' else path.as_uri()
    return uri + '?mode=ro'
