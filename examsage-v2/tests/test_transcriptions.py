import pytest
from examsage.domain import Document,Page
from examsage.questions import parse_exam


def fixture():
    doc=Document(id='exam',relative_path='exam.pdf',sha256='a'*64,pages=1,kind='exam',exam_year=2024)
    pages=[Page(document_id='exam',number=1,text='1. Water\n𝐾𝐾 = 1\ni) Explain. (5 marks)')]
    recipe={'version':'checked-1','documents':[{'sha256':doc.sha256,'pages':[{'number':1,'replacements':[{'before':'𝐾𝐾 = 1','after':r'\(K=1\)'}]}]}]}
    return doc,pages,recipe


def test_source_checked_layer_preserves_raw_and_shared_context():
    from examsage.transcriptions import parse_reviewed_exam
    doc,pages,recipe=fixture()
    records=parse_reviewed_exam(doc,pages,'course',recipe)
    assert '𝐾𝐾' not in records[0].text
    assert '𝐾𝐾' in records[0].details['raw_text']
    assert r'\(K=1\)' in records[1].details['shared_stem']
    assert '𝐾𝐾' in pages[0].text
    assert records[0].details['transcription']['review']=='agent_source_checked'
    assert records[0].review!='expert_checked'


def test_transcription_does_not_apply_to_changed_source_or_changed_span():
    from examsage.transcriptions import parse_reviewed_exam
    doc,pages,recipe=fixture()
    changed=doc.model_copy(update={'sha256':'b'*64})
    assert parse_reviewed_exam(changed,pages,'course',recipe)[0].text==parse_exam(changed,pages,'course')[0].text
    pages[0].text=pages[0].text.replace('𝐾𝐾','K')
    with pytest.raises(ValueError,match='transcription'):
        parse_reviewed_exam(doc,pages,'course',recipe)
