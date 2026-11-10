#!/usr/bin/env python3
"""Radar de concursos: triagem automatizada de notícias públicas recentes.

Não certifica abertura/lotação. Data e salário são inferidos apenas quando explicitamente citados.
Sem dependências externas; execução agendada pelo GitHub Actions.
"""
import concurrent.futures
import datetime as dt
import hashlib
import html
import json
import os
from pathlib import Path
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

BASE = Path(__file__).parent
DATA = BASE / 'data' / 'concursos.json'
TODAY = dt.datetime.now(dt.timezone(dt.timedelta(hours=-3))).date()
QUERIES = [
    'concurso inscrições abertas "procurador" "São Paulo" salário',
    'concurso inscrições abertas "auditor fiscal" "São Paulo" edital',
    'concurso inscrições abertas "médico" "São Paulo" remuneração',
    'concurso inscrições abertas "médico" "Santo André" salário',
    'concurso inscrições abertas "médico" "São Bernardo do Campo" salário',
    'concurso inscrições abertas "médico" "São Caetano do Sul" salário',
    'concurso inscrições abertas "procurador" "Santo André"',
    'concurso inscrições abertas "procurador" "São Bernardo do Campo"',
    'concurso inscrições abertas "procurador" "São Caetano do Sul"',
    'concurso inscrições abertas "analista judiciário" "São Paulo"',
    'concurso inscrições abertas "oficial de justiça" "São Paulo"',
    'concurso inscrições abertas "perito médico" "São Paulo"',
    'concurso inscrições abertas "economista" "São Paulo"',
    'concurso inscrições abertas "auditor controle externo" "São Paulo"',
    'concurso inscrições abertas "defensor público" "São Paulo"',
    'site:prefeitura.sp.gov.br concurso inscrições médico procurador',
    'site:tjsp.jus.br concurso edital inscrições',
    'site:trf3.jus.br concurso edital inscrições',
    'site:tce.sp.gov.br concurso auditor inscrições',
    'site:usp.br concurso médico inscrições',
]
AREAS = {
    'Medicina': ['médico', 'médica', 'medicina', 'cirurgião', 'perito médico', 'medico', 'saúde'],
    'Direito': ['procurador', 'defensor', 'promotor', 'magistratura', 'juiz', 'advogado', 'oficial de justiça', 'analista judiciário', 'jurídic', 'juridic', 'delegado'],
    'Economia e Finanças': ['auditor', 'economista', 'fiscal', 'finanças', 'tributári', 'contáb', 'controle externo'],
}
LOCATIONS = ['são paulo', 'sao paulo', 'santo andré', 'santo andre', 'são bernardo', 'sao bernardo', 'são caetano', 'sao caetano', 'mauá', 'maua', 'diadema', 'ribeirão pires', 'rio grande da serra']
FAR = ['suzano', 'jandira', 'jundiaí', 'jundiai', 'campinas', 'santos', 'sorocaba', 'ribeirão preto', 'ribeirao preto', 'presidente prudente', 'bauru', 'guarulhos', 'osasco']
MONTHS = {'janeiro':1,'fevereiro':2,'março':3,'marco':3,'abril':4,'maio':5,'junho':6,'julho':7,'agosto':8,'setembro':9,'outubro':10,'novembro':11,'dezembro':12}
SALARY = re.compile(r'R\$\s*(\d{1,3}(?:\.\d{3})*(?:,\d{2})?|\d{4,7}(?:,\d{2})?)', re.I)
DATE = re.compile(r'\b(?:até|ate|encerra(?:m)?(?: em)?|inscriç(?:ões|oes) até|prazo até)\s*(?:o dia |dia )?(\d{1,2})\s*(?:/|de\s+)(\d{1,2}|[a-zçãé]+)\s*(?:/|de\s+)(20\d{2})\b', re.I)
BANCA_DOMAINS = ('vunesp.com.br','concursosfcc.com.br','conhecimento.fgv.br','cebraspe.org.br','institutoaocp.org.br','ibfc.org.br','nossorumo.org.br')
OFFICIAL_DOMAINS = ('gov.br','sp.gov.br','jus.br','leg.br','usp.br','unesp.br','unicamp.br')
UA = 'RadarConcursos-SP/1.0 (monitoramento público; GitHub Actions)'

def get(url, max_bytes=900_000):
    req = urllib.request.Request(url, headers={'User-Agent':UA, 'Accept':'application/rss+xml, application/xml, text/html'})
    with urllib.request.urlopen(req, timeout=18) as response:
        return response.read(max_bytes).decode('utf-8', errors='replace'), response.geturl()

def remove_tags(t):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]*>', ' ', t or ''))).strip()

def rss(q):
    url = 'https://news.google.com/rss/search?' + urllib.parse.urlencode({'q':q+' when:30d','hl':'pt-BR','gl':'BR','ceid':'BR:pt-419'})
    raw,_ = get(url)
    root = ET.fromstring(raw)
    result=[]
    for node in root.findall('./channel/item'):
        def field(name):
            el=node.find(name)
            return (el.text or '').strip() if el is not None else ''
        pub=field('pubDate')
        try: published=parsedate_to_datetime(pub).date()
        except (ValueError,TypeError): continue
        if published < TODAY-dt.timedelta(days=30) or published>TODAY+dt.timedelta(days=1):continue
        result.append({'title':remove_tags(field('title')),'description':remove_tags(field('description')),'url':field('link'),'published':published.isoformat(),'publisher':field('source')})
    return result

def salary_from(t):
    values=[]
    for m in SALARY.finditer(t):
        try: value=float(m.group(1).replace('.','').replace(',','.'))
        except ValueError:continue
        if 1000 <= value <= 150000: values.append(value)
    # Multiple salaries in a general advertisement are ambiguous: show none instead of inventing a specific salary.
    return values[0] if len(values)==1 else None

def deadline_from(t):
    for m in DATE.finditer(t):
        mo=m.group(2).lower()
        mo=int(mo) if mo.isdigit() else MONTHS.get(mo)
        if mo is None:continue
        try: d=dt.date(int(m.group(3)),mo,int(m.group(1)))
        except ValueError:continue
        if TODAY <= d <= TODAY+dt.timedelta(days=120):return d.isoformat()
    return None

def identify_area(t):
    t=t.lower(); scores={a:sum(1 for token in words if token in t) for a,words in AREAS.items()}
    winner=max(scores,key=scores.get)
    return winner if scores[winner] else 'Geral'

def loc_from(t):
    lower=t.lower()
    # SP in a generic headline can describe the state, not a confirmed workplace.
    found=[x for x in LOCATIONS if x in lower]
    far=any(x in lower for x in FAR)
    if far and not any(x in lower for x in LOCATIONS[2:]):return 'Outra cidade citada — verificar', 'uncertain'
    if any(x in lower for x in LOCATIONS[2:]):return 'ABC citado — confirmar no edital','capital_abc'
    if 'são paulo' in lower or 'sao paulo' in lower:return 'São Paulo citada — confirmar lotação','uncertain'
    return 'Lotação a verificar','uncertain'

def relevant(text):
    l=text.lower()
    if not any(k in l for k in ['concurso','edital','seleção pública','selecao publica']):return False
    if not any(k in l for k in LOCATIONS):return False
    if not any(w in l for terms in AREAS.values() for w in terms) and 'nível superior' not in l:return False
    return True

def url_is_official(url):
    try: host=urllib.parse.urlparse(url).hostname or ''
    except Exception:return False
    return any(host==d or host.endswith('.'+d) for d in OFFICIAL_DOMAINS+BANCA_DOMAINS)

def find_official_links(url):
    """Enrich *only* when original source resolves to a government/court/university/banca page.
       HTML anchor text is explicitly validated so generic landing pages aren't labeled edital.
    """
    try:
        page,final=get(url)
        if not url_is_official(final):return None,None,final
        links=re.findall(r'<a\b([^>]*\bhref\s*=\s*["\']([^"\']+)["\'][^>]*)>(.*?)</a\s*>',page,re.I|re.S)
        edital=registration=None
        for _,href,body in links:
            address=urllib.parse.urljoin(final,html.unescape(href))
            if not url_is_official(address) or not address.startswith('https://'):continue
            anchor=remove_tags(body).lower()
            if not edital and ('edital' in anchor or 'edital' in href.lower()) and ('pdf' in href.lower() or 'edital' in anchor):edital=address
            if not registration and any(p in anchor for p in ('inscreva-se','inscrições','inscricao','inscrição','fazer inscrição')):registration=address
        return edital,registration,final
    except Exception:return None,None,url

def main():
    old={}
    if DATA.exists():
        try:old={x['id']:x for x in json.loads(DATA.read_text(encoding='utf8')).get('items',[])}
        except (ValueError,KeyError):pass
    found=[]; errors=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        futures={pool.submit(rss,q):q for q in QUERIES}
        for future in concurrent.futures.as_completed(futures):
            try: found.extend(future.result())
            except Exception as ex:errors.append(f'{futures[future]}: {type(ex).__name__}')
    unique={}
    for f in found:
        if f['url']:unique.setdefault(f['url'],f)
    candidates=[]
    for r in unique.values():
        t=(r['title']+' '+r['description'])
        if not relevant(t):continue
        amount=salary_from(t)
        if amount is not None and amount < 12000:continue
        deadline=deadline_from(t)
        if deadline is not None and deadline<TODAY.isoformat():continue
        rid=hashlib.sha256((r['title'].lower()+r['url']).encode('utf8')).hexdigest()[:16]
        location,locstatus=loc_from(t)
        item={'id':rid,'title':r['title'][:175],'organizer':r['publisher'][:100], 'area':identify_area(t),'salary':amount, 'deadline':deadline, 'status':'prazo_identificado' if deadline else 'a_verificar', 'location':location, 'location_status':locstatus,'summary':r['description'][:260] or 'Leia a fonte e o edital para confirmar as informações.', 'source_url':r['url'], 'edital_url':None,'registration_url':None,'published':r['published']}
        if rid in old:
            prev=old[rid]
            item['edital_url']=prev.get('edital_url')
            item['registration_url']=prev.get('registration_url')
        candidates.append(item)
    candidates.sort(key=lambda x:x['published'],reverse=True)
    # Limit external page fetches to minimize burden and avoid Google News redirect parsing.
    for item in candidates[:35]:
        if item['edital_url'] and item['registration_url']:continue
        edital,registration,resolved=find_official_links(item['source_url'])
        item['edital_url']=item['edital_url'] or edital
        item['registration_url']=item['registration_url'] or registration
        if url_is_official(resolved):item['source_url']=resolved
    if errors and not found and old:
        # Don't wipe a prior successful set on total upstream failure.
        candidates=list(old.values())
        note='Erro nas buscas atuais; exibindo a última coleta disponível. Conferir os prazos manualmente.'
    else:
        note=('Triagem de notícias públicas dos últimos 30 dias. Não garante inscrições abertas nem lotação. '
              + (f'{len(errors)} consulta(s) falharam nesta atualização.' if errors else ''))
    output={'updated_at':dt.datetime.now(dt.timezone.utc).isoformat(),'note':note,'items':candidates[:150]}
    DATA.parent.mkdir(exist_ok=True,parents=True)
    DATA.write_text(json.dumps(output,indent=2,ensure_ascii=False)+'\n',encoding='utf8')
    print(f'{len(found)} notícias, {len(unique)} únicas, {len(candidates)} candidatos, {len(errors)} erros')

if __name__=='__main__':main()
