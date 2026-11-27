import json
from hashlib import sha256
from pathlib import Path
import pytest
from PIL import Image
from examsage.domain import Document, Page, Manifest, Scope
from examsage.ingest import page_records
from examsage.storage import Store
from examsage.search import CourseQueryService


def fixture(tmp_path):
    folder=tmp_path/'supplements';folder.mkdir()
    image=folder/'page.png';Image.new('RGB',(100,80),'white').save(image)
    image_hash=sha256(image.read_bytes()).hexdigest()
    doc=Document(id='doc',relative_path='lecture.pdf',sha256='a'*64,pages=2,kind='lecture')
    pages=[Page(document_id='doc',number=1,text='1'),Page(document_id='doc',number=2,text='')]
    audit={'number':1,'render_sha256':image_hash,'category':'mixed','summary':'板块弯曲的挠度与弯矩关系',
           'transcription':'Flexural rigidity','formulas':[r'D\,d^4w/dx^4=q'],'warnings':['符号需结合原图'],
           'aliases':['板块弯曲','plate bending']}
    item={'number':1,'render_sha256':image_hash,'image':'page.png','native_text_sha256':sha256(b'1').hexdigest(),
          'ocr':{'schema':'page-ocr-v1','source_sha256':doc.sha256,'render_sha256':image_hash,'number':1,
                 'engine':'test','language':'eng','status':'recognized','text':'Flexural rigidity','words':[
                     {'text':'Flexural','confidence':95,'bbox':[0,0,.8,.2]}],'mean_confidence':95,'review':'machine_checked'},
          'audit':audit}
    package={'schema':'page-supplements-v1','source_sha256':doc.sha256,'pages':[item]}
    return folder,doc,pages,package


def save(folder,doc,package):
    (folder/(doc.sha256+'.json')).write_text(json.dumps(package),encoding='utf-8')


def test_supplement_recovers_retrieval_but_preserves_native_and_review_layers(tmp_path):
    from examsage.supplements import apply_supplements
    folder,doc,pages,package=fixture(tmp_path);save(folder,doc,package)
    updated=apply_supplements(doc,pages,folder,tmp_path/'assets')
    assert pages[0].text==updated[0].text=='1'
    assert updated[0].visual_status=='not_reviewed'
    record=page_records(updated,doc)[0]
    assert record.details['raw_text']=='1'
    assert record.details['supplement']['review']=='agent_source_checked'
    assert record.details['supplement']['ocr']['review']=='machine_checked'
    store=Store(tmp_path/'db.sqlite');manifest=Manifest(course_key='physics',course_name='Physics',documents=[doc])
    snapshot=store.publish('local',manifest,[record],[],{})
    scope=Scope(workspace='local',course='physics',snapshot=snapshot,allowed_sources=['doc'])
    result=CourseQueryService(store).search_evidence(scope,'板块弯曲')
    assert result.records and result.records[0].refs[0].page==1
    assert 'words' not in result.records[0].details['supplement']['ocr']


@pytest.mark.parametrize('mutation',['source','image','native','duplicate','out_of_range','hidden','box'])
def test_invalid_supplement_cannot_enter_snapshot(tmp_path,mutation):
    from examsage.supplements import apply_supplements
    folder,doc,pages,package=fixture(tmp_path);item=package['pages'][0]
    if mutation=='source':package['source_sha256']='b'*64
    elif mutation=='image':(folder/'page.png').write_bytes(b'corrupt')
    elif mutation=='native':item['native_text_sha256']='b'*64
    elif mutation=='duplicate':package['pages'].append(item.copy())
    elif mutation=='out_of_range':item['number']=3
    elif mutation=='hidden':pages[0].hidden=True
    elif mutation=='box':item['ocr']['words'][0]['bbox']=[-.1,0,1,1]
    save(folder,doc,package)
    with pytest.raises(ValueError):apply_supplements(doc,pages,folder,tmp_path/'assets')


def test_blank_audit_does_not_invent_or_index_ocr_noise(tmp_path):
    from examsage.supplements import apply_supplements
    folder,doc,pages,package=fixture(tmp_path);item=package['pages'][0]
    item['audit'].update(category='blank',summary='原页为空白，无可恢复的教学内容。',transcription='',formulas=[],aliases=[])
    item['ocr']['text']='hallucinated flux';save(folder,doc,package)
    updated=apply_supplements(doc,pages,folder,tmp_path/'assets')
    record=page_records(updated,doc)[0]
    assert 'hallucinated' not in record.text
    assert record.details['supplement']['resolution']=='blank_confirmed'


def test_low_confidence_ocr_is_retained_for_inspection_but_not_indexed(tmp_path):
    from examsage.supplements import apply_supplements
    folder,doc,pages,package=fixture(tmp_path);item=package['pages'][0]
    item['ocr'].update(text='spuriousOCRtoken',mean_confidence=12)
    save(folder,doc,package)
    record=page_records(apply_supplements(doc,pages,folder,tmp_path/'assets'),doc)[0]
    assert 'spuriousOCRtoken' not in record.text
    assert record.details['supplement']['ocr']['text']=='spuriousOCRtoken'


@pytest.mark.parametrize('surface',['media','export'])
def test_corrupted_supplement_image_is_rejected_on_all_surfaces(tmp_path,surface):
    from fastapi.testclient import TestClient
    from examsage.supplements import apply_supplements
    from examsage.api import create_app
    from examsage.release import publish_release
    folder,doc,pages,package=fixture(tmp_path);save(folder,doc,package)
    assets=tmp_path/'assets';updated=apply_supplements(doc,pages,folder,assets)
    records=page_records(updated,doc);store=Store(tmp_path/'course.sqlite3')
    sid=store.publish('local',Manifest(course_key='physics',course_name='Physics',documents=[doc]),records,[],{})
    scope=Scope(workspace='local',course='physics',snapshot=sid,allowed_sources=['doc'])
    (tmp_path/'current.json').write_text(scope.model_dump_json())
    published=tmp_path/'release';publish_release(store,scope,assets,published)
    client=TestClient(create_app(published),base_url='http://localhost')
    assert client.get('/api/page/doc/1').json()['bundle']['records'][0]['details']['supplement']['ocr']['text']=='Flexural rigidity'
    (assets/updated[0].supplement['image_asset']).write_bytes(b'corrupt')
    if surface=='export':
        with pytest.raises(ValueError,match='supplement'):publish_release(store,scope,assets,tmp_path/'bad-release')
    else:
        live=TestClient(create_app(tmp_path),base_url='http://localhost')
        assert live.get('/api/media/doc/1/0').status_code==404
