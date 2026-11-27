"""Evidence-bound review conclusions; an agent verdict is never expert approval."""
from .domain import SourceRef

CATEGORIES={'system_error','source_error','both','insufficient_evidence'}


def validate_adjudication(value, documents, visible, source_hashes):
    if not isinstance(value,dict) or value.get('schema')!='source-adjudication-v1' or value.get('review')!='agent_source_checked':
        raise ValueError('Invalid adjudication schema/review')
    if value.get('category') not in CATEGORIES or not isinstance(value.get('summary'),str) or not value['summary'].strip():
        raise ValueError('Invalid adjudication conclusion')
    for key in ['system_findings','source_findings','actions','remaining']:
        if not isinstance(value.get(key),list) or any(not isinstance(x,str) or not x.strip() for x in value[key]):
            raise ValueError('Invalid adjudication findings')
    evidence=value.get('evidence')
    if not isinstance(evidence,list) or not evidence:raise ValueError('Adjudication evidence required')
    for row in evidence:
        ref=SourceRef(document_id=row.get('document_id'),page=row.get('page'))
        doc=documents.get(ref.document_id)
        if doc is None or (ref.document_id,ref.page) not in visible or source_hashes.get(ref.document_id)!=doc.sha256 or row.get('source_sha256')!=doc.sha256:
            raise ValueError('Adjudication evidence missing, hidden or hash mismatch')
        if not isinstance(row.get('observation'),str) or not row['observation'].strip():
            raise ValueError('Adjudication observation required')


def adjudication_text(value):
    labels={'system_error':'系统错误','source_error':'原始资料错误','both':'系统与原始资料均有问题','insufficient_evidence':'证据仍不足'}
    result='\n[来源复核 · '+labels[value['category']]+']\n'+value['summary']
    for key,label in [('system_findings','系统发现'),('source_findings','来源发现'),('actions','处理'),('remaining','仍有限制')]:
        result+=''.join('\n'+label+'：'+x for x in value[key])
    return result
