import json
from types import SimpleNamespace

import pytest

from examsage.domain import digest
from examsage.knowledge_map import raw_text
from test_knowledge_map import nodes
from test_source_reviews import imported


def test_browse_excludes_hidden_slides_and_speaker_notes(tmp_path):
    from test_course_pack_formats import make_pptx, import_source

    path = tmp_path/'slides.pptx'
    make_pptx(path)
    _, api = import_source(tmp_path, path)
    result = api.call('browse_course_materials', {'course_id':'formats', 'offset':0})
    assert result['visible_pages'] == 1 and len(result['pages']) == 1
    assert result['pages'][0]['page'] == 1 and 'Teacher note.' not in result['pages'][0]['excerpt']
    for page, quote in [(1, 'Teacher note.'), (2, 'Example formula')]:
        topic = nodes()[0]
        topic['support'] = [{'page':page, 'document_id':'source', 'quote':quote}]
        with pytest.raises(ValueError):
            api.call('prepare_knowledge_map', {'course_id':'formats','nodes':[topic]})


def test_browse_large_course_in_numeric_page_order(tmp_path):
    from hashlib import sha256
    from examsage.course_pack import CoursePack, import_pack
    from examsage.plugin_tools import CourseBinding, PluginTools, Principal
    from test_course_pack import pack_data

    source = tmp_path/'source'
    data = pack_data(source)
    raw = '\f'.join('Page ' + str(i) for i in range(1, 15)).encode()
    (source/'notes.txt').write_bytes(raw)
    data['manifest']['documents'][0].update(pages=14, sha256=sha256(raw).hexdigest())
    course = import_pack(CoursePack.model_validate(data), source, tmp_path/'course')
    cid = 'demo-math'
    api = PluginTools([CourseBinding(cid,tmp_path/'course/course.sqlite3',course.scope)], Principal('student',frozenset([cid])))
    first = api.call('browse_course_materials', {'course_id':cid,'offset':0})
    last = api.call('browse_course_materials', {'course_id':cid,'offset':first['next_offset']})
    assert first['visible_pages'] == last['visible_pages'] == 14 and last['next_offset'] is None
    assert [p['page'] for p in first['pages']+last['pages']] == list(range(1,15))


def test_export_revalidates_snapshot_quotes_and_scope(tmp_path):
    from examsage.course_reader import render_map_reader

    _, api, binding = imported(tmp_path)
    cid = binding.course_id
    page_list = api.call('browse_course_materials', {'course_id': cid, 'offset': 0})
    candidate = {key: page_list[key] for key in ('course_id', 'snapshot', 'scope_digest')}
    candidate['nodes'] = nodes()
    assert candidate['scope_digest'] == digest(binding.scope.model_dump(mode='json'))
    destination = tmp_path / 'reader.html'
    for key, bad in [('snapshot', 'stale'), ('course_id', 'another'), ('scope_digest', 'revoked')]:
        with pytest.raises(ValueError):
            render_map_reader(api, cid, {**candidate, key: bad}, destination)
        assert not destination.exists()
    render_map_reader(api, cid, candidate, destination)
    html = destination.read_text(encoding='utf-8')
    data = json.loads(html.split('<script id="course-data" type="application/json">')[1].split('</script>')[0])
    graph = data[0]['knowledge_map']
    assert graph['coverage'] == {'cited_pages': 2, 'visible_pages': 3}
    assert graph['nodes'][1]['support'][0]['source_id'].startswith('src_')
    with pytest.raises(FileExistsError):
        render_map_reader(api, cid, candidate, destination)
    candidate['nodes'][0]['support'][0]['quote'] = 'fabricated'
    with pytest.raises(ValueError):
        render_map_reader(api, cid, candidate, tmp_path/'invalid.html')
    assert not (tmp_path/'invalid.html').exists()


def test_old_augmented_or_failed_page_cannot_ground_generated_commentary():
    old = SimpleNamespace(text='Original. Generated annotation.', details={'visual_review': {'summary': 'Generated annotation.'}})
    assert raw_text(old) == ''
    old.details = {'supplement': {'text': 'Generated annotation.'}}
    assert raw_text(old) == ''
    old.details = {'raw_text':'Original.', 'supplement': {'text': 'Generated annotation.'}}
    assert raw_text(old) == 'Original.'
    old.details['extraction_status'] = 'failed'
    assert raw_text(old) == ''


def test_downloaded_map_is_rechecked_and_server_projection_is_regenerated(tmp_path):
    from examsage.course_reader import render_map_reader
    from examsage.chat_service import CourseTools

    _, api, binding = imported(tmp_path)
    _, store = api._course(binding.course_id)
    graph = CourseTools(store, binding.scope).call('prepare_knowledge_map', {'nodes': nodes()})['knowledge_map']
    graph['coverage']['visible_pages'] = 999
    graph['nodes'][0]['support'][0]['source_id'] = 'forged'
    graph['nodes'][0]['limitations'] = ['forged']
    path = tmp_path/'download.html'
    render_map_reader(api, binding.course_id, graph, path)
    exported = json.loads(path.read_text(encoding='utf-8').split('<script id="course-data" type="application/json">')[1].split('</script>')[0])[0]['knowledge_map']
    assert exported['coverage']['visible_pages'] == 3
    assert 'forged' not in json.dumps(exported)
    assert exported['nodes'][0]['support'][0]['source_id'].startswith('src_')
    graph['nodes'][0]['support'][0]['quote'] = 'wrong source text'
    with pytest.raises(ValueError):
        render_map_reader(api, binding.course_id, graph, tmp_path/'tampered.html')


def test_alias_chat_browse_identity_can_be_used_by_native_exporter(tmp_path):
    from examsage.chat_service import CourseTools
    from examsage.course_reader import render_map_reader
    from examsage.plugin_tools import CourseBinding, PluginTools, Principal

    _, original, binding = imported(tmp_path)
    cid = 'registered-math'
    native = PluginTools([CourseBinding(cid,binding.database,binding.scope)], Principal('student',frozenset([cid])))
    _, store = original._course(binding.course_id)
    chat = CourseTools(store, binding.scope, course_id=cid)
    listing = chat.call('browse_course_materials', {'offset':0})
    proposal = {k:listing[k] for k in ('course_id','scope_digest','snapshot')}
    assert proposal['course_id'] == cid
    render_map_reader(native,cid,{**proposal,'nodes':nodes()},tmp_path/'bound.html')
