from copy import deepcopy
from hashlib import sha256
import json

import pytest

from examsage.course_pack import CoursePack, import_pack
from examsage.domain import digest
from examsage.plugin_tools import CourseBinding, PluginTools, Principal, load_library
from test_course_pack import pack_data


def review_pack(root):
    data=pack_data(root)
    raw='Second source condition. PRIVATE_REVIEW_TEXT belongs to a cross-source note.'
    (root/'second.txt').write_text(raw,encoding='utf-8')
    data['manifest']['documents'].append({'id':'second','relative_path':'second.txt','sha256':sha256(raw.encode()).hexdigest(),'kind':'lecture','pages':1})
    hashes={d['id']:d['sha256'] for d in data['manifest']['documents']}
    note={'id':'review-1','origin':'user_note','summary':'PRIVATE_REVIEW_TEXT: check the two sources before using this formula.',
        'targets':[{'document_id':'notes','page':2}],
        'evidence':[{'document_id':d,'page':p,'source_sha256':hashes[d]} for d,p in [('notes',2),('second',1)]]}
    # Marker exists only in the private source and cross-source note.
    data['source_reviews']=[note]
    return data


def imported(tmp_path):
    source=tmp_path/'source'
    data=review_pack(source)
    output=tmp_path/'course'
    result=import_pack(CoursePack.model_validate(data),source,output)
    binding=CourseBinding('demo-math',output/'course.sqlite3',result.scope)
    return data,PluginTools([binding],Principal('owner',frozenset(['demo-math']))),binding


def test_review_is_saved_on_original_page_and_image_without_rewriting_source(tmp_path):
    data,tools,binding=imported(tmp_path)
    result=tools.call('get_source_page',{'course_id':'demo-math','document_id':'notes','page':2})
    record=result['records'][0]
    assert record['text']=='Sum 1..n = n(n+1)/2.\n'
    assert record['refs']==[{'document_id':'notes','page':2,'block_id':None,'bbox':None}]
    assert record['details']['source_reviews'][0]['id']=='review-1'
    assert result['source_reviews'][0]['summary'].startswith('PRIVATE_REVIEW_TEXT')
    assert 'expert' not in result['source_reviews'][0]['review']
    assert any('PRIVATE_REVIEW_TEXT' in s for s in result['limitations'])
    image=tools.call('get_source_image',{'course_id':'demo-math','document_id':'notes','page':2})
    assert image['source_reviews']==result['source_reviews']
    assert image['sources'][0]['source_id']==result['sources'][0]['source_id']
    assert image['sources'][0]['payload_hash']==digest({k:v for k,v in image['records'][0].items() if k!='source_id'})
    source=result['sources'][0]
    calc=tools.call('calculate',{'course_id':'demo-math','expression':'n*(n+1)/2','inputs':{'n':10},'units':'count',
        'sources':[{'record_id':source['record_id'],'source_id':source['source_id']}]})
    assert calc['value']==55 and calc['source_reviews']==result['source_reviews']
    stored=json.loads((tmp_path/'course/manifest.json').read_text(encoding='utf-8'))
    for doc in stored['documents']:
        assert sha256((tmp_path/'course/assets'/doc['asset']).read_bytes()).hexdigest()==doc['sha256']


def test_revoked_support_cannot_leak_review_via_tools_reader_or_export(tmp_path):
    from examsage.course_reader import render_reader
    from examsage.release import publish_release
    data,tools,binding=imported(tmp_path)
    scope=binding.scope.model_copy(update={'allowed_sources':['notes']})
    restricted=PluginTools([CourseBinding('demo-math',binding.database,scope)],Principal('owner',frozenset(['demo-math'])))
    for name,args in [('get_source_page',{'document_id':'notes','page':2}),('get_source_image',{'document_id':'notes','page':2}),
            ('get_record',{'record_id':'notes:p2'}),('search_evidence',{'query':'Sum'})]:
        result=restricted.call(name,{'course_id':'demo-math',**args})
        assert 'PRIVATE_REVIEW_TEXT' not in json.dumps(result)
    page=restricted.call('get_source_page',{'course_id':'demo-math','document_id':'notes','page':2})
    src=page['sources'][0]
    calc=restricted.call('calculate',{'course_id':'demo-math','expression':'2+2','inputs':{},'units':'count',
        'sources':[{'record_id':src['record_id'],'source_id':src['source_id']}]})
    assert 'PRIVATE_REVIEW_TEXT' not in json.dumps(calc)
    reader=tmp_path/'reader.html';render_reader(restricted,reader)
    assert 'PRIVATE_REVIEW_TEXT' not in reader.read_text(encoding='utf-8')
    _,store=restricted._course('demo-math')
    published=tmp_path/'release'
    publish_release(store,scope,tmp_path/'course/assets',published)
    for path in published.rglob('*'):
        if path.is_file():assert b'PRIVATE_REVIEW_TEXT' not in path.read_bytes()


@pytest.mark.parametrize('bad',['hash','page','unbound_target','duplicate','expert'])
def test_invalid_review_contract_is_rejected(tmp_path,bad):
    data=review_pack(tmp_path/'source')
    note=data['source_reviews'][0]
    if bad=='hash':note['evidence'][0]['source_sha256']='0'*64
    elif bad=='page':note['evidence'][0]['page']=99
    elif bad=='unbound_target':note['targets'][0]['page']=1
    elif bad=='duplicate':data['source_reviews'].append(deepcopy(note))
    else:note['review']='expert_checked'
    with pytest.raises(ValueError):CoursePack.model_validate(data)


def make_library(tmp_path):
    from examsage.course_library_import import import_course_library
    source=tmp_path/'draft'
    data=review_pack(source)
    (source/'pack.json').write_text(json.dumps(data),encoding='utf-8')
    library=tmp_path/'library'
    import_course_library(source,['pack.json'],library)
    return source,library,load_library(library,['demo-math'])


def request_for(tools):
    profile=tools.call('get_course_profile',{'course_id':'demo-math'})
    context=profile['review_context']
    page=tools.call('get_source_page',{'course_id':'demo-math','document_id':'notes','page':1})
    ref=page['sources'][0]['refs'][0]
    return {'schema_version':'source-review-request-v1','course_id':'demo-math',**context,
        'reviews':[{'id':'review-2','origin':'user_note','summary':'Keep the positive integer condition.',
            'targets':[{'document_id':'notes','page':1}],
            'evidence':[{'document_id':'notes','page':1,'source_sha256':ref['sha256']}]}]}


def test_apply_request_appends_into_new_draft_then_new_library(tmp_path):
    from examsage.review_application import apply_source_reviews
    from examsage.course_library_import import import_course_library
    source,library,tools=make_library(tmp_path)
    before=sha256((source/'pack.json').read_bytes()).hexdigest()
    request=request_for(tools)
    output=tmp_path/'revised'
    result=apply_source_reviews(source,library,'demo-math',request,output)
    assert result['status']=='review_draft_saved'
    assert sha256((source/'pack.json').read_bytes()).hexdigest()==before
    updated=CoursePack.model_validate_json((output/'pack.json').read_text(encoding='utf-8'))
    assert [r.id for r in updated.source_reviews]==['review-1','review-2']
    import_course_library(output,['pack.json'],tmp_path/'updated-library')
    revised=load_library(tmp_path/'updated-library',['demo-math'])
    old=tools.call('get_source_page',{'course_id':'demo-math','document_id':'notes','page':1})
    new=revised.call('get_source_page',{'course_id':'demo-math','document_id':'notes','page':1})
    assert new['records'][0]['text']==old['records'][0]['text']
    assert new['source_reviews'][0]['id']=='review-2'
    assert old['snapshot']!=new['snapshot']
    with pytest.raises(ValueError,match='snapshot and scope'):
        revised.call('calculate',{'course_id':'demo-math','expression':'1+1','inputs':{},'units':'count',
            'sources':[{'record_id':old['sources'][0]['record_id'],'source_id':old['sources'][0]['source_id']}]})


@pytest.mark.parametrize('bad',['snapshot','scope_digest','pack_digest','workspace','source_bytes','duplicate_id','changed_pack','existing_output'])
def test_stale_forged_or_overwriting_review_application_is_rejected(tmp_path,bad):
    from examsage.review_application import apply_source_reviews
    source,library,tools=make_library(tmp_path)
    request=request_for(tools)
    output=tmp_path/'revised'
    if bad in {'snapshot','scope_digest','pack_digest','workspace'}:request[bad]='wrong'
    elif bad=='source_bytes':(source/'notes.txt').write_text('changed',encoding='utf-8')
    elif bad=='duplicate_id':request['reviews'][0]['id']='review-1'
    elif bad=='changed_pack':
        data=json.loads((source/'pack.json').read_text(encoding='utf-8'));data['manifest']['course_name']='Changed'
        (source/'pack.json').write_text(json.dumps(data),encoding='utf-8')
    else:output.mkdir();(output/'keep.txt').write_text('keep',encoding='utf-8')
    with pytest.raises((ValueError,FileExistsError)):
        apply_source_reviews(source,library,'demo-math',request,output)
    if bad=='existing_output':assert (output/'keep.txt').read_text(encoding='utf-8')=='keep'
    else:assert not output.exists()


def test_cli_saves_review_and_rejects_replay_without_overwriting(tmp_path,capsys):
    from examsage.cli import main
    source,library,tools=make_library(tmp_path)
    request=tmp_path/'request.json'
    request.write_text(json.dumps(request_for(tools)),encoding='utf-8')
    output=tmp_path/'reviewed'
    args=['apply-source-reviews','--draft',str(source),'--library',str(library),'--course-id','demo-math',
          '--request',str(request),'--output',str(output)]
    assert main(args)==0
    assert json.loads(capsys.readouterr().out)['status']=='review_draft_saved'
    before=(output/'pack.json').read_bytes()
    assert main(args)==1
    assert json.loads(capsys.readouterr().out)['status']=='review_failed'
    assert (output/'pack.json').read_bytes()==before


def test_hidden_review_evidence_is_rejected_without_publishing(tmp_path,monkeypatch):
    import examsage.ingest as ingest
    from examsage.domain import Record
    data=review_pack(tmp_path/'source')
    real_page_records=ingest.page_records
    # Model the parser's hidden-slide output, preserving all other source behavior.
    def hide(pages,doc):
        if doc.id=='second':pages[0].hidden=True
        return real_page_records(pages,doc)
    monkeypatch.setattr(ingest,'page_records',hide)
    with pytest.raises(ValueError,match='hidden or unavailable'):
        import_pack(CoursePack.model_validate(data),tmp_path/'source',tmp_path/'output')
    assert not (tmp_path/'output').exists()


def test_application_rejects_evidence_removed_from_current_scope(tmp_path):
    from examsage.review_application import apply_source_reviews
    source,library,tools=make_library(tmp_path)
    request=request_for(tools)
    binding,_=tools._course('demo-math')
    scope=binding.scope.model_copy(update={'allowed_sources':['notes']})
    (binding.database.parent/'current.json').write_text(scope.model_dump_json(),encoding='utf-8')
    restricted=load_library(library,['demo-math'])
    request['scope_digest']=digest(scope.model_dump(mode='json'))
    old=json.loads((source/'pack.json').read_text(encoding='utf-8'))['source_reviews'][0]
    request['reviews'][0]['evidence'].append(old['evidence'][1])
    with pytest.raises(ValueError,match='current scope'):
        apply_source_reviews(source,library,'demo-math',request,tmp_path/'output')
    assert not (tmp_path/'output').exists()


def test_partial_scope_is_readable_but_cannot_export_review_context(tmp_path):
    source,library,tools=make_library(tmp_path)
    binding,_=tools._course('demo-math')
    scope=binding.scope.model_copy(update={'allowed_sources':['notes']})
    restricted=PluginTools([CourseBinding('demo-math',binding.database,scope)],Principal('owner',frozenset(['demo-math'])))
    profile=restricted.call('get_course_profile',{'course_id':'demo-math'})
    assert profile['course_id']=='demo-math'
    assert 'review_context' not in profile
    assert profile['review_write_status']=='scope_incomplete'


def test_application_cannot_reintroduce_revoked_source_from_owner_draft(tmp_path):
    from examsage.review_application import apply_source_reviews
    source,library,tools=make_library(tmp_path)
    request=request_for(tools)  # Includes only notes:p1, not the revoked source.
    binding,_=tools._course('demo-math')
    scope=binding.scope.model_copy(update={'allowed_sources':['notes']})
    (binding.database.parent/'current.json').write_text(scope.model_dump_json(),encoding='utf-8')
    request['scope_digest']=digest(scope.model_dump(mode='json'))
    with pytest.raises(ValueError,match='current scope'):
        apply_source_reviews(source,library,'demo-math',request,tmp_path/'revised')
    assert not (tmp_path/'revised').exists()


def test_filtered_release_cannot_be_used_to_restore_the_original_full_draft(tmp_path):
    from examsage.review_application import apply_source_reviews
    from examsage.release import publish_release
    source,library,tools=make_library(tmp_path)
    request=request_for(tools)
    binding,store=tools._course('demo-math')
    scope=binding.scope.model_copy(update={'allowed_sources':['notes']})
    released=tmp_path/'released'
    publish_release(store,scope,binding.database.parent/'assets',released/'course')
    (released/'library.json').write_text(json.dumps({'courses':[{'slug':'demo-math','data':'course'}]}),encoding='utf-8')
    exported=load_library(released,['demo-math'])
    profile=exported.call('get_course_profile',{'course_id':'demo-math'})
    assert 'review_context' not in profile
    assert profile['review_write_status']=='export_readonly'
    exported_binding,_=exported._course('demo-math')
    request.update(snapshot=exported_binding.scope.snapshot,scope_digest=digest(exported_binding.scope.model_dump(mode='json')))
    with pytest.raises(ValueError):
        apply_source_reviews(source,released,'demo-math',request,tmp_path/'restored')
    assert not (tmp_path/'restored').exists()


@pytest.mark.parametrize('partial', [False, True])
def test_web_chat_carries_currently_permitted_source_notes_into_the_final_answer(tmp_path, partial):
    from examsage.chat_service import CourseTools, validate_answer
    _,tools,binding=imported(tmp_path)
    _,store=tools._course('demo-math')
    scope=binding.scope.model_copy(update={'allowed_sources':['notes']}) if partial else binding.scope
    chat=CourseTools(store,scope)
    page=chat.call('get_source_page',{'document_id':'notes','page':2})
    eid=page['records'][0]['evidence_ids'][0]
    final=validate_answer({'paragraphs':[{'text':'核对本页公式。','kind':'source','citations':[eid]}]},chat)
    assert any('PRIVATE_REVIEW_TEXT' in x for x in final['limitations']) == (not partial)
    if not partial:
        assert final['evidence'][0]['source_reviews'][0]['review']=='unverified_note'
        assert {r['document_id'] for r in final['evidence'][0]['source_reviews'][0]['evidence']}=={'notes','second'}
    else:
        assert 'PRIVATE_REVIEW_TEXT' not in json.dumps(final)

    computed=chat.call('calculate',{'expression':'2+2','inputs':{},'units':'count','source_ids':[eid]})
    calc_only=validate_answer({'paragraphs':[{'text':'结果为四。','kind':'derivation',
        'citations':[computed['evidence_id']]}]},chat)
    entry=calc_only['evidence'][0]
    assert entry.get('source_reviews',[])==final['evidence'][0].get('source_reviews',[])
    assert {r['document_id'] for r in entry['refs']}=={'notes'}
