"""Source-bound native slide renders; no Office process runs in the web server."""
from hashlib import sha256
import json
from pathlib import Path
from PIL import Image

from .domain import Document, Page


def contained(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError('Slide asset escapes its root')
    return path


def attach_slide_renders(doc: Document, pages: list[Page], folder: Path, assets: Path) -> list[Page]:
    manifest_path = folder / 'manifest.json'
    if not manifest_path.exists():
        return pages
    manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
    if (manifest.get('schema') != 'native-slide-render-v1' or manifest.get('source_sha256') != doc.sha256
            or manifest.get('page_count') != doc.pages or manifest.get('render_mode') != 'static_full_slide'):
        raise ValueError('Slide render source or schema mismatch')
    entries = manifest.get('slides', [])
    if len(entries) != doc.pages or {e['number'] for e in entries} != set(range(1, doc.pages + 1)):
        raise ValueError('Slide render is incomplete')
    by_number = {p.number: p for p in pages}
    result = []
    for item in sorted(entries, key=lambda e: e['number']):
        original = by_number[item['number']]
        if bool(item['hidden']) != original.hidden:
            raise ValueError('Slide visibility mismatch')
        source = contained(folder, item['file'])
        content = source.read_bytes()
        checksum = sha256(content).hexdigest()
        if checksum != item['sha256']:
            raise ValueError('Slide render integrity failure')
        with Image.open(source) as image:
            if image.format != 'PNG' or image.size != (item['width'], item['height']):
                raise ValueError('Slide render format or dimensions mismatch')
            image.verify()
        relative = f'slides/{checksum}.png'
        dest = assets / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() and sha256(dest.read_bytes()).hexdigest() != checksum:
            raise ValueError('Immutable slide asset corrupted')
        if not dest.exists():
            dest.write_bytes(content)
        page = original.model_copy(deep=True)
        page.render = dict(asset=relative, sha256=checksum, source_sha256=doc.sha256,
                           renderer=manifest['renderer'], mode=manifest['render_mode'],
                           width=item['width'], height=item['height'], animation_steps=item['animation_steps'])
        page.issues = [i for i in page.issues if i != 'visual_layout_not_verified']
        page.issues.append('Static full-slide render available; independent content review remains separate.')
        result.append(page)
    return result


def validated_slide_asset(doc: Document, details: dict, assets: Path) -> Path | None:
    render = details.get('render')
    if not isinstance(render, dict) or render.get('source_sha256') != doc.sha256:
        return None
    try:
        path = contained(assets, render['asset'])
        if path.suffix.lower() != '.png' or sha256(path.read_bytes()).hexdigest() != render.get('sha256'):
            return None
        return path
    except (OSError, ValueError, KeyError, TypeError):
        return None
