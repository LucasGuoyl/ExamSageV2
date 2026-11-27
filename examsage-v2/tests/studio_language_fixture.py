import json
import sys
import threading
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

kit, tests = map(Path, sys.argv[1:])
sys.path[:0] = [str(kit / 'src'), str(tests)]
from examsage.model_runtime import SubscriptionRuntime
from examsage.student_workspace import Principal, StudentWorkspace
from examsage.study_window import StudyDesk
from examsage.study_host import Studio, StudioHTTP
from test_model_runtime import Wire, completed

def runtime(folder):
    def wire():
        event = {'id':'tool1', 'method':'item/tool/call', 'params':{
            'threadId':'t1', 'turnId':'u1', 'callId':'c1', 'tool':'search_evidence',
            'arguments':{'query':'spring stiffness'}}}
        answer = json.dumps({'paragraphs':[{'text':'The stiffness is 200 N/m.',
            'kind':'source', 'citations':['E1']}], 'limitations':[]})
        return Wire(events=[event, *completed(answer)])
    return SubscriptionRuntime(folder, transport_factory=wire)

with TemporaryDirectory() as folder:
    with closing(StudyDesk(StudentWorkspace(Path(folder), Principal('language-test', frozenset())), runtime_factory=runtime)) as desk:
        with StudioHTTP(Studio(desk)) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            print('http://' + server.authority + '/en/#' + server.capability, flush=True)
            sys.stdin.readline()
            server.shutdown()
            thread.join()
