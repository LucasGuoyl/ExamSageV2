"""Export an authorized, offline evidence-reader candidate (not a model chat)."""
import json
from pathlib import Path

from .plugin_tools import PluginTools


def render_map_reader(tools: PluginTools, course_id: str, candidate: dict, output: Path):
    """Render a single authorized course after independently resolving each supplied quote."""
    identity = tools.call('browse_course_materials', {'course_id': course_id, 'offset': 0})
    keys = {'course_id', 'snapshot', 'scope_digest'}
    if (not isinstance(candidate, dict)
            or any(candidate.get(key) != identity[key] for key in keys)):
        raise ValueError('Map proposal does not match the selected course, snapshot or sources')
    if set(candidate) == keys | {'nodes'}:
        nodes = candidate['nodes']
    elif candidate.get('schema_version') == 'knowledge-map-v1':
        # A downloaded result includes generated source IDs, warnings and coverage.
        # Only its authored fields are inputs when reopening under current grants.
        try:
            nodes = []
            for topic in candidate['nodes']:
                authored = {key: topic[key] for key in ('id','parent','kind','title','summary')}
                authored['support'] = [{key: ref[key] for key in ('document_id','page','quote')}
                                       for ref in topic['support']]
                nodes.append(authored)
        except (TypeError, KeyError):
            raise ValueError('Invalid downloaded map structure') from None
    else:
        raise ValueError('Unknown knowledge map format')
    graph = tools.call('prepare_knowledge_map', {'course_id': course_id, 'nodes': nodes})
    return _render_reader(tools, output, graph)


def render_reader(tools: PluginTools, output: Path):
    return _render_reader(tools, output, None)


def _render_reader(tools, output, graph):
    if output.exists():
        raise FileExistsError('Choose a new reader output file')
    courses = []
    for item in tools.call('list_courses', {})['courses']:
        cid = item['course_id']
        if graph and cid != graph['course_id']:
            continue
        binding, store = tools._course(cid)
        records = store.list_records(binding.scope)
        items = []
        for record in records:
            if record.kind == 'answer':
                continue
            args = {'course_id': cid, 'record_id': record.id}
            bundle = tools.call('get_record', args)
            entry = {'id': record.id, 'title': record.title, 'kind': record.kind, 'bundle': bundle}
            if record.kind == 'question':
                entry['answer'] = tools.call('get_answer', {'course_id': cid, 'question_id': record.id})
            items.append(entry)
        course = {**item, 'profile': tools.call('get_course_profile', {'course_id': cid}), 'items': items}
        if graph:
            course['knowledge_map'] = graph
        courses.append(course)
    payload = json.dumps(courses, ensure_ascii=True).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    template = Path(__file__).with_name('web')/'course-reader.html'
    html = template.read_text(encoding='utf-8').replace('__EXAMSAGE_DATA__', payload)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8') as target:
        target.write(html)
    return {'courses': len(courses), 'output': str(output), 'model_called': False}
