import pytest
from test_supplements import fixture,save
from examsage.supplements import apply_supplements
from examsage.ingest import page_records

def recovery():
    return {'schema':'page-recovery-v1','status':'source_transcribed','blocks':[
        {'kind':'equation','text':'热扩散率是导热率与体积热容之比。','latex':r'\kappa=\frac{k}{\rho c_p}'}],
        'unresolved':[],'review':'agent_source_checked'}

def test_recovery_indexes_checked_content_without_promoting_ocr(tmp_path):
    folder,doc,pages,package=fixture(tmp_path);item=package['pages'][0]
    item['ocr'].update(text='badOCRguess',mean_confidence=8);item['audit']['recovery']=recovery();save(folder,doc,package)
    page=apply_supplements(doc,pages,folder,tmp_path/'assets')[0];record=page_records([page],doc)[0]
    assert '热扩散率' in record.text and r'\kappa' in record.text
    assert 'badOCRguess' not in record.text and record.details['raw_text']=='1'
    assert page.supplement['ocr']['mean_confidence']==8 and not page.supplement['ocr_indexed']
    assert page.supplement['recovery_status']=='source_transcribed'
    assert page.supplement['expert_acceptance']=='pending' and page.visual_status=='not_reviewed'

@pytest.mark.parametrize('fault',['schema','status','empty','kind','box','overclaim','hidden_uncertainty'])
def test_recovery_rejects_invalid_or_overstated_content(tmp_path,fault):
    folder,doc,pages,package=fixture(tmp_path);r=recovery()
    if fault=='schema':r['schema']='other'
    if fault=='status':r['status']='expert_verified'
    if fault=='empty':r['blocks']=[]
    if fault=='kind':r['blocks'][0]['kind']='guess'
    if fault=='box':r['blocks'][0]['bbox']=[0,0,2,1]
    if fault=='overclaim':r['review']='expert_checked'
    if fault=='hidden_uncertainty':r['unresolved']=['符号读不清但仍有影响']
    package['pages'][0]['audit']['recovery']=r;save(folder,doc,package)
    with pytest.raises(ValueError):apply_supplements(doc,pages,folder,tmp_path/'assets')

def test_partial_recovery_keeps_open_uncertainties_explicit(tmp_path):
    folder,doc,pages,package=fixture(tmp_path);r=recovery()
    r.update(status='partially_legible',unresolved=['右上角符号不可辨读，未纳入公式。'])
    package['pages'][0]['audit']['recovery']=r;save(folder,doc,package)
    page=apply_supplements(doc,pages,folder,tmp_path/'assets')[0];record=page_records([page],doc)[0]
    assert page.supplement['recovery_status']=='partially_legible'
    assert '未纳入公式' in record.text
