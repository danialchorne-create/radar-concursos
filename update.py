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
    """Triagem de notícias: mantém oportunidades para revisão sem inventar requisitos.
    RSS do Google Notícias costuma trazer título repetido na descrição e não o edital.
    """
    low=text.lower()
    if any(term in low for term in ACADEMIC_REJECTION):
        return False
    # Exclusões complementares de ingresso em cursos / vagas de alunos.
    if any(term in low for term in ('pós-graduação', 'pos-graduacao',
            'seleção de estudantes', 'selecao de estudantes',
            'curso gratuito', 'concurso cultural', 'concurso literário')):
        return False
    # Não exibir listas de resultados, provas antigas e inscrições já encerradas.
    if any(phrase in low for phrase in ('inscrições encerradas','inscricoes encerradas',
            'prazo de inscrição encerrado','prazo de inscricao encerrado',
            'resultado final publicado','gabarito definitivo',
            'homologação do resultado','homologacao do resultado')):
        return False
    # Identificador genérico de processo seletivo E pelo menos um cargo profissional.
    public_selection = any(term in low for term in (
        'concurso', 'edital', 'processo seletivo', 'seleção pública',
        'selecao publica', 'inscrições abertas', 'inscricoes abertas',
        'vagas para', 'vagas de'))
    professional_job = any(term in low for term in JOB_TERMS)
    return public_selection and professional_job

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

# A etapa seguinte publica SOMENTE inscrições em andamento com informações
# explícitas. Notícias não verificadas NÃO aparecem no painel do candidato.
import unicodedata

def normalized(t):
    return ''.join(c for c in unicodedata.normalize('NFKD', (t or '').lower()) if not unicodedata.combining(c))

NOT_APPLICATION = (
    'resultado', 'resultados', 'gabarito', 'nota de corte', 'notas da prova',
    'notas do concurso', 'classificacao', 'classificados', 'convocacao',
    'convocados', 'homologacao', 'prova aplicada', 'local de prova',
    'retificacao de resultado', 'concurso anterior', 'concurso passado',
    'nomeacao', 'nomeados', 'inscricoes encerradas', 'prazo encerrado',
    'inscricoes prorrogadas em 2025', 'mestrado', 'doutorado',
    'pos-graduacao', 'vestibular', 'residencia medica', 'curso gratuito',
    'bolsas de estudo', 'policia civil do acre',
)
OPEN_SIGNALS = ('inscricoes abertas', 'inscricao aberta', 'inscreva-se', 'periodo de inscricoes', 'inscricoes ate', 'inscricoes vao ate')
CITY_STRICT = (
    'santo andre','sao bernardo do campo','sao caetano do sul','maua',
    'diadema','ribeirao pires','rio grande da serra','osasco',
    'taboao da serra','barueri','guarulhos',
)
CITY_CAPITAL_SIGNALS = ('sao paulo capital', 'capital paulista', 'cidade de sao paulo', 'municipio de sao paulo', 'prefeitura de sao paulo')

# Permitimos cidade somente quando nomeada explicitamente, não apenas "SP"
# ou "Estado de São Paulo". Evita aceitar Acre e qualquer outro estado.
def city_strict(t):
    x=normalized(t)
    for c in CITY_STRICT:
        if has_place(x,c):return c.title()
    if any(z in x for z in CITY_CAPITAL_SIGNALS):return 'São Paulo (capital)'
    return None

def extract_deadline(t):
    x=normalized(t)
    patterns=(
        r'inscricoes?\s+(?:abertas?\s+)?ate\s+(?:o\s+dia\s+)?(\d{1,2})\s*(?:/|de\s+)(\d{1,2}|[a-z]+)\s*(?:/|de\s+)(20\d{2})',
        r'(?:inscricoes?\s+se\s+encerram|prazo\s+de\s+inscricao\s+termina)\s+(?:em|no\s+dia)\s+(\d{1,2})\s*(?:/|de\s+)(\d{1,2}|[a-z]+)\s*(?:/|de\s+)(20\d{2})',
    )
    for pat in patterns:
        for m in re.finditer(pat,x,re.I):
            mon=m.group(2)
            mon=int(mon) if mon.isdigit() else MONTHS.get(mon)
            if not mon:continue
            try: date=dt.date(int(m.group(3)),mon,int(m.group(1)))
            except ValueError:continue
            if TODAY <= date <= TODAY+dt.timedelta(days=120):return date.isoformat()
    return None

def application_signal(title, body):
    title_n=normalized(title); combined=normalized(title+' '+body)
    # A notícia precisa anunciar INSCRIÇÕES, e não resultados de um concurso.
    if any(term in title_n for term in NOT_APPLICATION):return False
    if not any(term in combined for term in OPEN_SIGNALS):return False
    if not any(term in combined for term in ('concurso publico','concurso para','edital de concurso','processo seletivo publico')):return False
    if not any(normalized(word) in combined for word in JOB_TERMS):return False
    return True

def main():
    found=[];errors=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        futures={pool.submit(rss,q):q for q in QUERIES}
        for future in concurrent.futures.as_completed(futures):
            try:found.extend(future.result())
            except Exception as ex:errors.append(f'{futures[future]}: {type(ex).__name__}')
    unique={}
    for article in found:
        if article['url']:unique.setdefault(article['url'],article)
    candidates=[]
    rejects={'nao_e_inscricao_aberta':0,'sem_cidade_confirmada':0,'sem_prazo_valido':0,'sem_salario_confirmado':0,'sem_fonte_oficial':0}
    for r in unique.values():
        headline=r['title']; snippet=r['description']; txt=headline+' '+snippet
        if not application_signal(headline,snippet):
            rejects['nao_e_inscricao_aberta']+=1;continue
        # Endereço de trabalho tem que ser inequívoco já no anúncio.
        city=city_strict(txt)
        if city is None:
            rejects['sem_cidade_confirmada']+=1;continue
        deadline=extract_deadline(txt)
        if not deadline:
            rejects['sem_prazo_valido']+=1;continue
        amount=salary_from(txt)
        if amount is None or amount < 12000:
            rejects['sem_salario_confirmado']+=1;continue
        # O link do Google Notícias pode apontar para uma reportagem.
        # Exibimos apenas quando a URL final é de órgão/banca oficial.
        edital,registration,final=find_official_links(r['url'])
        if not url_is_official(final):
            rejects['sem_fonte_oficial']+=1;continue
        rid=hashlib.sha256((headline.lower()+final).encode('utf8')).hexdigest()[:16]
        candidates.append({
            'id':rid,'title':headline[:175], 'organizer':r['publisher'][:100],
            'area':identify_area(txt),'salary':amount,'deadline':deadline,
            'status':'prazo_identificado','location':city+' — confirmar unidade no edital',
            'location_status':'capital_abc','summary':snippet[:260],
            'source_url':final,'edital_url':edital,'registration_url':registration,
            'published':r['published']
        })
    candidates.sort(key=lambda x:x['published'],reverse=True)
    note=('Filtro conservador: somente notícias com prazo de inscrição vigente, salário >= R$ 12 mil, cidade explícita e fonte oficial. '
          'A presença no painel NÃO comprova a lotação ou a elegibilidade: confira sempre o edital. '
          'O radar pode omitir concursos reais por falta de informação na notícia.')
    if errors:note+=f' {len(errors)} consultas falharam.'
    result={'updated_at':dt.datetime.now(dt.timezone.utc).isoformat(),'note':note,'items':candidates[:150]}
    DATA.parent.mkdir(exist_ok=True,parents=True)
    DATA.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf8')
    print(f'{len(found)} notícias, {len(unique)} únicas, {len(candidates)} anúncios com evidência de inscrição, {len(errors)} erros; descartes: {rejects}')

if __name__=='__main__':main()
