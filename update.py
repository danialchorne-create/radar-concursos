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
# Consultas focadas em CARGOS PÚBLICOS, não seleções acadêmicas.
QUERIES = [
    'concurso público inscrições abertas procurador São Paulo remuneração',
    'concurso público inscrições abertas auditor fiscal São Paulo salário',
    'concurso público inscrições abertas médico São Paulo remuneração',
    'concurso público inscrições abertas analista judiciário São Paulo salário',
    'concurso público inscrições abertas oficial justiça São Paulo',
    'concurso público inscrições abertas perito médico São Paulo',
    'concurso público inscrições abertas economista São Paulo',
    'concurso público inscrições abertas defensor público São Paulo',
    'concurso público inscrições abertas auditor controle externo São Paulo',
    'concurso público edital médico procurador Santo André',
    'concurso público edital médico procurador São Bernardo do Campo',
    'concurso público edital médico procurador São Caetano do Sul',
    'concurso público edital médico procurador Mauá Diadema',
    'concurso público inscrições abertas médico procurador Osasco',
    'concurso público inscrições abertas auditor médico Taboão da Serra',
    'concurso público inscrições abertas procurador médico Barueri',
    'concurso público inscrições abertas procurador médico Guarulhos',
    'site:prefeitura.sp.gov.br concurso público edital médico procurador',
    'site:tjsp.jus.br concurso público servidor edital inscrições',
    'site:trf3.jus.br concurso público servidor edital inscrições',
    'site:tce.sp.gov.br concurso público auditor inscrições',
    'site:osasco.sp.gov.br concurso público cargos inscrições',
    'site:guarulhos.sp.gov.br concurso público cargos inscrições',
    'site:barueri.sp.gov.br concurso público cargos inscrições',
    'site:taboaodaserra.sp.gov.br concurso público cargos inscrições',
]

AREAS = {
    'Medicina': ['médico', 'médica', 'medicina', 'cirurgião', 'perito médico', 'medico', 'saúde'],
    'Direito': ['procurador', 'defensor', 'promotor', 'magistratura', 'juiz', 'advogado', 'oficial de justiça', 'analista judiciário', 'jurídic', 'juridic', 'delegado'],
    'Economia e Finanças': ['auditor', 'economista', 'fiscal', 'finanças', 'tributári', 'contáb', 'controle externo'],
}
# Termos de localização devem ser checados com fronteiras de palavra.
CITY_NAMES = [
    'santo andré', 'santo andre', 'são bernardo do campo', 'sao bernardo do campo',
    'são caetano do sul', 'sao caetano do sul', 'mauá', 'maua', 'diadema',
    'ribeirão pires', 'ribeirao pires', 'rio grande da serra',
    'osasco', 'taboão da serra', 'taboao da serra', 'barueri', 'guarulhos',
]
CAPITAL = ['são paulo', 'sao paulo']
OTHER_CITIES = [
    'suzano', 'jandira', 'jundiaí', 'jundiai', 'campinas', 'santos',
    'sorocaba', 'ribeirão preto', 'ribeirao preto', 'presidente prudente',
    'bauru', 'cotia', 'carapicuíba', 'carapicuiba', 'embu das artes',
    'mogi das cruzes', 'praia grande', 'são vicente', 'sao vicente',
]
# Esses termos geralmente identificam seleção acadêmica, NÃO um cargo remunerado.
ACADEMIC_REJECTION = [
    'processo seletivo de mestrado', 'seleção para mestrado',
    'selecao para mestrado', 'inscrições para mestrado', 'inscricoes para mestrado',
    'vagas para mestrado', 'mestrado profissional', 'mestrado acadêmico',
    'mestrado academico', 'programa de pós-graduação', 'programa de pos-graduacao',
    'ingresso no mestrado', 'curso de mestrado', 'doutorado acadêmico',
    'doutorado academico', 'bolsa de estudo', 'bolsas de estudo',
    'vestibular', 'processo seletivo discente', 'seleção de alunos',
    'selecao de alunos', 'residência médica', 'residencia medica',
    'seleção para residência', 'selecao para residencia', 'pós-graduação lato sensu',
    'pos-graduacao lato sensu', 'inscrições para cursos', 'inscricoes para cursos',
    'especialização gratuita', 'especializacao gratuita',
]
# Indicadores de cargos, evitando a palavra genérica "concurso" como prova de pertinência.
JOB_TERMS = [
    'procurador', 'médico', 'medico', 'cirurgião', 'cirurgiao',
    'perito', 'auditor', 'fiscal', 'economista', 'defensor público',
    'defensor publico', 'promotor de justiça', 'promotor de justica',
    'juiz', 'magistratura', 'analista judiciário', 'analista judiciario',
    'oficial de justiça', 'oficial de justica', 'delegado', 'advogado',
    'analista de controle', 'analista tributário', 'analista tributario',
    'analista administrativo', 'servidor público', 'servidor publico',
    'nível superior', 'nivel superior', 'cargo público', 'cargo publico',
    'carreira pública', 'carreira publica',
]

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

def has_place(text, term):
    return bool(re.search(r'(?<!\w)' + re.escape(term) + r'(?!\w)', text, re.I))

def loc_from(t):
    low=t.lower()
    included=next((city for city in CITY_NAMES if has_place(low,city)),None)
    outside=next((city for city in OTHER_CITIES if has_place(low,city)),None)
    if included and outside:
        return 'Cidades diferentes citadas — conferir lotação','uncertain'
    if included:
        return included.title()+' citada — confirmar lotação','capital_abc'
    if outside:
        return 'Outra cidade ('+outside.title()+') — fora da região','outside'
    if any(has_place(low,x) for x in CAPITAL):
        # "São Paulo" pode referir-se ao ESTADO, não necessariamente à capital.
        return 'São Paulo citada — confirmar se é capital','uncertain'
    return 'Lotação a verificar','uncertain'

def relevant(text):
    low=text.lower()
    # Primeiro exclui cursos e processos seletivos acadêmicos mesmo quando falam "edital".
    if any(term in low for term in ACADEMIC_REJECTION):
        return False
    # Notícias de concursos para cargos públicos, sem aceitar "edital" isolado.
    if not any(term in low for term in ('concurso público','concurso publico',
                    'concurso para servidores','concurso de servidores',
                    'seleção pública para contratação','selecao publica para contratacao',
                    'processo seletivo para contratação','processo seletivo para contratacao',
                    'processo seletivo simplificado para médicos',
                    'edital de concurso','concurso abre','concurso oferece')):
        return False
    if not any(term in low for term in JOB_TERMS):
        return False
    if not any(has_place(low,x) for x in CITY_NAMES+CAPITAL):
        return False
    # Evita notícias sobre resultado de provas antigas e inscrições fechadas.
    if any(phrase in low for phrase in ('inscrições encerradas','inscricoes encerradas',
            'prazo de inscrição encerrado','prazo de inscricao encerrado',
            'resultado final publicado','gabarito definitivo',
            'homologação do resultado','homologacao do resultado')):
        return False
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
        location,locstatus=loc_from(t)
        if locstatus=='outside':continue
        amount=salary_from(t)
        if amount is not None and amount < 12000:continue
        deadline=deadline_from(t)
        if deadline is not None and deadline<TODAY.isoformat():continue
        rid=hashlib.sha256((r['title'].lower()+r['url']).encode('utf8')).hexdigest()[:16]
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
        note=('Triagem restrita a notícias sobre cargos públicos. Exclui seleções acadêmicas. Prazo e lotação ainda dependem de conferência no edital. '
              + (f'{len(errors)} consulta(s) falharam nesta atualização.' if errors else ''))
    output={'updated_at':dt.datetime.now(dt.timezone.utc).isoformat(),'note':note,'items':candidates[:150]}
    DATA.parent.mkdir(exist_ok=True,parents=True)
    DATA.write_text(json.dumps(output,indent=2,ensure_ascii=False)+'\n',encoding='utf8')
    print(f'{len(found)} notícias, {len(unique)} únicas, {len(candidates)} candidatos, {len(errors)} erros')

if __name__=='__main__':main()
