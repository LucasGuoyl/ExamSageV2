from hashlib import sha256
from io import StringIO
import json

import pytest
from fastapi import HTTPException

from examsage.cli import main
from examsage.domain import Record, SourceRef
from test_source_reviews import imported, make_library
from test_student_web import mount, read_course_route, student


def test_selected_document_cites_canonical_pages_without_private_annotations(tmp_path):
    from examsage.study_file import write_study_text
    _,api,b = imported(tmp_path)
    _,db = api._course('demo-math')
    target = StringIO()
    assert write_study_text(target,db,b.scope,'demo-math',['notes']) == 2
    data = target.getvalue()
    assert 'PRIVATE_REVIEW_TEXT' not in data and 'second.txt' not in data
    for page in (1,2):
        source = api.call('get_source_page',{'course_id':'demo-math','document_id':'notes','page':page})['sources'][0]
        assert source['source_id'] in data and source['refs'][0]['sha256'] in data
    assert 'Sum 1..n = n(n+1)/2.' in data and b.scope.snapshot in data


def test_original_lines_and_missing_text_survive_an_annotated_page():
    from examsage.study_file import page_lines
    refs=[SourceRef(document_id='verse',page=2)]
    row=Record(id='verse:p2',title='verse',kind='block',text='Later commentary',refs=refs,
               details={'raw_text':'窗外\n\n  灯下','supplement':{'audit':{'category':'formula'}}})
    text=page_lines(row,'src_example')
    assert '│ 窗外\n│ \n│   灯下' in text and 'Later commentary' not in text
    assert '另有核查导读' in text and '未知' in text
    row.details={'raw_text':'not usable','extraction_status':'failed'}
    assert 'not usable' not in page_lines(row,'src_example')
    row.details={'supplement':{'audit':{'category':'formula'}}}
    assert 'Later commentary' not in page_lines(row,'src_example')
    assert '请核对原页' in page_lines(row,'src_example')


def test_extracted_control_bytes_are_visible_at_their_original_positions():
    from examsage.study_file import page_lines
    raw = 'h*=cos\x00\n\tA\x12B\x85C'
    row=Record(id='doc:p9',title='nine',kind='block',text=raw,refs=[SourceRef(document_id='doc',page=9)])
    txt=page_lines(row,'src_unchanged')
    assert 'h*=cos〔U+0000〕\n│ \tA〔U+0012〕B〔U+0085〕C' in txt
    assert all(char not in txt for char in ('\x00','\x12','\x85'))
    assert '请核对原页' in txt and 'src_unchanged' in txt
    assert row.text==raw


def test_cli_keeps_finished_output_and_rejects_unavailable_selection(tmp_path):
    _,lib,_=make_library(tmp_path)
    output=tmp_path/'material.txt'
    cmd=['study-file','--library',str(lib),'--course-id','demo-math','--output',str(output)]
    assert main(cmd+['--document','notes'])==0
    saved=sha256(output.read_bytes()).hexdigest()
    assert main(cmd+['--document','second'])==1
    assert sha256(output.read_bytes()).hexdigest()==saved
    second=tmp_path/'incomplete.txt'
    cmd[cmd.index(str(output))]=str(second)
    assert main(cmd+['--document','notes','--document','unregistered'])==1
    assert not second.exists()
    assert main(cmd)==0 and 'second.txt' in second.read_text(encoding='utf8')


def test_cli_rechecks_teacher_selection_before_publishing(tmp_path,monkeypatch):
    from examsage import study_file
    _,lib,tools=make_library(tmp_path)
    binding,_=tools._course('demo-math')
    current=binding.database.parent/'current.json'
    write=study_file.write_study_text
    def during_update(*args):
        count=write(*args)
        current.write_text(binding.scope.model_copy(update={'allowed_sources':['notes']}).model_dump_json())
        return count
    monkeypatch.setattr(study_file,'write_study_text',during_update)
    folder=tmp_path/'student-output'
    assert main(['study-file','--library',str(lib),'--course-id','demo-math',
                 '--document','second','--output',str(folder/'materials.txt')])==1
    assert list(folder.iterdir())==[]


def test_student_download_returns_attachment_and_expires_when_grants_change(tmp_path):
    from examsage.chat_runner import ChatRunner
    from examsage.student_web import create_student_app
    from test_course_pack_formats import import_source,make_pdf
    source=tmp_path/'notes.pdf'
    make_pdf(source)
    import_source(tmp_path,source)
    (tmp_path/'library.json').write_text(json.dumps({'courses':[{'slug':'formats','data':'imported'}]}))
    ws=student(tmp_path/'users','A',['formats'])
    runner=ChatRunner(ws.chats,runtime=object())
    try:
        app=create_student_app(tmp_path/'library.json',ws,chat_runner=runner)
        course=mount(app,'/courses/formats')
        route='/api/study-file/{doc_id}'
        result=read_course_route(course,route,'source')
        assert 'attachment' in result.headers['content-disposition']
        assert result.media_type.startswith('text/plain') and 'notes.pdf' in result.body.decode()
        student(tmp_path/'users','A',[]).remember_public_grants()
        with pytest.raises(HTTPException) as err:
            read_course_route(course,route,'source')
        assert err.value.status_code==409
    finally:
        runner.close()


def test_source_list_can_start_after_a_hidden_title_slide(tmp_path):
    from examsage.api import create_app
    from test_chat_api import endpoint
    from test_course_pack_formats import make_pptx, import_source
    from zipfile import ZipFile
    source=tmp_path/'slides.pptx'
    make_pptx(source)
    # The teacher hides slide 1 and makes slide 2 visible.
    with ZipFile(source) as archive:
        files={name:archive.read(name) for name in archive.namelist()}
    from xml.etree import ElementTree
    for number,visible in ((1,'0'),(2,'1')):
        key=f'ppt/slides/slide{number}.xml'
        root=ElementTree.fromstring(files[key]);root.set('show',visible)
        files[key]=ElementTree.tostring(root)
    with ZipFile(source,'w') as archive:
        for name,data in files.items():
            archive.writestr(name,data)
    import_source(tmp_path,source)
    app=create_app(tmp_path/'imported',course_id='formats',chat_runner=object())
    item=endpoint(app,'/api/documents')()[0]
    assert item['first_visible_page']==2
    file=endpoint(app,'/api/study-file/{doc_id}')('source').body.decode()
    assert '物理页 2　' in file and '物理页 1　' not in file


def test_attached_image_matches_the_plugin_and_the_text_page(tmp_path):
    from base64 import b64decode
    from examsage.api import create_app
    from test_chat_api import endpoint
    from test_course_pack_formats import make_pdf,import_source
    source=tmp_path/'notes.pdf'
    make_pdf(source)
    _,tools=import_source(tmp_path,source)
    app=create_app(tmp_path/'imported',course_id='formats',chat_runner=object())
    attachment=endpoint(app,'/api/study-image/{doc_id}/{number}')('source',1)
    native=tools.call('get_source_image',{'course_id':'formats','document_id':'source','page':1})
    sid=native['image']['source_id']
    assert attachment.body==b64decode(native['_image_payload']['data'])
    assert attachment.headers['x-examsage-source-id']==sid
    assert ('-p1-'+sid[:16]+'.png') in attachment.headers['content-disposition']
    assert sid in endpoint(app,'/api/study-file/{doc_id}')('source').body.decode()
    with pytest.raises(HTTPException) as missing:
        endpoint(app,'/api/study-image/{doc_id}/{number}')('source',3)
    assert missing.value.status_code==404


def test_web_can_download_a_large_verified_original_slide(tmp_path):
    from random import Random
    from io import BytesIO
    from PIL import Image
    from examsage.api import create_app
    from test_chat_api import endpoint
    from test_page_image import ARGS, image_api
    buf = BytesIO()
    with Image.frombytes('RGB',(1024,1024),Random(0).randbytes(3*1024**2)) as image:
        image.save(buf,format='PNG')
    png = buf.getvalue()
    assert len(png) > 2*1024**2
    native,_,_,scope = image_api(tmp_path,suffix='.pptx',png=png,dimensions=(1024,1024))
    (tmp_path/'current.json').write_text(scope.model_dump_json())
    app = create_app(tmp_path,course_id='physics',chat_runner=object())
    native_image = native.call('get_source_image',ARGS)['image']
    assert native_image['reason'] == 'png_size_limit'
    response = endpoint(app,'/api/study-image/{doc_id}/{number}')('doc',1)
    assert response.body == png
    assert response.headers['x-examsage-source-id'] == native_image['source_id']
