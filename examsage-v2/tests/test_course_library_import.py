"""Owner-operated batch import: complete library or no published result."""
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

import pytest

from examsage.cli import main
from examsage.plugin_tools import load_library
from test_course_pack import pack_data
from test_course_pack_formats import make_pdf, make_pptx


def write_pack(root, cid):
    data = pack_data(root)
    data['profile']['course_id'] = cid
    data['manifest']['course_key'] = cid
    (root / 'pack.json').write_text(json.dumps(data), encoding='utf-8')
    return data


def run_import(source, output, packs):
    from examsage.course_library_import import import_course_library
    return import_course_library(source, packs, output)


def test_cli_creates_relocatable_library_reader_and_pending_review(tmp_path, capsys):
    source = tmp_path / '资料'
    write_pack(source / '甲', 'algebra')
    write_pack(source / '乙', 'mechanics')
    output = tmp_path / 'new'
    assert main(['import-courses', '--source-root', str(source), '--pack', '甲/pack.json',
                 '--pack', '乙/pack.json', '--output', str(output)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['status'] == 'imported_pending_review'
    assert result['model_called'] is False
    moved = tmp_path / '已搬移'
    output.rename(moved)
    tools = load_library(moved, ['algebra', 'mechanics'])
    courses = tools.call('list_courses', {})['courses']
    assert {c['course_id'] for c in courses} == {'algebra', 'mechanics'}
    report = json.loads((moved / 'review.json').read_text(encoding='utf-8'))
    assert report['semantic_review'] == 'pending'
    assert report['totals']['pages'] == 4
    assert {c['snapshot'] for c in report['courses']} == {c['snapshot'] for c in courses}
    for course in report['courses']:
        assert course['report']['semantic_review'] == 'pending'
        assert course['report']['material_status'] == 'demonstration'
        record = tools.call('get_record', {'course_id': course['course_id'], 'record_id': 'proof'})['records'][0]
        assert record['review'] == 'candidate'
        assert [r['page'] for r in record['refs']] == [1, 2]
    html = (moved / 'course-reader.html').read_text(encoding='utf-8')
    embedded = json.loads(html.split('<script id="course-data" type="application/json">')[1].split('</script>')[0])
    assert {c['course_id'] for c in embedded} == {'algebra', 'mechanics'}
    restricted = load_library(moved, ['algebra'])
    with pytest.raises(ValueError):
        restricted.call('get_record', {'course_id': 'mechanics', 'record_id': 'proof'})


@pytest.mark.parametrize('mutation', ['hash', 'page_count'])
def test_later_pack_failure_leaves_no_library_or_changed_inputs(tmp_path, mutation):
    source = tmp_path / 'inputs'
    write_pack(source / 'first', 'first')
    data = write_pack(source / 'second', 'second')
    second = source / 'second'
    (second / 'notes.txt').write_text('only one page', encoding='utf-8')
    if mutation == 'page_count':
        data['manifest']['documents'][0]['sha256'] = sha256((second / 'notes.txt').read_bytes()).hexdigest()
        (second / 'pack.json').write_text(json.dumps(data), encoding='utf-8')
    baseline = {p.relative_to(source).as_posix(): sha256(p.read_bytes()).hexdigest() for p in source.rglob('*') if p.is_file()}
    output = tmp_path / 'new'
    with pytest.raises(ValueError, match='hash mismatch|page count mismatch'):
        run_import(source, output, ['first/pack.json', 'second/pack.json'])
    assert not output.exists()
    assert not list(tmp_path.glob('.cl-*'))
    assert baseline == {p.relative_to(source).as_posix(): sha256(p.read_bytes()).hexdigest() for p in source.rglob('*') if p.is_file()}


@pytest.mark.parametrize('kind', ['empty', 'duplicate_pack', 'duplicate_id', 'outside', 'absolute'])
def test_invalid_selection_rejected_before_publication(tmp_path, kind):
    source = tmp_path / 'inputs'
    write_pack(source / 'first', 'same')
    write_pack(source / 'second', 'same')
    selections = {'empty': [], 'duplicate_pack': ['first/pack.json', 'first/./pack.json'],
        'duplicate_id': ['first/pack.json', 'second/pack.json'],
        'outside': ['../inputs/first/pack.json'], 'absolute': [str(source / 'first/pack.json')]}
    output = tmp_path / 'new'
    with pytest.raises(ValueError):
        run_import(source, output, selections[kind])
    assert not output.exists()


def test_existing_output_and_legacy_library_are_not_overwritten(tmp_path):
    source = tmp_path / 'inputs'
    write_pack(source, 'math')
    output = tmp_path / 'existing'
    output.mkdir()
    marker = output / 'library.json'
    marker.write_text('{"old":"keep"}', encoding='utf-8')
    with pytest.raises(FileExistsError):
        run_import(source, output, ['pack.json'])
    assert marker.read_text(encoding='utf-8') == '{"old":"keep"}'
    assert sorted(p.name for p in output.iterdir()) == ['library.json']


def test_reader_failure_does_not_publish_partial_library(tmp_path, monkeypatch):
    from examsage import course_reader
    write_pack(tmp_path / 'input', 'math')
    def fail(*args, **kwargs):
        raise OSError('Reader disk failure')
    monkeypatch.setattr(course_reader, 'render_reader', fail)
    with pytest.raises(OSError, match='Reader disk failure'):
        run_import(tmp_path / 'input', tmp_path / 'new', ['pack.json'])
    assert not (tmp_path / 'new').exists()


def test_pdf_pptx_batch_retains_failures_hidden_pages_and_source_access(tmp_path):
    source = tmp_path / '中文资料'
    for cid, maker, suffix in [('new-pdf', make_pdf, '.pdf'), ('new-pptx', make_pptx, '.pptx')]:
        folder = source / cid
        data = write_pack(folder, cid)
        path = folder / ('原课件' + suffix)
        maker(path)
        doc = data['manifest']['documents'][0]
        doc.update(relative_path=path.name, sha256=sha256(path.read_bytes()).hexdigest())
        data['records'] = []
        data['profile']['outcomes'] = []
        (folder / 'pack.json').write_text(json.dumps(data), encoding='utf-8')
    output = tmp_path / 'new'
    run_import(source, output, ['new-pdf/pack.json', 'new-pptx/pack.json'])
    tools = load_library(output, ['new-pdf', 'new-pptx'])
    report = json.loads((output / 'review.json').read_text(encoding='utf-8'))
    assert report['totals']['extraction']['failed_pages'] == 1
    assert report['totals']['extraction']['hidden_pages'] == 1
    # The PDF's first page is also partial: native text is not visual review.
    assert report['totals']['extraction']['partial_pages'] == 3
    text = tools.call('get_source_page', {'course_id': 'new-pdf', 'document_id': 'notes', 'page': 1})
    assert 'Assume x is positive' in text['records'][0]['text']
    hidden = tools.call('get_source_page', {'course_id': 'new-pptx', 'document_id': 'notes', 'page': 2})
    assert hidden['records'] == []
    image = tools.call('get_source_image', {'course_id': 'new-pdf', 'document_id': 'notes', 'page': 1})
    assert image['image']['available'] is True
    assert image['_image_payload']['type'] == 'image'


def test_real_cli_returns_json_and_nonzero_on_invalid_pack(tmp_path):
    from os import environ
    source = tmp_path / 'input'
    write_pack(source, 'math')
    (source / 'notes.txt').write_text('changed', encoding='utf-8')
    result = subprocess.run([sys.executable, '-m', 'examsage', 'import-courses', '--source-root', str(source),
        '--pack', 'pack.json', '--output', str(tmp_path / 'new')], capture_output=True, text=True,
        encoding='utf-8', env={**{k: environ[k] for k in ('SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP') if k in environ},
            'PYTHONPATH': str(Path(__file__).parents[1] / 'src'), 'PYTHONUTF8': '1'}, timeout=20)
    assert result.returncode == 1
    assert json.loads(result.stdout)['status'] == 'import_failed'
    assert not (tmp_path / 'new').exists()


def test_batch_import_does_not_exhaust_windows_path_budget_in_nested_staging(tmp_path):
    source = tmp_path / 'input'
    data = write_pack(source, 'math')
    # Valid final asset near the Win32 limit; nested per-course staging must not
    # turn this ordinary output path into an overlong hidden temporary path.
    padding = max(1, 143 - len(str(tmp_path.resolve())) - len('/library/') - 1)
    output = tmp_path / ('x' * padding) / 'library'
    asset = output / 'courses/course-0001/assets/sources' / (data['manifest']['documents'][0]['sha256'] + '.txt')
    assert len(str(asset.resolve())) < 260
    run_import(source, output, ['pack.json'])
    tools = load_library(output, ['math'])
    assert tools.call('get_record', {'course_id': 'math', 'record_id': 'proof'})['records']
    assert asset.read_bytes() == (source / 'notes.txt').read_bytes()


@pytest.mark.parametrize('format', ['broken_pdf', 'broken_zip', 'broken_xml', 'missing_notes', 'missing_relation'])
def test_cli_reports_malformed_source_formats_without_traceback(tmp_path, capsys, format):
    from zipfile import ZipFile
    source = tmp_path / 'input'
    data = write_pack(source, 'math')
    path = source / ('damaged.pdf' if format == 'broken_pdf' else 'damaged.pptx')
    if format in {'missing_notes', 'missing_relation'}:
        p = 'http://schemas.openxmlformats.org/presentationml/2006/main'
        r = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
        rel = 'http://schemas.openxmlformats.org/package/2006/relationships'
        with ZipFile(path, 'w') as archive:
            archive.writestr('ppt/slides/slide1.xml', f'<p:sld xmlns:p="{p}"><p:cSld/></p:sld>')
            if format == 'missing_notes':
                archive.writestr('ppt/slides/_rels/slide1.xml.rels', f'<Relationships xmlns="{rel}">'
                    f'<Relationship Id="notes" Type="{r}/notesSlide" Target="../notesSlides/missing.xml"/></Relationships>')
            else:
                archive.writestr('ppt/presentation.xml', f'<p:presentation xmlns:p="{p}" xmlns:r="{r}">'
                    '<p:sldIdLst><p:sldId id="1" r:id="missing"/></p:sldIdLst></p:presentation>')
    elif format == 'broken_xml':
        with ZipFile(path, 'w') as archive:
            archive.writestr('ppt/slides/slide1.xml', '<broken')
    else:
        path.write_bytes(b'%PDF-1.4\ntruncated' if format == 'broken_pdf' else b'not a zip')
    data['manifest']['documents'][0].update(relative_path=path.name, sha256=sha256(path.read_bytes()).hexdigest())
    (source / 'pack.json').write_text(json.dumps(data), encoding='utf-8')
    assert main(['import-courses', '--source-root', str(source), '--pack', 'pack.json',
                 '--output', str(tmp_path / 'new')]) == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out)['status'] == 'import_failed'
    assert 'Traceback' not in captured.err
    assert not (tmp_path / 'new').exists()
    assert not list(tmp_path.glob('.cl-*'))
