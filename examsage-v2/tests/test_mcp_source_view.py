import io

from examsage.mcp_server import PROTOCOL_VERSION
from examsage.plugin_tools import Principal
from examsage.student_workspace import StudentWorkspace
from test_mcp_http import call, hosted_client, invoke
from test_web_intake import make_import


def test_http_client_can_discover_and_fetch_the_source_view(tmp_path):
    with hosted_client(tmp_path,tmp_path/'people',[Principal('student',frozenset())]) as client:
        init=invoke(client,'initialize',{'protocolVersion':PROTOCOL_VERSION,'capabilities':{},
                   'clientInfo':{'name':'student','version':'1'}}).json()['result']
        assert 'resources' in init['capabilities']
        tools=invoke(client,'tools/list').json()['result']['tools']
        views={t['name']:t['_meta']['ui']['resourceUri'] for t in tools if t.get('_meta',{}).get('ui')}
        assert set(views)=={'get_source_page','get_source_image'}
        assert len(set(views.values()))==1
        uri=views['get_source_page']
        listed=invoke(client,'resources/list').json()['result']['resources']
        assert [r['uri'] for r in listed]==[uri]
        contents=invoke(client,'resources/read',{'uri':uri}).json()['result']['contents']
        assert len(contents)==1 and contents[0]['mimeType']=='text/html;profile=mcp-app'
        assert contents[0]['uri']==uri and '<html' in contents[0]['text']
        assert contents[0]['_meta']['ui']['csp']['connectDomains']==[]
        assert invoke(client,'resources/templates/list').json()['result']=={'resourceTemplates':[]}
        assert invoke(client,'resources/read',{'uri':'ui://examsage/missing'}).json()['error']['code']==-32002
        assert invoke(client,'resources/read',{}).json()['error']['code']==-32602


def test_resource_is_generic_and_native_text_citations_still_work(tmp_path):
    principal=Principal('student',frozenset())
    folder=tmp_path/'people'
    receipt=make_import(StudentWorkspace(folder,principal).imports,[
        ('verse.txt',io.BytesIO('试课独有标题\n第一行\n\n第四行'.encode()))])
    identity=[principal]
    with hosted_client(tmp_path/'catalog',folder,identity) as client:
        cid='upload-'+receipt['id']
        doc=call(client,'browse_course_materials',course_id=cid,offset=0)['structuredContent']['pages'][0]
        result=call(client,'get_source_page',course_id=cid,document_id=doc['document_id'],page=1)
        page=result['structuredContent']
        ref=page['sources'][0]
        assert ref['refs'][0]['filename']=='verse.txt' and '试课独有标题' in result['content'][0]['text']
        assert result['_meta']['examsage/originalTextField'] in ('raw_text','text')
        uri=invoke(client,'resources/list').json()['result']['resources'][0]['uri']
        html=invoke(client,'resources/read',{'uri':uri}).json()['result']['contents'][0]['text']
        assert '试课独有标题' not in html and cid not in html and ref['source_id'] not in html
        identity.clear()
        assert invoke(client,'resources/read',{'uri':uri}).status_code==401
