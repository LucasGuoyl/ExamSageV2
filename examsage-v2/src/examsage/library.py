"""Course-specific snapshots behind a shared local viewer."""
from collections import Counter
from pathlib import Path
import json
import re

from .domain import Scope
from .ingest import ingest, atomic_json, PARSER_VERSION
from .manifest import build_manifest
from .storage import Store
from .release import inside


def build_source_course(source: Path, audit: Path, folder: str, data: Path, config: dict, pilot: Path | None=None) -> dict:
    manifest = build_manifest(source, audit, folder, config)
    extracted = ingest(source, manifest, data)
    metadata = {'parser':PARSER_VERSION, 'structure_mode':'source_pages', 'review':'candidate',
                'query_aliases':config.get('query_aliases',{}), 'question_extraction':'not_verified'}
    relations=[]
    if pilot:
        from .course_pilots import load_pilot
        records,relations,pilot_metadata=load_pilot(pilot,manifest,extracted['pages'])
        extracted['records']+=records;metadata.update(pilot_metadata)
    store = Store(data/'course.sqlite3')
    sid = store.publish('local',manifest,extracted['records'],relations,metadata)
    scope = Scope(workspace='local',course=manifest.course_key,snapshot=sid,allowed_sources=[d.id for d in manifest.documents])
    atomic_json(data/'current.json',scope.model_dump(mode='json'))
    atomic_json(data/'pages.json',[p.model_dump() for p in extracted['pages']])
    atomic_json(data/'topics.json',metadata.get('topics',[]))
    report = {'snapshot':sid,'documents':len(manifest.documents),'pages':len(extracted['pages']),
              'records':dict(Counter(r.kind for r in extracted['records'])), 'structure_mode':'source_pages',
              'source_kinds':dict(Counter(d.kind for d in manifest.documents)),
              'full_slide_renders':sum(bool(p.render) for p in extracted['pages']),
              'failed_pages':sum(p.status=='failed' for p in extracted['pages']),
              'little_text_pages':sum(len(p.text.strip())<30 for p in extracted['pages']),
              'supplement_pages':sum(bool(p.supplement) for p in extracted['pages']),
              'low_text_unprocessed':sum(len(p.text.strip())<30 and not p.supplement for p in extracted['pages']),
              'supplement_categories':dict(Counter(p.supplement['audit']['category'] for p in extracted['pages'] if p.supplement)),
              'recovery_pages':sum(bool(p.supplement and p.supplement.get('recovery_status')) for p in extracted['pages']),
              'recovery_states':dict(Counter(p.supplement['recovery_status'] for p in extracted['pages'] if p.supplement and p.supplement.get('recovery_status'))),
              'visual_review_pending':len(extracted['pages']), 'human_acceptance':'pending',
              'pilot_records':metadata.get('pilot_records',0),'pilot_answer_pairs':metadata.get('pilot_answer_pairs',0),
              'cached_documents':extracted['cached'],'newly_parsed_documents':extracted['processed']}
    atomic_json(data/'build_report.json',report)
    return report


def build_library(source: Path, audit: Path, config_path: Path, data: Path) -> dict:
    from .cli import build
    config = json.loads(config_path.read_text(encoding='utf-8'))
    registry=[]
    results={}
    for slug, settings in config['courses'].items():
        if not re.fullmatch('[a-z0-9_-]+',slug):raise ValueError('Invalid course slug')
        target=inside(data,slug)
        try:
            if settings.get('curated_recipe'):
                result=build(source/slug,audit,inside(config_path.parent,settings['curated_recipe']),target)
            else:
                pilot=inside(config_path.parent,settings['pilot']) if settings.get('pilot') else None
                result=build_source_course(source/slug,audit,slug,target,settings,pilot)
            results[slug]=result
            registry.append({'slug':slug,'data':slug,'name':settings['name']})
        except Exception as exc:
            results[slug]={'error':str(exc),'error_type':type(exc).__name__}
    atomic_json(data/'library-report.json',results)
    # A failed rebuild must not remove previously available courses from the catalog.
    # Per-course snapshots already published remain valid; the catalog changes only
    # when every configured course completes successfully.
    if not any('error' in result for result in results.values()):
        atomic_json(data/'library.json',{'default':config['default'],'courses':registry})
    return results


def registry_courses(default_data: Path):
    """Read an explicit registry or discover it beside a legacy default course."""
    default_data=default_data.resolve()
    registry=default_data.parent/'library.json'
    entries=json.loads(registry.read_text(encoding='utf-8'))['courses'] if registry.exists() else []
    entries=[dict(e,path=inside(default_data.parent,e['data'])) for e in entries]
    if default_data!=registry and not any(e['path']==default_data for e in entries):
        entries=[]
    for entry in entries:
        if not re.fullmatch('[a-z0-9_-]+',entry['slug']):raise ValueError('Invalid course slug')
    return entries


def create_library_app(default_data: Path, *, import_root: Path | None=None, chat_runner=None):
    from fastapi import FastAPI
    from .api import create_app
    from .web_intake import install_intake
    default_data=default_data.resolve()
    entries=registry_courses(default_data)
    catalog=[{'slug':e['slug'],'name':e['name'],'url':'/' if e['path']==default_data else '/courses/'+e['slug']+'/'} for e in entries]
    app=FastAPI(title='ExamSage Course Library',docs_url=None,redoc_url=None,openapi_url=None)
    default_id = None
    for entry in entries:
        if entry['path']!=default_data:
            app.mount('/courses/'+entry['slug'],create_app(entry['path'], catalog,
                      chat_runner=chat_runner, course_id=entry['slug']))
        else:
            default_id = entry['slug']
    install_intake(app, import_root if import_root is not None else Path(__file__).resolve().parents[2]/'data'/'course-imports',
                   catalog, chat_runner=chat_runner)
    app.mount('/',create_app(default_data,catalog,chat_runner=chat_runner,course_id=default_id))
    return app
