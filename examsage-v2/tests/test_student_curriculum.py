"""Curriculum declarations from a student's upload remain scoped to its course snapshot."""
from io import BytesIO
import json

import pytest

from examsage.chat_runner import ChatRunner
from examsage.student_web import create_student_app
from examsage.student_workspace import student_tools
from examsage.web_intake import import_selection
from test_chat_api import endpoint
from test_chat_runner import wait_run
from test_student_web import student


SCHOOL = {'curriculum_system':'School programme', 'institution':'North School', 'stage':'高中',
          'syllabus_version':'2025 修订', 'language':'中文 / English'}
COLLEGE = {'curriculum_system':'University modules', 'institution':'College A', 'stage':'本科',
           'syllabus_version':'2026 autumn', 'language':'English'}


def upload(workspace, words, **options):
    return import_selection(workspace.imports, '物理', 'Physics', [('lesson.txt', BytesIO(words.encode()))], **options)


def test_same_name_courses_select_the_right_syllabus_and_original_page(tmp_path):
    owner = student(tmp_path,'student-one',[])
    other = student(tmp_path,'student-two',[])
    publications = [upload(owner,'School example: Hooke spring.',curriculum=SCHOOL),
                    upload(owner,'College example: elastic moduli.',curriculum=COLLEGE)]
    runner = ChatRunner(owner.chats,runtime=object())
    try:
        web = create_student_app(None,owner,chat_runner=runner)
        entries = endpoint(web,'/api/courses')()
        home = endpoint(web,'/')()
        tools = student_tools(None,owner)
        listed = {row['course_id']:row for row in tools.call('list_courses',{})['courses']}
        foreign = student_tools(None,other)
        for pub, values, words in zip(publications,(SCHOOL,COLLEGE),('Hooke','moduli')):
            cid = 'upload-'+pub['id']
            entry = next(e for e in entries if e['url']==pub['study_url'])
            assert all(values[k] in entry['name'] for k in ('curriculum_system','stage','syllabus_version'))
            assert entry['name'] in home
            assert all(listed[cid]['profile'][k] == v for k,v in values.items())
            profile = tools.call('get_course_profile',{'course_id':cid})
            assert all(profile[k] == v for k,v in values.items())
            assert profile['source_review']['semantic_review']=='pending' and profile['outcomes']==[]
            record = tools.call('search_evidence',{'course_id':cid,'query':words})['sources'][0]
            ref = record['refs'][0]
            page = tools.call('get_source_page',{'course_id':cid,'document_id':ref['document_id'],'page':ref['page']})
            assert words in page['records'][0]['text'] and page['sources'][0]['source_id'] == record['source_id']
            with pytest.raises(ValueError):
                foreign.call('get_course_profile',{'course_id':cid})
        old = upload(owner,'Old course without a declared curriculum.')
        prof = tools.call('get_course_profile',{'course_id':'upload-'+old['id']})
        assert prof['syllabus_version']=='unspecified' and prof['institution'] is None
        assert tools.call('get_source_page',{'course_id':'upload-'+old['id'],
            'document_id':prof['source_review']['page_reviews'][0]['document_id'],'page':1})['records']
    finally:
        runner.close()


def test_only_curriculum_registration_fields_are_accepted(tmp_path):
    owner = student(tmp_path, 'registrant', [])
    for invalid in ({'material_status':'demonstration'}, {'stage':{}}, {'language':'x'*201}):
        with pytest.raises(ValueError):
            upload(owner,'Reference material.',curriculum=invalid)
    assert owner.private_catalog() == []
    pub = upload(owner, 'Partial profile.',curriculum={'stage':'  高中  ','institution':' '})
    profile = student_tools(None,owner).call('get_course_profile',{'course_id':'upload-'+pub['id']})
    assert (profile['stage'],profile['institution'],profile['language']) == ('高中',None,'unspecified')


def test_web_tutor_receives_scoped_registration_with_source_grounding(tmp_path):
    owner = student(tmp_path,'student-one',[])
    pub = upload(owner,'Hooke spring: the experiment is static.',curriculum=SCHOOL)
    upload(owner,'Not part of this course.',curriculum=COLLEGE)
    tools = student_tools(None,owner)
    binding,store = tools._course('upload-'+pub['id'])
    contexts = []
    class Tutor:
        def generate(self, context, specs, call, cancel, on_status, **kwargs):
            contexts.append(json.loads(context))
            found = call('search_evidence',{'query':'spring'})
            return {'paragraphs':[{'text':'课件将本例限定为静力实验。','kind':'source',
                                   'citations':[found['records'][0]['evidence_ids'][0]]}]}
    runner = ChatRunner(owner.chats,runtime=Tutor())
    try:
        session = runner.store.create_session(binding.scope)
        run = runner.submit(store,binding.scope,session['id'],'Explain Hooke spring for my syllabus.','curriculum1')
        final = wait_run(runner,binding.scope,run['id'])
        assert final['status']=='completed'
        assert contexts[0].get('course_registration_not_evidence') == SCHOOL
        assert 'College A' not in json.dumps(contexts[0])
        assert final['answer']['evidence'][0]['refs'][0]['page']==1
    finally:
        runner.close()


def test_registration_is_omitted_from_forecasts_and_cannot_displace_a_long_question(tmp_path):
    from examsage.chat_service import build_context
    from examsage.model_runtime import RuntimeFailure
    owner = student(tmp_path, 'forecaster', [])
    pub = upload(owner, 'Question 1 on Heat.',curriculum={'syllabus_version':'TARGET_YEAR_PRIVATE_NOTE'})
    binding,store = student_tools(None,owner)._course('upload-'+pub['id'])
    contexts = []
    class Capture:
        def generate(self, context, specs, call, cancel, on_status, **kwargs):
            contexts.append(json.loads(context))
            raise RuntimeFailure('fixture_done','Finished capturing the model request.')
    runner = ChatRunner(owner.chats,runtime=Capture())
    try:
        session = runner.store.create_session(binding.scope)
        run = runner.submit(store,binding.scope,session['id'],'【历年试卷主题】2025 年，按卷面考年回顾。请给出优先复习主题。','forecast1')
        result = wait_run(runner,binding.scope,run['id'])
        assert result['error']['code']=='fixture_done'
        assert len(contexts)==1 and 'TARGET_YEAR_PRIVATE_NOTE' not in json.dumps(contexts[0])
        assert 'course_registration_not_evidence' not in contexts[0]
        question = 'x' * 46500
        messages = [{'role':'user','content':question}]
        extra = {key: '字' * 200 for key in SCHOOL}
        context = json.loads(build_context(messages, binding.scope.course, registration=extra))
        assert context['user_turns_in_order'][-1]['text']==question
        assert 'course_registration_not_evidence' not in context
    finally:
        runner.close()


def test_same_curriculum_value_in_different_fields_is_distinguishable_without_ids(tmp_path):
    owner = student(tmp_path, 'multicourse', [])
    system = upload(owner, 'Course system example.',curriculum={'curriculum_system':'Cambridge','stage':'Secondary'})
    school = upload(owner, 'School example.',curriculum={'institution':'Cambridge','stage':'Secondary'})
    other_school = upload(owner, 'Other term.',curriculum={'institution':'Cambridge','stage':'Secondary'})
    runner = ChatRunner(owner.chats,runtime=object())
    try:
        app = create_student_app(None,owner,chat_runner=runner)
        names = {row['url']:row['name'] for row in endpoint(app,'/api/courses')()}
        a,b = names[system['study_url']],names[school['study_url']]
        assert '体系 Cambridge' in a and '学校 Cambridge' in b
        assert system['id'][-8:] not in a
        assert school['id'][-8:] in b and other_school['id'][-8:] in names[other_school['study_url']]
    finally:
        runner.close()
