import pytest
from test_slides import rendered_fixture


def test_review_bound_to_source_and_render_preserves_raw_and_builds_cited_steps(tmp_path):
    from examsage.slides import attach_slide_renders
    from examsage.visual_review import apply_visual_review
    from examsage.ingest import page_records
    doc, pages, assets, folder, _ = rendered_fixture(tmp_path)
    pages = attach_slide_renders(doc, pages, folder, assets)
    recipe = {'documents': {doc.sha256: {'pages': [{'number': 1, 'render_sha256': pages[0].render['sha256'],
               'summary': 'Porosity definition', 'formulas': [r'\phi=V_p/V_t'], 'warnings': ['Check averaging.']}],
               'derivations': [{'key': 'flow', 'title': 'Flow derivation', 'summary': 'From porosity to velocity',
                  'pages': [1], 'aliases': ['流速推导'], 'conditions': ['Steady flow'],
                  'steps': [{'title': 'First', 'text': 'Use pore fraction', 'pages': [1], 'latex': r'v=q/\phi'}]}]}}}
    reviewed, derived = apply_visual_review(doc, pages, recipe, 'c')
    assert reviewed[0].text == pages[0].text
    assert reviewed[0].visual_status == 'agent_reviewed'
    assert pages[0].visual_status == 'not_reviewed'
    record = page_records(reviewed, doc)[0]
    assert record.details['raw_text'] == 'original page 1'
    assert 'Porosity definition' in record.text
    assert record.details['visual_review']['review'] == 'agent_source_checked'
    assert derived[0].refs[0].page == 1
    assert derived[0].review != 'expert_checked'
    recipe['documents'][doc.sha256]['pages'][0]['render_sha256'] = '0'*64
    with pytest.raises(ValueError, match='render'): apply_visual_review(doc, pages, recipe, 'c')


def test_derivation_cannot_cite_unreviewed_or_hidden_pages(tmp_path):
    from examsage.slides import attach_slide_renders
    from examsage.visual_review import apply_visual_review
    doc, pages, assets, folder, _ = rendered_fixture(tmp_path)
    pages = attach_slide_renders(doc, pages, folder, assets)
    recipe = {'documents': {doc.sha256: {'pages': [], 'derivations': [{'key':'bad','title':'bad',
        'summary':'bad','pages':[2],'conditions':[],'steps':[]}]}}}
    with pytest.raises(ValueError): apply_visual_review(doc, pages, recipe, 'c')
