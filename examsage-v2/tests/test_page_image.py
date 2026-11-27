"""Real PDF/PNG fixtures exercise the authorized original-page image boundary."""
import base64
from hashlib import sha256
import io
import json
from pathlib import Path
import random
import subprocess
from zipfile import ZipFile

from PIL import Image, ImageDraw
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, NumberObject
import pytest

from examsage.domain import Document, Manifest, Page, Scope
from examsage.ingest import page_records
from examsage.plugin_tools import CourseBinding, PluginTools, Principal
from examsage.storage import Store


ARGS = {'course_id': 'physics', 'document_id': 'doc', 'page': 1}


def pdf_bytes(width=600, height=400, *, noisy=False):
    writer = PdfWriter()
    page = writer.add_blank_page(width=width, height=height)
    if noisy:
        image = DecodedStreamObject()
        image.set_data(random.Random(11).randbytes(1600 * 1200 * 3))
        image.update({NameObject('/Type'): NameObject('/XObject'), NameObject('/Subtype'): NameObject('/Image'),
                      NameObject('/Width'): NumberObject(1600), NameObject('/Height'): NumberObject(1200),
                      NameObject('/ColorSpace'): NameObject('/DeviceRGB'), NameObject('/BitsPerComponent'): NumberObject(8)})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/XObject'): DictionaryObject({
            NameObject('/Noise'): writer._add_object(image)})})
        commands = f'q {width} 0 0 {height} 0 0 cm /Noise Do Q'
    else:
        # Four edge markers make a silent crop observable in both orientations.
        commands = f'1 0 0 rg 0 0 {width/8} {height/8} re f '
        commands += f'0 1 0 rg {width*7/8} 0 {width/8} {height/8} re f '
        commands += f'0 0 1 rg 0 {height*7/8} {width/8} {height/8} re f '
        commands += f'1 1 0 rg {width*7/8} {height*7/8} {width/8} {height/8} re f'
    stream = DecodedStreamObject()
    stream.set_data(commands.encode('ascii'))
    page[NameObject('/Contents')] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def png_bytes(size=(600, 400)):
    image = Image.new('RGB', size, 'white')
    draw = ImageDraw.Draw(image)
    width, height = size
    for box, color in [((0, 0, width//8, height//8), 'blue'),
                       ((width*7//8, 0, width-1, height//8), 'yellow'),
                       ((0, height*7//8, width//8, height-1), 'red'),
                       ((width*7//8, height*7//8, width-1, height-1), 'lime')]:
        draw.rectangle(box, fill=color)
    output = io.BytesIO()
    image.save(output, format='PNG')
    return output.getvalue()


def image_api(tmp_path, *, suffix='.pdf', source=None, png=None, render_change=None,
              hidden=False, allowed=True, text='Original page', dimensions=(600, 400)):
    assets = tmp_path / 'assets'
    (assets / 'sources').mkdir(parents=True, exist_ok=True)
    if source is None:
        if suffix == '.pdf':
            source = pdf_bytes(*dimensions)
        elif suffix == '.pptx':
            output = io.BytesIO()
            with ZipFile(output, 'w') as archive:
                archive.writestr('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
                archive.writestr('ppt/slides/slide1.xml', '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:cSld/></p:sld>')
            source = output.getvalue()
        else:
            source = b'Original text'
    doc = Document(id='doc', relative_path='Original'+suffix, sha256=sha256(source).hexdigest(),
                   pages=1, kind='lecture', asset='sources/original'+suffix)
    (assets / doc.asset).write_bytes(source)
    render = None
    if suffix == '.pptx' and png is not False:
        png = png or png_bytes(dimensions)
        (assets / 'slides').mkdir(exist_ok=True)
        (assets / 'slides/page.png').write_bytes(png)
        render = {'asset': 'slides/page.png', 'sha256': sha256(png).hexdigest(),
                  'source_sha256': doc.sha256, 'width': dimensions[0], 'height': dimensions[1],
                  'mode': 'static_full_slide', 'renderer': 'fixture', 'animation_steps': 2}
        render.update(render_change or {})
    record = page_records([Page(document_id='doc', number=1, text=text, hidden=hidden,
                                status='failed' if not text else 'text_extracted', render=render,
                                issues=['independent semantic review pending'])], doc)[0]
    store = Store(tmp_path / 'course.sqlite3')
    sid = store.publish('w', Manifest(course_key='c', course_name='C', documents=[doc]), [record], [], {})
    scope = Scope(workspace='w', course='c', snapshot=sid, allowed_sources=['doc'] if allowed else [])
    tools = PluginTools([CourseBinding('physics', store.path, scope)], Principal('owner', frozenset(['physics'])))
    return tools, doc, store, scope


def payload_image(result):
    payload = result['_image_payload']
    assert payload['type'] == 'image' and payload['mimeType'] == 'image/png'
    data = base64.b64decode(payload['data'], validate=True)
    assert len(data) <= 2 * 1024 * 1024
    with Image.open(io.BytesIO(data)) as image:
        assert image.format == 'PNG'
        image.load()
        assert image.size == (result['image']['width'], result['image']['height'])
        assert max(image.size) <= 2048
        assert result['image']['png_sha256'] == sha256(data).hexdigest()
        return image.convert('RGB')


def assert_corners(image):
    width, height = image.size
    assert image.getpixel((width//32, height//32)) == (0, 0, 255)
    assert image.getpixel((width*31//32, height//32)) == (255, 255, 0)
    assert image.getpixel((width//32, height*31//32)) == (255, 0, 0)
    assert image.getpixel((width*31//32, height*31//32)) == (0, 255, 0)


@pytest.mark.parametrize('suffix', ['.pdf', '.pptx'])
@pytest.mark.parametrize('dimensions', [(600, 400), (3000, 1500)])
def test_original_page_is_complete_parseable_and_source_bound_without_writes(tmp_path, suffix, dimensions):
    tools, doc, _, scope = image_api(tmp_path, suffix=suffix, dimensions=dimensions)
    before = {p.relative_to(tmp_path): sha256(p.read_bytes()).hexdigest() for p in tmp_path.rglob('*') if p.is_file()}
    directories = {p.relative_to(tmp_path) for p in tmp_path.rglob('*') if p.is_dir()}
    page = tools.call('get_source_page', ARGS)
    result = tools.call('get_source_image', ARGS)
    assert result['image']['available'] is True
    assert result['image']['source_id'] == page['sources'][0]['source_id']
    assert result['image']['source_sha256'] == doc.sha256
    assert result['image']['filename'] == 'Original'+suffix
    assert result['image']['page'] == 1
    assert result['image']['mode'] == 'static_full_page'
    assert result['snapshot'] == scope.snapshot
    for key in ('source_id', 'record_id', 'content_hash', 'refs', 'review'):
        assert result['sources'][0][key] == page['sources'][0][key]
    assert result['sufficiency'] == page['sufficiency'] == 'unassessed'
    assert result['records'][0]['review'] == page['records'][0]['review']
    assert result['image']['scaled_down'] is (dimensions[0] > 2048)
    assert result['limitations'] and 'semantic' in result['image']['validation']
    assert str(tmp_path) not in json.dumps(result)
    assert_corners(payload_image(result))
    after = {p.relative_to(tmp_path): sha256(p.read_bytes()).hexdigest() for p in tmp_path.rglob('*') if p.is_file()}
    assert after == before
    assert {p.relative_to(tmp_path) for p in tmp_path.rglob('*') if p.is_dir()} == directories


def test_image_does_not_upgrade_failed_text_or_semantic_review(tmp_path):
    tools, _, _, _ = image_api(tmp_path, text='')
    page = tools.call('get_source_page', ARGS)
    result = tools.call('get_source_image', ARGS)
    assert result['image']['available'] is True
    assert result['sufficiency'] == page['sufficiency'] == 'insufficient'
    assert result['records'][0]['review'] == 'candidate'
    assert set(page['limitations']) <= set(result['limitations'])


@pytest.mark.parametrize('suffix', ['.pdf', '.pptx'])
def test_image_projection_hash_verifies_without_changing_canonical_citation(tmp_path, suffix):
    from examsage.domain import digest
    tools, _, _, _ = image_api(tmp_path, suffix=suffix)
    page = tools.call('get_source_page', ARGS)
    result = tools.call('get_source_image', ARGS)
    for response in (page, result):
        record = response['records'][0]
        projection = {key: value for key, value in record.items() if key != 'source_id'}
        assert response['sources'][0]['payload_hash'] == digest(projection)
    assert 'details' not in result['records'][0]
    for key in ('source_id', 'record_id', 'content_hash', 'refs', 'review'):
        assert result['sources'][0][key] == page['sources'][0][key]
    assert tools.call('calculate', {'course_id': 'physics', 'expression': '2^3',
        'inputs': {}, 'units': 'arithmetic only', 'sources': [{
        'record_id': result['sources'][0]['record_id'],
        'source_id': result['sources'][0]['source_id']}]})['value'] == 8


@pytest.mark.parametrize('case', ['hidden', 'scope', 'page', 'document'])
def test_visibility_and_scope_are_checked_before_any_asset_read(tmp_path, monkeypatch, case):
    tools, _, _, _ = image_api(tmp_path, hidden=case == 'hidden', allowed=case != 'scope')
    args = {**ARGS, **({'page': 2} if case == 'page' else {}),
            **({'document_id': 'other'} if case == 'document' else {})}
    # An asset read is a forbidden side effect for all these denied requests.
    original = Path.open
    def guarded(path, *a, **kw):
        if 'assets' in path.parts:
            pytest.fail('Denied page attempted to read an asset')
        return original(path, *a, **kw)
    monkeypatch.setattr(Path, 'open', guarded)
    result = tools.call('get_source_image', args)
    assert result['image']['available'] is False
    assert '_image_payload' not in result
    assert result['sources'] == []


@pytest.mark.parametrize('arguments', [{**ARGS, 'page': False}, {**ARGS, 'page': 0}, {**ARGS, 'page': '1'},
                                      {**ARGS, 'path': 'x'}, {**ARGS, 'url': 'https://example.com'},
                                      {**ARGS, 'max_size': 9}, {**ARGS, 'course_id': 'missing'}])
def test_image_arguments_do_not_accept_paths_limits_or_unregistered_courses(tmp_path, arguments):
    tools, _, _, _ = image_api(tmp_path)
    with pytest.raises(ValueError):
        tools.call('get_source_image', arguments)


@pytest.mark.parametrize('suffix', ['.txt', '.md'])
def test_nonvisual_source_is_explicitly_unavailable(tmp_path, suffix):
    tools, _, _, _ = image_api(tmp_path, suffix=suffix)
    result = tools.call('get_source_image', ARGS)
    assert result['image']['available'] is False
    assert result['image']['reason'] == 'unsupported_source_format'
    assert '_image_payload' not in result


@pytest.mark.parametrize('damage', ['source', 'png', 'png_hash', 'render_source', 'mode', 'width', 'missing',
                                  'format', 'traversal', 'absolute', 'png_bytes', 'pixels', 'source_bytes', 'pdf_size'])
def test_corrupt_unbound_unsafe_or_excessive_assets_never_return_an_image(tmp_path, damage):
    changes = {'png_hash': {'sha256': '0'*64}, 'render_source': {'source_sha256': '0'*64},
               'mode': {'mode': 'embedded_image'}, 'width': {'width': 601},
               'traversal': {'asset': '../outside.png'}, 'absolute': {'asset': str(tmp_path / 'outside.png')}}
    kwargs = {'suffix': '.pptx', 'render_change': changes.get(damage)}
    if damage == 'missing': kwargs['png'] = False
    if damage == 'format':
        output = io.BytesIO()
        Image.new('RGB', (600, 400)).save(output, 'JPEG')
        kwargs['png'] = output.getvalue()
    if damage == 'png_bytes': kwargs['png'] = png_bytes() + b'\0'*(2*1024*1024)
    if damage == 'pixels': kwargs.update(dimensions=(20000, 1000))
    if damage == 'pdf_size': kwargs = {'dimensions': (20000, 20000)}
    tools, doc, _, _ = image_api(tmp_path, **kwargs)
    if damage == 'source': (tmp_path / 'assets' / doc.asset).write_bytes(b'changed')
    if damage == 'png': (tmp_path / 'assets/slides/page.png').write_bytes(b'broken')
    if damage == 'source_bytes':
        with (tmp_path / 'assets' / doc.asset).open('wb') as stream:
            stream.truncate(128*1024*1024 + 1)
    result = tools.call('get_source_image', ARGS)
    assert result['image']['available'] is False
    assert result['image']['reason']
    assert '_image_payload' not in result
    assert str(tmp_path) not in json.dumps(result)


@pytest.mark.parametrize('escape_root', [False, True])
def test_junction_or_symlink_outside_assets_is_rejected_without_reading_target(tmp_path, monkeypatch, escape_root):
    tools, doc, _, _ = image_api(tmp_path)
    link = tmp_path / 'assets' if escape_root else tmp_path / 'assets/sources'
    outside = tmp_path / 'outside'
    link.rename(outside)
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        # Windows directory junctions do not require the symlink privilege.
        process = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(outside)],
                                 capture_output=True, timeout=5)
        assert process.returncode == 0, process.stderr
    original = Path.open
    def guarded(path, *a, **kw):
        if path.is_relative_to(outside):
            pytest.fail('Escaping asset attempted to read its target')
        return original(path, *a, **kw)
    monkeypatch.setattr(Path, 'open', guarded)
    try:
        result = tools.call('get_source_image', ARGS)
        assert result['image']['available'] is False
        assert '_image_payload' not in result
    finally:
        # Only remove this temporary link itself, never recurse into the target.
        link.rmdir()


def test_pdf_output_over_two_mib_is_unavailable_instead_of_retried_or_cropped(tmp_path):
    tools, _, _, _ = image_api(tmp_path, source=pdf_bytes(1600, 1200, noisy=True))
    result = tools.call('get_source_image', ARGS)
    assert result['image']['available'] is False
    assert result['image']['reason'] == 'png_size_limit'
    assert '_image_payload' not in result


def test_png_with_bound_hash_but_invalid_chunk_is_explicitly_unavailable(tmp_path):
    png = bytearray(png_bytes())
    png[png.index(b'IDAT') + 5] ^= 1  # Keep the manifest bound to these invalid PNG bytes.
    tools, _, _, _ = image_api(tmp_path, suffix='.pptx', png=bytes(png))
    result = tools.call('get_source_image', ARGS)
    assert result['image']['available'] is False
    assert '_image_payload' not in result


@pytest.mark.parametrize('redirect_root', [False, True])
def test_controlled_resolver_escape_is_refused_before_target_read(tmp_path, monkeypatch, redirect_root):
    """Resolver injection covers the branch; it is not a real-link acceptance test."""
    tools, doc, _, _ = image_api(tmp_path)
    root = tmp_path / 'assets'
    selected = root if redirect_root else root / doc.asset
    outside = tmp_path / 'outside'
    original_resolve = Path.resolve
    original_open = Path.open
    def controlled_resolve(path, *a, **kw):
        return outside if path == selected else original_resolve(path, *a, **kw)
    def guarded(path, *a, **kw):
        if path.is_relative_to(outside):
            pytest.fail('Rejected resolver result attempted a read')
        return original_open(path, *a, **kw)
    monkeypatch.setattr(Path, 'resolve', controlled_resolve)
    monkeypatch.setattr(Path, 'open', guarded)
    result = tools.call('get_source_image', ARGS)
    assert result['image']['available'] is False
    assert result['image']['reason'] == 'asset_outside_authorized_root'
    assert '_image_payload' not in result


def test_binary_over_text_bound_is_allowed_but_metadata_bound_is_still_enforced(tmp_path, monkeypatch):
    noise = Image.frombytes('RGB', (600, 400), random.Random(12).randbytes(600 * 400 * 3))
    output = io.BytesIO()
    noise.save(output, 'PNG')
    assert 500000 < len(output.getvalue()) < 2*1024*1024
    tools, _, _, _ = image_api(tmp_path / 'binary', suffix='.pptx', png=output.getvalue())
    result = tools.call('get_source_image', ARGS)
    assert result['image']['available'] is True
    assert len(base64.b64decode(result['_image_payload']['data'])) > 500000
    tools, _, _, _ = image_api(tmp_path / 'text', text='Original page conditions. ' * 21000)
    original = Path.open
    def guarded(path, *a, **kw):
        if 'assets' in path.parts:
            pytest.fail('Oversized metadata attempted to read an asset')
        return original(path, *a, **kw)
    monkeypatch.setattr(Path, 'open', guarded)
    with pytest.raises(ValueError, match='Evidence too large'):
        tools.call('get_source_image', ARGS)


def test_mcp_image_is_separate_from_text_and_structured_content(tmp_path):
    from examsage.mcp_server import MCPServer, serve_stdio
    tools, _, _, _ = image_api(tmp_path, suffix='.pptx')
    messages = [dict(jsonrpc='2.0', id=1, method='initialize', params={
        'protocolVersion': '2025-11-25', 'capabilities': {}, 'clientInfo': {'name': 'test', 'version': '1'}}),
        dict(jsonrpc='2.0', method='notifications/initialized'),
        dict(jsonrpc='2.0', id=2, method='tools/call', params={'name': 'get_source_image', 'arguments': ARGS})]
    output = io.BytesIO()
    serve_stdio(MCPServer(tools), io.BytesIO(('\n'.join(json.dumps(m) for m in messages)+'\n').encode()), output)
    result = json.loads(output.getvalue().splitlines()[1])['result']
    assert result['isError'] is False
    assert [c['type'] for c in result['content']] == ['text', 'image']
    assert json.loads(result['content'][0]['text']) == result['structuredContent']
    assert '_image_payload' not in result['structuredContent']
    assert result['content'][1]['data'] not in result['content'][0]['text']
    assert_corners(payload_image({**result['structuredContent'], '_image_payload': result['content'][1]}))
