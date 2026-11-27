import io

import httpx
import pytest

from examsage.mcp_server import PROTOCOL_VERSION
from examsage.plugin_tools import Principal, SPECS
from examsage.student_workspace import StudentWorkspace
from test_plugin_candidates import candidate_source
from test_web_intake import make_import


ORIGIN = 'https://courses.example'
HEADERS = {'Accept':'application/json, text/event-stream','MCP-Protocol-Version':PROTOCOL_VERSION}


def hosted_client(library, students, identity):
    from examsage.mcp_http import create_course_mcp
    endpoint = create_course_mcp(library,students,origin=ORIGIN)

    def host(environ, start_response):
        if identity:
            environ['examsage.principal'] = identity[0]
        return endpoint(environ,start_response)

    return httpx.Client(transport=httpx.WSGITransport(app=host),base_url=ORIGIN,headers=HEADERS)


def invoke(client, method, params=None):
    return client.post('/mcp',json={'jsonrpc':'2.0','id':1,'method':method,'params':params or {}})


def call(client,name,**args):
    return invoke(client,'tools/call',{'name':name,'arguments':args}).json()['result']


def test_remote_client_negotiates_and_round_trips_authored_course_page(tmp_path):
    principal = Principal('institution:student-a',frozenset())
    root = tmp_path/'students'
    receipt = make_import(StudentWorkspace(root,principal).imports,[
        ('Water.txt',io.BytesIO(b'Darcy flux q=0.18 m/day.\fEffective porosity is 0.30.'))])
    with hosted_client(tmp_path/'library',root,[principal]) as client:
        reply=client.post('/mcp',headers={'MCP-Protocol-Version':PROTOCOL_VERSION},json={
            'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':PROTOCOL_VERSION,
                'capabilities':{},'clientInfo':{'name':'student','version':'1'}}})
        assert reply.json()['result']['protocolVersion']==PROTOCOL_VERSION
        ack=client.post('/mcp',json={'jsonrpc':'2.0','method':'notifications/initialized'})
        assert ack.status_code==202 and not ack.content
        assert {t['name'] for t in invoke(client,'tools/list').json()['result']['tools']}==set(SPECS)
        cid='upload-'+receipt['id']
        assert [c['course_id'] for c in call(client,'list_courses')['structuredContent']['courses']]==[cid]
        first=call(client,'browse_course_materials',course_id=cid,offset=0)['structuredContent']['pages'][0]
        pages=[call(client,'get_source_page',course_id=cid,document_id=first['document_id'],page=p)
               ['structuredContent'] for p in (1,2)]
        assert '0.18' in pages[0]['records'][0]['text'] and '0.30' in pages[1]['records'][0]['text']
        sources=[{k:page['sources'][0][k] for k in ('source_id','record_id')} for page in pages]
        result=call(client,'calculate',course_id=cid,expression='q/n',inputs={'q':.18,'n':.30},
                    sources=sources,units='m/day')['structuredContent']
        assert result['value']==pytest.approx(.6)
        assert {s['refs'][0]['page'] for s in result['sources']}=={1,2}


def test_host_grants_follow_the_current_student_on_every_request(tmp_path):
    library=candidate_source(tmp_path/'source')/'data'
    students=tmp_path/'students'
    alice=Principal('A',frozenset(['grt']))
    bob=Principal('B',frozenset(['ses']))
    def fixture_course(person):
        receipt=make_import(StudentWorkspace(students,person).imports)
        return 'upload-'+receipt['id']
    private_a,private_b=fixture_course(alice),fixture_course(bob)
    identity=[alice]
    with hosted_client(library,students,identity) as client:
        def menu():
            return {c['course_id'] for c in call(client,'list_courses')['structuredContent']['courses']}
        assert menu()=={'grt',private_a}
        identity[0]=bob
        assert menu()=={'ses',private_b}
        assert call(client,'browse_course_materials',course_id=private_a,offset=0)['isError']
        identity[0]=Principal('A',frozenset())
        assert menu()=={private_a}
        assert call(client,'get_course_profile',course_id='grt')['isError']
        identity.clear()
        assert invoke(client,'tools/list').status_code==401


def test_http_negotiation_and_origin(tmp_path):
    with hosted_client(tmp_path,tmp_path/'students',[Principal('A',frozenset())]) as client:
        assert client.get('/mcp').status_code==405
        msg={'jsonrpc':'2.0','id':1,'method':'ping'}
        for headers,status in [({'Origin':'https://other.example'},403),
                               ({'Host':'other.example'},403),
                               ({'Accept':'application/json'},406),
                               ({'MCP-Protocol-Version':'unknown'},400)]:
            assert client.post('/mcp',json=msg,headers=headers).status_code==status
        assert client.get('/mcp',headers={'Origin':'https://other.example'}).status_code==403
        assert client.post('/mcp',content='abc',headers={'Content-Type':'text/plain'}).status_code==415
        assert client.post('/mcp',content='{}'*70000,headers={'Content-Type':'application/json'}).status_code==413
        assert client.post('/mcp',content='[',headers={'Content-Type':'application/json'}).status_code==400
        assert client.post('/mcp',json=[msg]).status_code==400
        assert invoke(client,'ping').json()['result']=={}


def test_cli_serves_local_os_courses_on_loopback(tmp_path,monkeypatch):
    from contextlib import contextmanager
    from wsgiref import simple_server
    from examsage.cli import main
    library=candidate_source(tmp_path/'source')/'data'
    calls=[]
    @contextmanager
    def listener(host,port,app):
        class Server:
            def serve_forever(self):
                calls.append((host,port))
                with httpx.Client(transport=httpx.WSGITransport(app=app),headers=HEADERS,
                                  base_url=f'http://{host}:{port}') as client:
                    courses=call(client,'list_courses')['structuredContent']['courses']
                assert [c['course_id'] for c in courses]==['grt']
        yield Server()
    monkeypatch.setattr(simple_server,'make_server',listener)
    args=['serve-mcp-local','--library',str(library),'--workspace-root',str(tmp_path/'students'),
          '--course','grt','--port','8770']
    assert main(args)==0 and calls==[('127.0.0.1',8770)]
    assert not (tmp_path/'students').exists()


def test_client_discovers_configured_school_sign_in_without_course_access(tmp_path):
    from examsage.mcp_http import create_course_mcp
    issuer='https://school.example/tenant'
    app=create_course_mcp(tmp_path,tmp_path/'students',origin=ORIGIN,authorization_server=issuer)
    with httpx.Client(transport=httpx.WSGITransport(app=app),base_url=ORIGIN,headers=HEADERS) as client:
        response=invoke(client,'tools/list')
        assert response.status_code==401
        path='/.well-known/oauth-protected-resource/mcp'
        assert f'resource_metadata="{ORIGIN}{path}"' in response.headers['WWW-Authenticate']
        assert client.get(path).json()=={'resource':ORIGIN+'/mcp','authorization_servers':[issuer]}
        assert client.post(path).status_code==405
        assert client.get(path,headers={'Origin':'https://elsewhere.example'}).status_code==403
        assert invoke(client,'tools/list').status_code==401


def test_normal_wsgi_mount_preserves_school_resource_and_reachable_challenge(tmp_path):
    from wsgiref.util import shift_path_info
    from examsage.mcp_http import create_course_mcp
    app=create_course_mcp(tmp_path,tmp_path,origin=ORIGIN,authorization_server='https://login.example')
    def school(environ,start_response):
        if shift_path_info(environ)!='school':
            start_response('404 Not Found',[('Content-Type','text/plain')])
            return [b'']
        return app(environ,start_response)
    with httpx.Client(transport=httpx.WSGITransport(app=school),base_url=ORIGIN,headers=HEADERS) as client:
        first=client.post('/school/mcp',json={'jsonrpc':'2.0','method':'ping','id':1})
        advertised=first.headers['www-authenticate'].split('resource_metadata="')[1].split('"')[0]
        resource=client.get(advertised)
        assert resource.status_code==200 and resource.json()['resource']==ORIGIN+'/school/mcp'


def test_allowed_browser_can_discover_login_and_send_course_requests(tmp_path):
    from examsage.mcp_http import create_course_mcp
    browser='https://study.example'
    app=create_course_mcp(tmp_path,tmp_path,origin=ORIGIN,allowed_origins=[browser],
                          authorization_server='https://login.example')
    with httpx.Client(transport=httpx.WSGITransport(app=app),base_url=ORIGIN) as client:
        preflight=client.options('/mcp',headers={'Origin':browser,'Access-Control-Request-Method':'POST',
            'Access-Control-Request-Headers':'Content-Type, Authorization, MCP-Protocol-Version'})
        assert preflight.status_code==204
        assert preflight.headers['access-control-allow-origin']==browser
        assert 'mcp-protocol-version' in preflight.headers['access-control-allow-headers'].lower()
        assert 'POST' in preflight.headers['access-control-allow-methods']
        challenge=client.post('/mcp',json={},headers={'Origin':browser})
        assert challenge.status_code==401 and challenge.headers['access-control-allow-origin']==browser
        assert 'www-authenticate' in challenge.headers['access-control-expose-headers'].lower()
        meta=client.get('/.well-known/oauth-protected-resource/mcp',headers={'Origin':browser})
        assert meta.headers['access-control-allow-origin']==browser
        excluded=client.options('/mcp',headers={'Origin':'https://other.example',
                                               'Access-Control-Request-Method':'POST'})
        assert excluded.status_code==403 and 'access-control-allow-origin' not in excluded.headers


def test_empty_http_responses_pass_wsgi_validation(tmp_path):
    from wsgiref.validate import validator
    from examsage.mcp_http import create_course_mcp
    app=validator(create_course_mcp(tmp_path,tmp_path,origin=ORIGIN))
    with httpx.Client(transport=httpx.WSGITransport(app=app),base_url=ORIGIN) as client:
        assert client.get('/mcp').status_code==401
