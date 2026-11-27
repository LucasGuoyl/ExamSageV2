import json

from examsage.plugin_tools import CourseBinding, PluginTools, Principal
from test_plugin_tools import api


def test_reader_exports_only_authorized_evidence_and_escapes_html(tmp_path):
    from examsage.course_reader import render_reader
    tools = api(tmp_path/'library', ('physics',))
    binding, store = tools._course('physics')
    from examsage.storage import Store
    manifest = store.manifest(binding.scope)
    record = store.get(binding.scope, 'doc:p1')
    record.text = '</script><script>window.readerInjected=true</script>'
    writer = Store(store.path)
    sid = writer.publish('w', manifest, [record], [], {})
    scope = binding.scope.model_copy(update={'snapshot': sid})
    tools = PluginTools([CourseBinding('physics', store.path, scope)], Principal('alice', frozenset(['physics'])))
    target = tmp_path/'reader.html'
    render_reader(tools, target)
    html = target.read_text(encoding='utf-8')
    data = json.loads(html.split('<script id="course-data" type="application/json">')[1].split('</script>')[0])
    assert [c['course_id'] for c in data] == ['physics']
    assert data[0]['items'][0]['bundle']['records'][0]['text'] == record.text
    assert '</script><script>window.readerInjected' not in html
