"""Deterministic CJK character-pair indexing alongside ordinary FTS terms."""
import re
import unicodedata

def cjk_terms(text: str) -> list[str]:
    runs=re.findall(r'[\u3400-\u9fff]+',unicodedata.normalize('NFKC',text))
    return list(dict.fromkeys('zh'+run[i:i+2] for run in runs for i in range(len(run)-1)))

def index_body(record) -> str:
    text=record.text
    chain=record.details.get('derivation',{})
    text+='\n'+'\n'.join(str(step.get(k,'')) for step in chain.get('steps',[]) for k in ['title','text','latex'])
    text+='\n'+'\n'.join(chain.get('conditions',[])+chain.get('warnings',[]))
    return text+'\n'+' '.join(cjk_terms(record.title+' '+' '.join(record.aliases)+' '+text))
