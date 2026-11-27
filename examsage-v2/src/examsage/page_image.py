"""Bounded, read-only original-page images, after the caller authorizes the page.

No source path is accepted from a tool argument and no image is cached on disk.
Full static pages remain distinct from semantic or independent content review.
"""
from __future__ import annotations

from hashlib import sha256
import io
import math
from pathlib import Path, PurePosixPath

from PIL import Image
import pypdfium2 as pdfium

from .domain import Document, Record
from .ingest import PDFIUM_LOCK
from .source_paths import source_path


MAX_SOURCE_BYTES = 128 * 1024 * 1024
MAX_PNG_BYTES = 2 * 1024 * 1024
MAX_DOWNLOAD_PNG_BYTES = 16 * 1024 * 1024
MAX_EDGE = 2048
MAX_INPUT_PIXELS = 16_777_216
MAX_PDF_POINTS = 14_400
STATIC_LIMITATION = '完整静态原页不等于图表、公式或逐句语义已验收；需结合文字缺口、来源冲突和审核状态。'


class ImageUnavailable(ValueError):
    """A constant, path-free reason suitable for the tool metadata."""


def _asset(database: Path, relative: str | None) -> Path:
    if not isinstance(relative, str) or not relative or '\0' in relative:
        raise ImageUnavailable('asset_unavailable')
    relative = relative.replace('\\', '/')
    parts = PurePosixPath(relative)
    if parts.is_absolute() or '..' in parts.parts or ':' in relative:
        raise ImageUnavailable('asset_outside_authorized_root')
    # The fixed assets directory itself must not be redirected by a symlink.
    root = database.resolve().parent / 'assets'
    if root.resolve() != root:
        raise ImageUnavailable('asset_outside_authorized_root')
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ImageUnavailable('asset_outside_authorized_root')
    return source_path(path)


def _read(path: Path, limit: int, label: str) -> bytes:
    # Both stat and a bounded read are needed if a file changes during the call.
    if path.stat().st_size > limit:
        raise ImageUnavailable(label + '_size_limit')
    with path.open('rb') as stream:
        content = stream.read(limit + 1)
    if len(content) > limit:
        raise ImageUnavailable(label + '_size_limit')
    return content


def verified_source_bytes(database: Path, doc: Document) -> bytes:
    source = _read(_asset(database, doc.asset), MAX_SOURCE_BYTES, 'source')
    if sha256(source).hexdigest() != doc.sha256:
        raise ImageUnavailable('source_integrity_failure')
    return source


def _encode(image: Image.Image, png_limit: int) -> bytes:
    if max(image.size) > MAX_EDGE or min(image.size) < 1:
        raise ImageUnavailable('output_dimensions_limit')
    output = io.BytesIO()
    image.save(output, format='PNG')
    content = output.getvalue()
    if len(content) > png_limit:
        raise ImageUnavailable('png_size_limit')
    return content


def _pdf(content: bytes, doc: Document, page_number: int, png_limit: int) -> tuple[bytes, dict]:
    # Coordinate this lock with ingest.render_pdf_page: PDFium is not thread safe.
    with PDFIUM_LOCK:
        with pdfium.PdfDocument(content) as pdf:
            if len(pdf) != doc.pages or not 1 <= page_number <= len(pdf):
                raise ImageUnavailable('source_page_count_mismatch')
            page = pdf[page_number - 1]
            try:
                width, height = page.get_size()
                if (not all(math.isfinite(v) and 0 < v <= MAX_PDF_POINTS for v in (width, height))):
                    raise ImageUnavailable('pdf_dimensions_limit')
                scale = min(1.5, MAX_EDGE / max(width, height))
                # PDFium rounds upward; stay inside the edge bound despite float error.
                if max(math.ceil(width * scale), math.ceil(height * scale)) > MAX_EDGE:
                    scale = math.nextafter(scale, 0)
                if not math.isfinite(scale) or scale <= 0:
                    raise ImageUnavailable('pdf_dimensions_limit')
                bitmap = page.render(scale=scale)
                try:
                    image = bitmap.to_pil()
                    try:
                        png = _encode(image,png_limit)
                        metadata = {'width': image.width, 'height': image.height,
                                    'source_dimensions': {'width': width, 'height': height, 'unit': 'pdf_points'},
                                    'raster_scale': scale, 'scaled_down': scale < 1.5,
                                    'source_mode': 'static_pdf_page'}
                    finally:
                        image.close()
                finally:
                    bitmap.close()
            finally:
                page.close()
    return png, metadata


def _slide(database: Path, doc: Document, record: Record, png_limit: int) -> tuple[bytes, dict]:
    render = record.details.get('render')
    if not isinstance(render, dict):
        raise ImageUnavailable('full_slide_render_unavailable')
    if render.get('source_sha256') != doc.sha256 or render.get('mode') != 'static_full_slide':
        raise ImageUnavailable('full_slide_render_unbound')
    width, height = render.get('width'), render.get('height')
    # Check declared dimensions before even opening the decoder.
    if (type(width) is not int or type(height) is not int or width <= 0 or height <= 0
            or width * height > MAX_INPUT_PIXELS):
        raise ImageUnavailable('png_dimensions_limit')
    content = _read(_asset(database, render.get('asset')), png_limit, 'png')
    if sha256(content).hexdigest() != render.get('sha256'):
        raise ImageUnavailable('png_integrity_failure')
    with Image.open(io.BytesIO(content)) as image:
        if image.format != 'PNG' or image.size != (width, height) or image.width * image.height > MAX_INPUT_PIXELS:
            raise ImageUnavailable('png_format_or_dimensions_mismatch')
        image.verify()
    scale = min(1.0, MAX_EDGE / max(width, height))
    target = (max(1, math.floor(width * scale)), max(1, math.floor(height * scale)))
    if scale < 1:
        with Image.open(io.BytesIO(content)) as image:
            image.load()
            resized = image.resize(target, Image.Resampling.LANCZOS)
            try:
                content = _encode(resized,png_limit)
            finally:
                resized.close()
    else:
        # Decode once to reject corrupt IDAT streams, even when no resize is needed.
        with Image.open(io.BytesIO(content)) as image:
            image.load()
    return content, {'width': target[0], 'height': target[1],
                     'source_dimensions': {'width': width, 'height': height, 'unit': 'pixels'},
                     'raster_scale': scale, 'scaled_down': scale < 1,
                     'source_mode': 'static_full_slide'}


def is_original_page(record: Record | None, document_id: str, page: int) -> bool:
    return (record is not None and record.id == f'{document_id}:p{page}' and
            record.kind == 'block' and len(record.refs) == 1 and
            record.refs[0].document_id == document_id and record.refs[0].page == page)


def source_image(database: Path, doc: Document, record: Record, page: int, *,
                 download: bool = False) -> tuple[dict, bytes | None]:
    """Read an already authorized canonical page; never write assets or a cache."""
    metadata = {'available': False, 'mode': 'static_full_page',
                'validation': 'static_page_only_not_semantic_review'}
    suffix = PurePosixPath(doc.relative_path).suffix.lower()
    if suffix not in {'.pdf', '.pptx'}:
        return {**metadata, 'reason': 'unsupported_source_format'}, None
    try:
        source = verified_source_bytes(database, doc)
        png_limit = MAX_DOWNLOAD_PNG_BYTES if download else MAX_PNG_BYTES
        png, rendered = (_pdf(source, doc, page, png_limit) if suffix == '.pdf'
                         else _slide(database, doc, record, png_limit))
        return {**metadata, **rendered, 'available': True, 'png_sha256': sha256(png).hexdigest(),
                'png_bytes': len(png), 'mime_type': 'image/png'}, png
    except ImageUnavailable as exc:
        return {**metadata, 'reason': str(exc)}, None
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, OverflowError, SyntaxError, Image.DecompressionBombError):
        # Decoder exceptions often include local paths; expose only a constant code.
        return {**metadata, 'reason': 'invalid_or_missing_image_asset'}, None
