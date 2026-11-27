from test_core import example


def test_wrong_page_not_counted_as_supported_and_human_status_pending(tmp_path):
    from examsage.evaluate import evaluate
    from examsage.domain import Scope
    from examsage.search import CourseQueryService
    store,m,r=example(tmp_path)
    sid=store.publish('w',m,[r],[],{})
    scope=Scope(workspace='w',course='c',snapshot=sid,allowed_sources=['doc'])
    cases={'version':'test','cases':[{'id':'x','split':'reserved','query':'Darcy','evidence':[{'source':'a.pdf','pages':[2]}]}]}
    report=evaluate(cases,CourseQueryService(store),scope)
    assert report['passed']==0
    assert report['human_acceptance']=='pending'
    assert report['results'][0]['matched_groups']==[False]


def test_bundle_missing_state_is_required_for_missing_cases(tmp_path):
    from examsage.evaluate import evaluate
    from examsage.domain import Scope
    from examsage.search import CourseQueryService
    store,m,r=example(tmp_path)
    sid=store.publish('w',m,[r],[],{})
    scope=Scope(workspace='w',course='c',snapshot=sid,allowed_sources=['doc'])
    cases={'version':'test','cases':[{'id':'x','split':'development','query':'official answers','missing':True}]}
    report=evaluate(cases,CourseQueryService(store),scope)
    assert report['passed']==1
