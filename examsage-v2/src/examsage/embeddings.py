"""Optional embedding adapter; no network calls unless explicitly configured."""
from __future__ import annotations

import json
import math
from pathlib import Path
import sqlite3
from urllib.request import Request, urlopen
from urllib.parse import urlparse

from .domain import digest


def unit(vector):
    if not vector or not all(isinstance(x,(float,int)) and math.isfinite(x) for x in vector):
        raise ValueError("embedding must be a finite nonempty numeric vector")
    norm=math.sqrt(sum(x*x for x in vector))
    if not norm:
        raise ValueError("zero embedding vector")
    return [x/norm for x in vector]


class VectorIndex:
    def __init__(self, path: Path, route: str):
        self.path, self.route = path, route
        path.parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS vectors(snapshot TEXT, route TEXT, id TEXT, vector TEXT, PRIMARY KEY(snapshot,route,id))")

    def replace(self, snapshot: str, vectors: dict[str,list[float]]):
        values={key:unit(value) for key,value in vectors.items()}
        if len({len(v) for v in values.values()})>1:
            raise ValueError("mixed embedding dimensions")
        with sqlite3.connect(self.path) as db:
            db.execute("DELETE FROM vectors WHERE snapshot=? AND route=?", (snapshot,self.route))
            db.executemany("INSERT INTO vectors VALUES(?,?,?,?)", [(snapshot,self.route,k,json.dumps(v)) for k,v in values.items()])

    def rank(self, snapshot: str, query: list[float], allowed: set[str], limit=80):
        if not allowed:
            return []
        query=unit(query)
        results=[]
        with sqlite3.connect(self.path) as db:
            for rid,payload in db.execute("SELECT id,vector FROM vectors WHERE snapshot=? AND route=?",(snapshot,self.route)):
                if rid not in allowed:
                    continue
                vector=json.loads(payload)
                if len(vector)!=len(query):
                    raise ValueError("embedding route dimension mismatch")
                results.append((rid,sum(a*b for a,b in zip(query,vector))))
        return sorted(results,key=lambda x:(-x[1],x[0]))[:limit]


class EmbeddingClient:
    def __init__(self, base_url: str, api_key: str, model: str):
        parsed=urlparse(base_url)
        if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.query:
            raise ValueError("embedding endpoint must be an HTTPS origin/path without credentials/query")
        self.url=base_url.rstrip('/')+'/embeddings'
        self.key,self.model=api_key,model
        self.route=digest([base_url,model,"unit-v1"])

    def embed(self, texts: list[str]) -> list[list[float]]:
        body=json.dumps({'model':self.model,'input':texts}).encode()
        req=Request(self.url,data=body,headers={'Authorization':'Bearer '+self.key,'Content-Type':'application/json'})
        try:
            with urlopen(req,timeout=60) as response:
                data=json.load(response)
            rows=sorted(data['data'],key=lambda x:x['index'])
            if [r['index'] for r in rows]!=list(range(len(texts))):
                raise ValueError('embedding response indices mismatch')
            return [unit(r['embedding']) for r in rows]
        except Exception:
            raise RuntimeError('Embedding request failed; endpoint response not logged.') from None
