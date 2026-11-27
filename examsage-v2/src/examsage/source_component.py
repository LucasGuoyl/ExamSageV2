"""Static MCP Apps resource served by the HTTP transport. No course data is cached here."""
from pathlib import Path

from .knowledge_map import original_text_field


URI = 'ui://examsage/source-page-v1.html'
MIME = 'text/html;profile=mcp-app'
PAGE_TOOLS = {'get_source_page','get_source_image'}
UI = {'prefersBorder': True, 'csp': {'connectDomains': [], 'resourceDomains': []}}


def attach_tools(definitions):
    for tool in definitions:
        if tool['name'] in PAGE_TOOLS:
            tool['_meta'] = {'ui': {'resourceUri': URI,'visibility': ['model','app']},
                             'openai/outputTemplate': URI}


def resource(method, params):
    if method=='resources/read':
        if set(params)-{'uri','_meta'} or not isinstance(params.get('uri'),str):
            raise ValueError('Invalid resource parameters')
        if params['uri']!=URI:
            raise LookupError('Resource not found')
        html = (Path(__file__).parent/'web'/'source-component.html').read_text(encoding='utf-8')
        return {'contents':[{'uri':URI,'mimeType':MIME,'text':html,'_meta':{'ui':UI}}]}
    if set(params)-{'_meta'}:
        raise ValueError('Invalid resource list parameters')
    if method=='resources/templates/list':
        return {'resourceTemplates':[]}
    return {'resources':[{'uri':URI,'name':'课程引用原页','mimeType':MIME,'_meta':{'ui':UI}}]}


def add_result_metadata(result, name):
    if name=='get_source_page':
        records = result['structuredContent'].get('records',[])
        if records:
            field = original_text_field(records[0].get('details') or {})
            result['_meta'] = {'examsage/originalTextField':field}
