"""Stateless MCP over HTTP. The WSGI host supplies each verified principal."""
from http import HTTPStatus
import json
from pathlib import Path
from urllib.parse import quote_from_bytes, urlsplit

from . import source_component
from .mcp_server import MAX_MESSAGE_BYTES, PROTOCOL_VERSION, MCPServer, decode_message, error
from .plugin_tools import Principal
from .student_workspace import StudentWorkspace, local_workspace, student_tools


def _origin(value):
    parsed = urlsplit(value)
    if (not parsed.hostname or parsed.username is not None or parsed.password is not None or
            parsed.path not in ('','/') or parsed.query or parsed.fragment or '*' in parsed.netloc):
        raise ValueError('Expected a single origin with an explicit scheme and host')
    if parsed.scheme != 'https' and not (parsed.scheme == 'http' and
                                         parsed.hostname in ('127.0.0.1','localhost','::1')):
        raise ValueError('Use HTTPS or a loopback HTTP origin')
    host = parsed.hostname if ':' not in parsed.hostname else f'[{parsed.hostname}]'
    if parsed.port not in (None,443 if parsed.scheme=='https' else 80):
        host += f':{parsed.port}'
    return parsed.scheme+'://'+host


def _accepts_json_rpc(accept):
    types = set()
    for item in accept.lower().split(','):
        name,*params = (part.strip() for part in item.split(';'))
        quality = next((p.partition('=')[2] for p in params if p.startswith('q=')),'1')
        try:
            if 0 < float(quality) <= 1:
                types.add(name)
        except ValueError:
            continue
    return {'application/json','text/event-stream'} <= types


def _read_body(environ):
    size = environ.get('CONTENT_LENGTH','')
    if size:
        if not size.isascii() or not size.isdecimal() or len(size)>19:
            return 400,None
        length = int(size)
        if length > MAX_MESSAGE_BYTES:
            return 413,None
        body = environ['wsgi.input'].read(length)
        if len(body) != length:
            return 400,None
    elif environ.get('wsgi.input_terminated') is True:
        body = environ['wsgi.input'].read(MAX_MESSAGE_BYTES+1)
        if len(body) > MAX_MESSAGE_BYTES:
            return 413,None
    else:
        return 411,None
    try:
        return 200,decode_message(body)
    except (ValueError,UnicodeError,RecursionError):
        return 400,None


def create_course_mcp(library: Path | None, student_root: Path, *, origin: str, allowed_origins=(),
                      authorization_server: str | None = None):
    """Create a /mcp WSGI application; only a server-set Principal grants access."""
    public_origin = _origin(origin)
    allowed = {public_origin,*(_origin(item) for item in allowed_origins)}
    parsed = urlsplit(public_origin)
    hosts = {parsed.netloc}
    if parsed.port is None:
        hosts.add(parsed.netloc+(':443' if parsed.scheme=='https' else ':80'))
    root = Path(student_root).resolve()
    library = Path(library).resolve() if library is not None else None
    metadata_path = '/.well-known/oauth-protected-resource/mcp'
    if authorization_server is not None:
        issuer = urlsplit(authorization_server)
        if (issuer.scheme != 'https' or not issuer.hostname or issuer.username is not None
                or issuer.password is not None or issuer.query or issuer.fragment):
            raise ValueError('Expected an HTTPS authorization server issuer URL')

    def application(environ, start_response):
        method = environ['REQUEST_METHOD']
        browser_origin = environ.get('HTTP_ORIGIN')
        mount = quote_from_bytes(environ.get('SCRIPT_NAME','').rstrip('/').encode('latin-1'),safe='/')
        resource_base = public_origin+mount

        def respond(status, message=None, *, headers=()):
            body = b'' if message is None else json.dumps(message,allow_nan=False).encode('utf-8')
            fields = [('Cache-Control','no-store'),('X-Content-Type-Options','nosniff'),('Vary','Origin'),*headers]
            if status != 204:
                fields.extend([('Content-Length',str(len(body))),
                               ('Content-Type','application/json' if message is not None else 'text/plain')])
            if browser_origin in allowed:
                fields.extend([('Access-Control-Allow-Origin',browser_origin),
                               ('Access-Control-Expose-Headers','WWW-Authenticate')])
            start_response(f'{status} {HTTPStatus(status).phrase}',fields)
            return [b'' if method=='HEAD' else body]

        # Compare the host chosen by the gateway with the configured public origin.
        host = environ.get('HTTP_HOST','').lower()
        if host not in hosts or (browser_origin is not None and browser_origin not in allowed):
            return respond(403)
        metadata = authorization_server is not None and environ['PATH_INFO']==metadata_path
        if not metadata and environ['PATH_INFO'] != '/mcp':
            return respond(404)
        if method=='OPTIONS' and browser_origin is not None:
            allowed_methods = ('GET','HEAD') if metadata else ('POST',)
            allowed_headers = ('accept','authorization','content-type','mcp-protocol-version')
            requested = {h.strip().lower() for h in environ.get('HTTP_ACCESS_CONTROL_REQUEST_HEADERS','').split(',')
                         if h.strip()}
            if (environ.get('HTTP_ACCESS_CONTROL_REQUEST_METHOD') not in allowed_methods
                    or not requested.issubset(allowed_headers)):
                return respond(403)
            return respond(204,headers=[('Access-Control-Allow-Methods',', '.join(allowed_methods)),
                                        ('Access-Control-Allow-Headers',', '.join(allowed_headers))])
        if metadata:
            if method not in ('GET','HEAD'):
                return respond(405,headers=[('Allow','GET, HEAD')])
            return respond(200,{'resource':resource_base+'/mcp','authorization_servers':[authorization_server]})
        principal = environ.get('examsage.principal')
        if not isinstance(principal,Principal):
            challenge = 'Bearer realm="examsage"'
            if authorization_server is not None:
                challenge += f', resource_metadata="{resource_base}{metadata_path}"'
            return respond(401,headers=[('WWW-Authenticate',challenge)])
        if method != 'POST':
            return respond(405,headers=[('Allow','POST')])
        if not _accepts_json_rpc(environ.get('HTTP_ACCEPT','')):
            return respond(406)
        if environ.get('CONTENT_TYPE','').split(';',1)[0].strip().lower()!='application/json':
            return respond(415)
        status,message = _read_body(environ)
        if status != 200:
            return respond(status,error(None,-32700,'Invalid or unavailable JSON message'))
        if not isinstance(message,dict) or message.get('jsonrpc')!='2.0' or not isinstance(message.get('method'),str):
            return respond(400,error(None,-32600,'Expected one JSON-RPC request or notification'))
        initial = message['method']=='initialize' and 'id' in message
        version = environ.get('HTTP_MCP_PROTOCOL_VERSION')
        if version != PROTOCOL_VERSION and not (initial and version is None):
            return respond(400,error(None,-32600,'Unsupported MCP protocol version'))
        workspace = StudentWorkspace(root,principal)
        tools = student_tools(library,workspace)
        # Stateless HTTP has no shared handshake or student session. The client sends
        # the negotiated protocol version with each post-initialization request.
        server = MCPServer(tools,initialized=not initial,source_component=source_component)
        reply = server.handle(message)
        if reply is None:
            return respond(202)
        return respond(400 if reply.get('error',{}).get('code') == -32600 else 200,reply)

    return application


def serve_local(library, student_root, courses, port):
    """Developer entry for a single OS user. A hosting service must inject its own identities."""
    from wsgiref.simple_server import make_server
    if not 1 <= port <= 65535:
        raise ValueError('端口应在 1 至 65535 之间。')
    workspace = local_workspace(student_root,courses)
    if set(courses) != set(workspace.public_entries(library)):
        raise ValueError('所选课程未登记，或不在该学生当前的授权范围。')
    origin = f'http://127.0.0.1:{port}'
    endpoint = create_course_mcp(library,student_root,origin=origin)

    def local_app(environ,start_response):
        if environ.get('REMOTE_ADDR')=='127.0.0.1':
            environ['examsage.principal'] = workspace.principal
        return endpoint(environ,start_response)

    with make_server('127.0.0.1',port,local_app) as server:
        print(f'押题宝本机课程 MCP：{origin}/mcp',flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
