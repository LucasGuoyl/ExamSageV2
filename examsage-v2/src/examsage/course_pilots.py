"""Validate explicitly audited course pilots against the current source inventory."""
from pathlib import Path
import json
import re
from .domain import Manifest, Page, Record, Relation, SourceRef, digest
from .numeric_audit import audit_numerical_check
from .adjudication import validate_adjudication


def load_pilot(path: Path, manifest: Manifest, pages: list[Page]):
    recipe=json.loads(path.read_text(encoding='utf-8'))
    if recipe.get('schema')!='course-pilot-v1' or recipe.get('course_key')!=manifest.course_key:
        raise ValueError('Pilot schema/course mismatch')
    docs={d.id:d for d in manifest.documents}
    source_hashes=recipe['source_hashes']
    for did,sha in source_hashes.items():
        if did not in docs or docs[did].sha256!=sha:raise ValueError('Pilot source hash mismatch')
    visible={(p.document_id,p.number) for p in pages if not p.hidden}
    page_text={(p.document_id,p.number):p.text for p in pages if not p.hidden}
    def check_refs(refs):
        for ref in refs:
            if ref.document_id not in source_hashes or (ref.document_id,ref.page) not in visible:
                raise ValueError('Pilot reference missing, hidden or unbound')
    records=[Record.model_validate(r) for r in recipe['records']]
    by_id={r.id:r for r in records}
    if len(by_id)!=len(records):raise ValueError('Duplicate pilot record')
    for record in records:
        check_refs(record.refs)
        record.details['pilot_record']=True
        if record.visibility!='visible' or record.review!='agent_source_checked':raise ValueError('Pilot review required')
        bound={(r.document_id,r.page) for r in record.refs}
        for step in record.details.get('derivation',{}).get('steps',[]):
            refs=[SourceRef.model_validate(r) for r in step.get('refs',[])]
            refs += [SourceRef(document_id=record.refs[0].document_id,page=n) for n in step.get('pages',[])]
            if not refs or not {(r.document_id,r.page) for r in refs}<=bound:
                raise ValueError('Derivation step outside record source scope')
            check_refs(refs)
        if record.kind in {'question','answer'}:
            details=record.details;did=record.refs[0].document_id
            details['source_only_text']='\n\n'.join(f'原页 {r.page}\n'+page_text[r.document_id,r.page] for r in record.refs)
            if details.get('audit',{}).get('adjudication'):
                validate_adjudication(details['audit']['adjudication'],docs,visible,source_hashes)
            if len({r.document_id for r in record.refs})!=1 or details.get('source_sha256')!=docs[did].sha256:
                raise ValueError('Question/answer source mismatch')
            if docs[did].kind!=('exam' if record.kind=='question' else 'exam_solution'):
                raise ValueError('Question/answer document kind mismatch')
            if details.get('year_basis') not in {'cover_verified','filename_label'} or not isinstance(details.get('exam_year'),int):
                raise ValueError('Question needs explicit year basis')
            labels=recipe.get('year_labels',{})
            label=labels.get(did) or (labels.get(details.get('paired_document_id')) if record.kind=='answer' else None)
            if not label or label.get('year')!=details['exam_year'] or label.get('basis')!=details['year_basis']:
                raise ValueError('Question/answer year differs from audited source label')
            if details.get('year_label') and label.get('label')!=details['year_label']:
                raise ValueError('Question/answer academic-year label mismatch')
            if not str(details.get('number','')).isdigit():raise ValueError('Question number required')
            details['number']=str(int(details['number']))
            details['pilot_record']=True
            if record.kind=='question' and not details.get('part'):
                # A whole-question guide may include comparisons with answer pages.
                # Preserve a projection made solely from the original question pages.
                details['source_question_text']='\n\n'.join(f'原题第 {r.page} 页\n'+page_text[r.document_id,r.page] for r in record.refs)
            if details.get('scope')=='subquestion':
                part=details.get('part','')
                if not re.fullmatch(r'(?:[a-z]+|[0-9]+)(?:\.(?:[a-z]+|[0-9]+))*',part):raise ValueError('Invalid canonical subquestion part')
                parent=by_id.get(record.parent_id)
                if parent is None or parent.kind!=record.kind or parent.refs[0].document_id!=did or any(str(parent.details.get(k))!=str(details[k]) for k in ['exam_year','number','year_basis']):
                    raise ValueError('Subquestion parent identity mismatch')
                expected=part.rsplit('.',1)[0] if '.' in part else None
                actual=parent.details.get('part')
                if actual!=expected and not (record.kind=='answer' and actual is None):raise ValueError('Subquestion parent hierarchy mismatch')
                audit=details.get('audit',{})
                if audit.get('status') not in {'checked','source_conflict','partial'} or audit.get('numerical_status') not in {'recomputed','qualitative','symbolic','unresolved'}:
                    raise ValueError('Invalid subquestion audit status')
                for key in ['conditions','warnings']:
                    if not isinstance(audit.get(key),list) or any(not isinstance(v,str) or not v.strip() for v in audit[key]):raise ValueError('Invalid audit text list')
                for key in ['formula_checks','numerical_checks']:
                    if not isinstance(audit.get(key),list):raise ValueError('Audit checks must be lists')
                for formula in audit['formula_checks']:
                    if not all(isinstance(formula.get(k),str) and formula[k].strip() for k in ['latex','note']):raise ValueError('Formula explanation required')
                if bool(audit['numerical_checks'])!=(audit['numerical_status']=='recomputed'):raise ValueError('Numerical status must match actual checks')
                checked=[]
                for check in audit['numerical_checks']:
                    refs=[SourceRef.model_validate(r) for r in check.get('source_refs',[])]
                    support={(e['document_id'],e['page']) for e in audit.get('adjudication',{}).get('evidence',[])}
                    if not refs or any(r.document_id not in {did,details.get('paired_document_id')} and (r.document_id,r.page) not in support for r in refs):raise ValueError('Numerical check outside bound source scope')
                    check_refs(refs)
                    if not check.get('label') or not isinstance(check.get('unit'),str):raise ValueError('Numerical check label/unit required')
                    result=audit_numerical_check(check);checked.append(result)
                    if result['comparison']=='mismatch':
                        if audit['status']=='checked':audit['status']='source_conflict'
                        note=f"复算不一致：{check['label']}，按列明条件得 {result['computed_value']:.8g} {check['unit']}，来源答案写 {check['source_value']} {check['unit']}。"
                        if note not in audit['warnings']:audit['warnings'].append(note)
                audit['numerical_checks']=checked
    for record in records:
        if record.kind=='question':
            record.details['children_count']=sum(r.parent_id==record.id and r.kind=='question' for r in records)
            record.details['has_answer']=False
    edges=[];paired=set()
    for raw in recipe.get('relations',[]):
        edge=Relation.model_validate({**{k:v for k,v in raw.items() if k!='details'},
            'id':raw.get('id') or 'pilot-rel:'+digest(raw)[:24]})
        check_refs(edge.refs)
        if edge.source not in by_id or edge.target not in by_id:raise ValueError('Pilot relation endpoint absent')
        q,a=by_id[edge.source],by_id[edge.target]
        if edge.kind=='has_answer':
            if q.kind!='question' or a.kind!='answer' or edge.origin!='explicit':raise ValueError('Invalid answer relation')
            if any(q.details.get(k)!=a.details.get(k) for k in ['exam_year','number','part','year_basis']):
                raise ValueError('Answer year/question mismatch')
            if q.details.get('paired_document_id')!=a.refs[0].document_id or a.details.get('paired_document_id')!=q.refs[0].document_id:
                raise ValueError('Answer document pairing mismatch')
            if {(r.document_id,r.page) for r in edge.refs}!={(r.document_id,r.page) for r in q.refs+a.refs}:
                raise ValueError('Answer relation evidence incomplete')
            if q.id in paired:raise ValueError('Ambiguous answer mapping')
            paired.add(q.id);q.details['has_answer']=True
        edges.append(edge)
    for did,year in recipe.get('document_years',{}).items():
        label=recipe.get('year_labels',{}).get(did,{})
        if did not in source_hashes or docs[did].kind!='exam' or label.get('basis')!='cover_verified' or label.get('year')!=year:
            raise ValueError('Document date needs cover evidence')
        docs[did].exam_year=year
        docs[did].date_evidence='Pilot audit: year on cover; availability date remains unknown.'
    metadata={'pilot_hash':digest(recipe),'pilot_records':len(records),'pilot_questions':sum(r.kind=='question' for r in records),
        'pilot_answer_pairs':len(paired),'topics':recipe.get('topics',[]),'pilot_limitations':recipe.get('limitations',[]),
        'question_extraction':'pilot_source_matched' if paired else 'not_verified'}
    return records,edges,metadata
