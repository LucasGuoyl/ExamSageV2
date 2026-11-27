"""Exercise the files a recipient receives, using the base runtime and actual plugin commands."""
import base64
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys._base_executable


def run(args, env, *, stdin=None, success=True):
    result = subprocess.run(args, env=env, input=stdin, capture_output=True, timeout=90)
    if success:
        assert result.returncode == 0, result.stderr.decode(errors='replace') + result.stdout.decode(errors='replace')
    return result


def test_prepare_prints_unicode_directory_through_a_legacy_windows_pipe(tmp_path):
    profile = {"LOCALAPPDATA": str(tmp_path / "profile")}
    for name in ("WINDIR", "SystemRoot", "TEMP", "TMP", "PATH"):
        if name in os.environ:
            profile[name] = os.environ[name]
    archive = tmp_path / "student.zip"
    run([PYTHON, "-I", "-B", ROOT / "tools/build_student_kit.py", archive], profile)
    folder = tmp_path / "学生"
    with ZipFile(archive) as package:
        package.extractall(folder)
    script = ("import runpy, sys; sys.stdout.reconfigure(encoding='cp1252'); "
              "sys.argv = sys.argv[1:]; runpy.run_path(sys.argv[0], run_name='__main__')")
    result = run([PYTHON, "-I", "-B", "-c", script, folder / "kit.py", "prepare"], profile)
    assert Path(result.stdout.decode("utf-8").strip()) == folder / "marketplace"


def call(plugin, env, method, args, *, success=True):
    cfg, = json.loads((plugin/'.mcp.json').read_bytes())['mcpServers'].values()
    wire = [{'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-11-25',
             'capabilities': {}, 'clientInfo': {'name':'student', 'version':'1'}}},
            {'method': 'notifications/initialized'},
            {'id': 2, 'method':'tools/call', 'params': {'name':method, 'arguments':args}}]
    stream = b''.join(json.dumps({'jsonrpc':'2.0', **msg}).encode() + b'\n' for msg in wire)
    command = [cfg['command'], *(arg.replace('${PLUGIN_ROOT}', str(plugin)) for arg in cfg['args'])]
    result = run(command, env, stdin=stream, success=success)
    if not success:
        return result
    return json.loads(result.stdout.splitlines()[-1])['result']


def test_recipient_distribution_moves_reads_pages_and_separates_students(tmp_path):
    from examsage.source_paths import source_path
    archive = tmp_path/'kit.zip'
    env = {k:os.environ[k] for k in ('WINDIR','SystemRoot','TMP','TEMP','PATH') if k in os.environ}
    run([PYTHON, '-I', '-B', ROOT/'tools/build_student_kit.py', archive], env)
    with ZipFile(archive) as z:
        names = z.namelist()
        assert json.loads(z.read('src/examsage/paper_topics.json')) == {}
        assert all(not n.startswith(('data/','.git/')) and not n.endswith('.sqlite3') for n in names)
        recipients = []
        for label in ['A 物理','B 数学']:
            folder = tmp_path/label
            z.extractall(folder)
            profile = dict(env, LOCALAPPDATA=str(folder/'profile'))
            kit = [PYTHON, '-I', '-B', folder/'kit.py']
            run([*kit,'prepare'], profile)
            run([*kit,'prepare'], profile)
            marker = 'Private excerpt ' + label
            document = folder/'lesson.txt'
            document.write_text(marker, encoding='utf-8')
            receipt = json.loads(run([*kit,'import','--name',label,'--subject','test',document],profile).stdout)
            assert 'reader_url' not in receipt and 'study_url' not in receipt
            html = Path(receipt['offline_reader']).read_text('utf8')
            embedded = re.search('<script id="course-data" type="application/json">(.*?)</script>',html,re.S)
            reader_course, = json.loads(embedded[1])
            assert reader_course['course_id'] == 'upload-'+receipt['id'] and marker in str(reader_course['items'])
            plugin = folder/'marketplace/examsage-student-courses'
            courses = call(plugin,profile,'list_courses',{})['structuredContent']['courses']
            assert [(r['course_id'],r['name']) for r in courses] == [('upload-'+receipt['id'], label)]
            query = {'course_id':courses[0]['course_id'], 'query':'Private excerpt'}
            evidence = call(plugin,profile,'search_evidence',query)['structuredContent']
            assert marker in str(evidence['records']) and evidence['sources']
            recipients.append((plugin,profile,courses[0]['course_id']))
    own, profile, _ = recipients[1]
    denied = call(own,profile,'search_evidence',{'course_id':recipients[0][2], 'query':'excerpt'})
    assert denied['isError']
    demo = own.with_name('examsage-student-demos')
    moved = tmp_path/'cached plugin'
    shutil.copytree(source_path(demo),source_path(moved))
    demo.rename(demo.with_name('disabled-demo'))
    courses = call(moved,profile,'list_courses',{})['structuredContent']['courses']
    assert {r['course_id'] for r in courses} == {'demo-'+s for s in ['physics','mathematics','history','literature']}
    page = call(moved,profile,'get_source_page',{'course_id':'demo-physics','document_id':'lesson','page':1})
    assert '200' in str(page['structuredContent']['records']) and page['structuredContent']['sources']
    (moved/'library').rename(moved/'missing')
    assert call(moved,profile,'list_courses',{},success=False).returncode != 0


def test_recipient_formats_and_preparation_integrity(tmp_path):
    from test_course_pack_formats import make_pdf, make_pptx
    from test_course_draft import ordered_pptx
    work = tmp_path/'student'
    archive = tmp_path/'received.zip'
    env = {k:os.environ[k] for k in ('WINDIR','SystemRoot','TMP','TEMP','PATH') if k in os.environ}
    env['LOCALAPPDATA'] = str(tmp_path/'profile')
    run([PYTHON,'-I','-B',ROOT/'tools/build_student_kit.py',archive],env)
    with ZipFile(archive) as z:
        z.extractall(work)
    kit = [PYTHON,'-I','-B',work/'kit.py']
    run([*kit,'prepare'],env)
    pdf = tmp_path/'conditions.pdf'
    slides = tmp_path/'seminar.pptx'
    make_pdf(pdf)
    make_pptx(slides)
    intake = [*kit,'import','--name','Lecture','--subject','Physics',pdf,slides]
    assert run(intake,env,success=False).returncode != 0
    plugin = work/'marketplace/examsage-student-courses'
    assert call(plugin,env,'list_courses',{})['structuredContent']['courses'] == []
    ordered_pptx(slides,show='1')
    with ZipFile(slides) as archive:
        parts = {n:archive.read(n) for n in archive.namelist()}
    marker = b'Example formula with original conditions.'
    parts['ppt/slides/slide1.xml'] = parts['ppt/slides/slide1.xml'].replace(marker,b'Static linear spring formula F=kx.')
    parts['ppt/slides/slide2.xml'] = parts['ppt/slides/slide2.xml'].replace(marker,b'Under the preceding assumptions x=F/k.')
    with ZipFile(slides,'w') as archive:
        for n,data in parts.items():
            archive.writestr(n,data)
    receipt = json.loads(run(intake,env).stdout)
    course = 'upload-'+receipt['id']
    plugin = work/'marketplace/examsage-student-courses'
    for word, path in [('positive',pdf),('formula',slides)]:
        query = call(plugin,env,'search_evidence',{'course_id':course,'query':word})['structuredContent']
        refs = [r for s in query['sources'] for r in s['refs'] if r['filename']==path.name and r['page']==1]
        assert refs, query
        page = {'course_id':course,'document_id':refs[0]['document_id'],'page':1}
        original = call(plugin,env,'get_source_page',page)['structuredContent']
        result = call(plugin,env,'get_source_image',page)
        img = result['structuredContent']['image']
        assert word in str(original['records']).lower()
        if path == pdf:
            assert img['available'] and img['source_id'] == original['sources'][0]['source_id']
            images = [i for i in result['content'] if i['type']=='image']
            assert len(images)==1
            assert base64.b64decode(images[0]['data'],validate=True).startswith(b'\x89PNG\r\n\x1a\n')
        else:
            assert not img['available'] and img['reason']=='full_slide_render_unavailable'
            next_page = call(plugin,env,'get_source_page',{**page,'page':2})['structuredContent']
            assert 'x=F/k' in str(next_page['records']) and next_page['sources'][0]['refs'][0]['page'] == 2
    demo = work/'marketplace/examsage-student-demos'
    for subject,word in [('physics','Hooke'),('mathematics','归纳'),('literature','钥匙'),('history','宣言')]:
        result = call(demo,env,'search_evidence',{'course_id':'demo-'+subject,'query':word})
        assert result['structuredContent']['sources'] and result['structuredContent']['records']
    evidence = demo/'server.py'
    evidence.write_bytes(evidence.read_bytes()+b'\n')
    assert run([*kit,'prepare'],env,success=False).returncode != 0


def test_received_demo_contains_only_selected_authored_pack(tmp_path):
    from examsage.plugin_package import build_package
    from examsage.course_pack import CoursePack, import_pack
    unrelated = tmp_path/'author-library'
    unrelated.mkdir()
    pack_dir = ROOT/'examples/course-packs/physics'
    pack = CoursePack.model_validate_json((pack_dir/'pack.json').read_bytes())
    import_pack(pack,pack_dir,unrelated/'demo-physics')
    (unrelated/'library.json').write_text(json.dumps({'courses':[{'slug':'demo-physics','data':'demo-physics'}]}))
    (unrelated/'another-students-work.txt').write_bytes(b'separate private document')
    (unrelated/'demo-physics/author-notes.txt').write_bytes(b'author private notes')
    output = tmp_path/'plugin'
    with pytest.raises(ValueError,match='bundled examples'):
        build_package(output,unrelated,['demo-physics'],Path(PYTHON),plugin_name='student-demo',recipient=True)
    assert not output.exists()
    build_package(output,None,['demo-physics'],Path(PYTHON),plugin_name='student-demo',recipient=True)
    assert {p.name for p in (output/'library').iterdir()} == {'library.json','demo-physics'}
    assert not (output/'library/demo-physics/author-notes.txt').exists()
    env = {k:os.environ[k] for k in ('WINDIR','SystemRoot','TMP','TEMP') if k in os.environ}
    result = call(output,env,'list_courses',{})['structuredContent']
    assert [row['course_id'] for row in result['courses']] == ['demo-physics']


def test_deep_recipient_profile_reopens_published_database_read_only(tmp_path):
    from examsage.source_paths import source_path
    from examsage.storage import Store
    import sqlite3

    env = {k:os.environ[k] for k in ('WINDIR','SystemRoot','TMP','TEMP') if k in os.environ}
    env['LOCALAPPDATA'] = str(tmp_path/('student space '*4+'#% 学期'))
    archive = tmp_path/'student.zip'
    run([PYTHON,'-I','-B',ROOT/'tools/build_student_kit.py',archive],env)
    app = tmp_path/'received'
    with ZipFile(archive) as zipped:
        zipped.extractall(app)
    kit = [PYTHON,'-I','-B',app/'kit.py']
    run([*kit,'prepare'],env)
    source = tmp_path/'flow.txt'
    source.write_bytes(b'Head gradient equals 0.03.')
    result = json.loads(run([*kit,'import','--name','Water','--subject','Geophysics',source],env).stdout)
    personal = app/'marketplace/examsage-student-courses'
    cid = 'upload-'+result['id']
    assert [c['course_id'] for c in call(personal,env,'list_courses',{})['structuredContent']['courses']] == [cid]
    data = call(personal,env,'search_evidence',{'course_id':cid,'query':'gradient'})['structuredContent']
    assert '0.03' in str(data['records']) and data['sources']
    cached = call(source_path(personal),env,'list_courses',{})['structuredContent']['courses']
    assert [row['course_id'] for row in cached] == [cid]
    database, = source_path(Path(env['LOCALAPPDATA'])).rglob('course.sqlite3')
    assert len(str(database)) > 260
    with Store(database,read_only=True).connect() as conn, pytest.raises(sqlite3.OperationalError,match='readonly'):
        conn.execute('CREATE TABLE unexpected_write (n)')
