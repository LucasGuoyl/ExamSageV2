from hashlib import sha256
import json
from PIL import Image
import pytest
from examsage.domain import Document, Manifest, Page, Scope
from examsage.ingest import page_records
from examsage.storage import Store


def rendered_fixture(tmp_path):
    source = b'original slide deck'
    doc = Document(id='deck', relative_path='lecture.pptx', sha256=sha256(source).hexdigest(),
                   pages=2, kind='lecture', asset='sources/deck.pptx')
    assets = tmp_path / 'assets'
    (assets / 'sources').mkdir(parents=True)
    (assets / doc.asset).write_bytes(source)
    render_dir = tmp_path / 'slide-renders' / doc.sha256
    render_dir.mkdir(parents=True)
    slides = []
    for n in [1, 2]:
        path = render_dir / f'{n}.png'
        Image.new('RGB', (80, 60), (n*80, 50, 100)).save(path)
        slides.append(dict(number=n, file=path.name, sha256=sha256(path.read_bytes()).hexdigest(),
                           width=80, height=60, hidden=n==2, animation_steps=0))
    manifest = dict(schema='native-slide-render-v1', source_sha256=doc.sha256,
                    renderer='PowerPoint test fixture', render_mode='static_full_slide', page_count=2, slides=slides)
    (render_dir / 'manifest.json').write_text(json.dumps(manifest))
    pages = [Page(document_id='deck', number=n, text=f'original page {n}', hidden=n==2,
                  issues=['visual_layout_not_verified']) for n in [1, 2]]
    return doc, pages, assets, render_dir, manifest


def test_full_slide_attached_without_changing_raw_or_review_status(tmp_path):
    from examsage.slides import attach_slide_renders
    doc, pages, assets, folder, _ = rendered_fixture(tmp_path)
    result = attach_slide_renders(doc, pages, folder, assets)
    assert result[0].text == pages[0].text and pages[0].render is None
    assert result[0].visual_status == 'not_reviewed'
    record = page_records(result, doc)[0]
    assert record.details['render']['source_sha256'] == doc.sha256
    assert (assets / record.details['render']['asset']).is_file()
    assert record.details['render']['asset'] in record.details['assets']
    assert page_records(result, doc)[1].visibility == 'hidden'


@pytest.mark.parametrize('damage', ['source', 'image', 'missing', 'traversal', 'hidden'])
def test_invalid_or_incomplete_render_is_rejected(tmp_path, damage):
    from examsage.slides import attach_slide_renders
    doc, pages, assets, folder, manifest = rendered_fixture(tmp_path)
    if damage == 'source': manifest['source_sha256'] = 'b'*64
    if damage == 'image': (folder / '1.png').write_bytes(b'corrupt')
    if damage == 'missing': manifest['slides'].pop()
    if damage == 'traversal': manifest['slides'][0]['file'] = '../1.png'
    if damage == 'hidden': manifest['slides'][1]['hidden'] = False
    (folder / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError): attach_slide_renders(doc, pages, folder, assets)


def test_native_preview_survives_export_and_hidden_pages_remain_unavailable(tmp_path):
    from examsage.slides import attach_slide_renders
    from examsage.api import create_app
    from examsage.release import publish_release
    from fastapi.testclient import TestClient
    doc, pages, assets, folder, _ = rendered_fixture(tmp_path)
    records = page_records(attach_slide_renders(doc, pages, folder, assets), doc)
    store = Store(tmp_path / 'course.sqlite3')
    manifest = Manifest(course_key='c', course_name='C', documents=[doc])
    sid = store.publish('w', manifest, records, [], {})
    scope = Scope(workspace='w', course='c', snapshot=sid, allowed_sources=['deck'])
    (tmp_path / 'current.json').write_text(scope.model_dump_json())
    client = TestClient(create_app(tmp_path), base_url='http://localhost')
    page = client.get('/api/page/deck/1').json()
    assert page['preview_kind'] == 'pptx_full_slide'
    assert client.get(page['preview_url']).headers['content-type'] == 'image/png'
    assert page['media_urls'] == []
    assert client.get('/api/preview/deck/2').status_code == 404
    release = tmp_path / 'release'
    publish_release(store, scope, assets, release)
    reopened = TestClient(create_app(release), base_url='http://localhost')
    assert reopened.get('/api/preview/deck/1').content == client.get(page['preview_url']).content
    (assets / records[0].details['render']['asset']).write_bytes(b'corrupt')
    assert client.get('/api/preview/deck/1').status_code == 404
    assert client.get('/api/media/deck/1/0').status_code == 404
    with pytest.raises(ValueError, match='render'):
        publish_release(store, scope, assets, tmp_path / 'corrupt-release')
