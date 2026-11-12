#!/usr/bin/env python3
"""Radar de concursos: descoberta em bancas/órgãos e validação em páginas oficiais.

A lista 'abertos' é conservadora; 'revisao' NUNCA é apresentada como inscrição confirmada.
Este script não substitui a leitura de edital e não garante cobertura exaustiva.
"""
from __future__ import annotations
import concurrent.futures
from collections import Counter
from threading import Lock
from datetime import datetime, date, timedelta, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import os
from pathlib import Path
import re
import time
import unicodedata
from urllib.parse import urlencode, urljoin, urlparse
import requests
from bs4 import BeautifulSoup
from io import BytesIO
from pypdf import PdfReader

ROOT=Path(__file__).resolve().parent
OUTPUT=ROOT/'data'/'concursos.json'
BRT=timezone(timedelta(hours=-3))
TODAY=datetime.now(BRT).date()
MIN_SALARY=15000
USER_AGENT='Mozilla/5.0 (compatible; RadarConcursosSP/5.0; public-edital-monitor)'
DIAG=Counter()
DIAG_LOCK=Lock()
def rejected(reason):
    with DIAG_LOCK: DIAG[reason] += 1
    return None
SESSION=requests.Session()
SESSION.headers.update({'User-Agent':USER_AGENT,'Accept-Language':'pt-BR,pt;q=0.9','Accept':'text/html,application/pdf;q=0.9,*/*;q=0.8'})
TRUSTED_DOMAINS=(
    'vunesp.com.br','concursosfcc.com.br','fcc.org.br','pciconcursos.com.br','conhecimento.fgv.br',
    'cebraspe.org.br','institutoaocp.org.br','ibfc.org.br',
    'nossorumo.org.br','gov.br','sp.gov.br','jus.br','leg.br',
    'usp.br','unesp.br','unicamp.br','fundacaofat.org.br',
)
# NÃO adicionamos o nome de um estado como evidência de cidade de trabalho.
CITIES={
 'sao paulo':'São Paulo (capital)', 'santo andre':'Santo André',
 'sao bernardo do campo':'São Bernardo do Campo','sao caetano do sul':'São Caetano do Sul',
 'maua':'Mauá','diadema':'Diadema','ribeirao pires':'Ribeirão Pires',
 'rio grande da serra':'Rio Grande da Serra','osasco':'Osasco',
 'taboao da serra':'Taboão da Serra','barueri':'Barueri','guarulhos':'Guarulhos'
}
CAPITAL_MARKERS=('prefeitura de sao paulo','municipio de sao paulo','cidade de sao paulo',
                 'sao paulo capital','capital paulista','comarca da capital')
OUTSIDE=( 'acre','rio branco - ac','manaus','amazonas','goias','goiania','rio de janeiro',
          'belo horizonte','minas gerais','espirito santo','vitoria - es','parana',
          'curitiba','santa catarina','rio grande do sul','porto alegre',
          'mato grosso do sul','campo grande - ms','paraiba','ceara','pernambuco',
          'jandira','suzano','jundiai','campinas','santos','sorocaba',
          'mogi das cruzes','cotia','carapicuiba','itapevi','franco da rocha')
DISQUALIFY_TITLE=(
 'resultado','gabarito','nota','notas','pontuacao','classificacao',
 'convocacao','convocados','nomeacao','nomeados','homologacao','provas realizadas',
 'local de prova','prova objetiva','retificacao de resultado',
 'mestrado','doutorado','pos-graduacao','vestibular','residencia medica',
 'residencia multiprofissional','bolsa de estudo','curso livre','estagio',
 'processo seletivo discente','concurso interno','prorrogacao de validade'
)
ACADEMIC_TERMS=( 'selecao de alunos','ingresso de alunos','programa de pos-graduacao',
 'mestrado','doutorado','vestibular','residencia medica','pos-graduacao stricto sensu',
 'especializacao academica','bolsa de estudo','cursos gratuitos',
 'concurso literario','concurso cultural','concurso interno')
CAREERS={
 'Medicina':('medico','medica','cirurgiao','clinico geral','pericia medica','medicina'),
 'Direito':('procurador','defensor publico','promotor de justica','juiz','magistratura',
           'oficial de justica','analista judiciario','advogado publico','delegado'),
 'Economia e Finanças':('auditor fiscal','auditor de controle','auditor de contas',
            'analista de financas','economista','analista tributario',
            'fiscal de tributos','analista de planejamento','analista em planejamento'),
 'Geral nível superior':('analista administrativo','analista de gestao','especialista em politicas',
                           'cargo de nivel superior','nivel superior em qualquer area','professor universitario','docente universitario')
}
# Fontes diretas: páginas oficiais de concursos ou mecanismos internos da banca.
DIRECT_SOURCES=[
 ('Vunesp - Direito','https://www.vunesp.com.br/?b=PROCURADOR'),
 ('Vunesp - Medicina','https://www.vunesp.com.br/?b=MEDICO'),
 ('Vunesp - Auditoria','https://www.vunesp.com.br/?b=AUDITOR'),
 ('Vunesp - São Paulo','https://www.vunesp.com.br/?b=SAO%20PAULO'),
 ('Vunesp - Guarulhos','https://www.vunesp.com.br/?b=GUARULHOS'),
 ('Vunesp - Osasco','https://www.vunesp.com.br/?b=OSASCO'),
 ('FCC - inscrições abertas','https://www1.concursosfcc.com.br/'),
 ('PCI - concursos SP','https://www.pciconcursos.com.br/pesquisa/concursos-estado-de-sp'),
 ('PCI - capital','https://www.pciconcursos.com.br/concursos/sp/sao-paulo'),
 ('FGV - concursos','https://conhecimento.fgv.br/concursos'),
]
# Motor de descoberta é complementar: os links só são aproveitados DEPOIS de
# abrir e validar o conteúdo na própria banca ou órgão.
SITE_QUERIES=[
 'site:vunesp.com.br concurso procurador inscricoes 2026',
 'site:vunesp.com.br concurso medico inscricoes 2026',
 'site:vunesp.com.br concurso auditor inscricoes 2026',
 'site:concursosfcc.com.br concurso sao paulo inscricoes 2026',
 'site:conhecimento.fgv.br/concursos sao paulo edital 2026',
 'site:prefeitura.sp.gov.br concurso publico inscricoes medico procurador 2026',
 'site:osasco.sp.gov.br concurso publico inscricoes 2026',
 'site:guarulhos.sp.gov.br concurso publico inscricoes 2026',
 'site:barueri.sp.gov.br concurso publico inscricoes 2026',
 'site:taboaodaserra.sp.gov.br concurso publico inscricoes 2026',
 'site:trf3.jus.br concurso publico 2026 inscricoes',
 'site:tce.sp.gov.br concurso inscricoes 2026',
]
MONTHS={'janeiro':1,'fevereiro':2,'marco':3,'abril':4,'maio':5,'junho':6,
        'julho':7,'agosto':8,'setembro':9,'outubro':10,'novembro':11,'dezembro':12}
SALARY_RE=re.compile(r'R\$\s*([\d\.]+,\d{2}|\d{4,6})',re.I)
YEAR_RE=re.compile(r'20(?:2[5-9]|3\d)')
VUNESP_DETAIL=re.compile(r'^/[A-Z]{3,6}\d{4}(?:/)?$')


def norm(s):
    return ''.join(c for c in unicodedata.normalize('NFKD',str(s or '').lower())
                   if not unicodedata.combining(c))

def words_has(s,term):
    return bool(re.search(r'(?<!\w)'+re.escape(term)+r'(?!\w)',s))

def trusted(url):
    p=urlparse(url)
    if p.scheme!='https' or not p.hostname: return False
    h=p.hostname.lower()
    return any(h==d or h.endswith('.'+d) for d in TRUSTED_DOMAINS)

def fetch(url):
    """Fetch HTML or PDF from allow-listed domains, preserving type for parsing."""
    if not trusted(url): raise ValueError('URL não é de fonte permitida')
    r=SESSION.get(url,timeout=18,allow_redirects=True)
    r.raise_for_status()
    if not trusted(r.url): raise ValueError('Redirecionamento externo não permitido')
    if len(r.content)>8_000_000:raise ValueError('Documento acima do limite')
    kind=r.headers.get('content-type','').lower()
    if 'pdf' in kind or r.content[:4]==b'%PDF':
        try:
            pdf=PdfReader(BytesIO(r.content),strict=False)
            pages=[]
            for page in pdf.pages[:25]:
                pages.append((page.extract_text() or '')[:12000])
            return ' '.join(pages)[:60000],r.url,'pdf'
        except Exception as exc:
            raise ValueError('Falha ao ler PDF: '+type(exc).__name__)
    return r.text,r.url,'html'

def source_links(page,base):
    soup=BeautifulSoup(page,'html.parser')
    result=[]
    for a in soup.find_all('a',href=True):
        href=urljoin(base,a.get('href',''))
        if not trusted(href):continue
        path=urlparse(href).path
        label=a.get_text(' ',strip=True)
        if (VUNESP_DETAIL.match(path) or ('concurso' in norm(href) and len(label)>5)
            or ('edital' in norm(href) and len(label)>5) or
            ('pciconcursos.com.br' in urlparse(href).netloc and 'noticias/' in href and len(label)>10)):
            result.append(href)
    return result

def discover():
    pool=[]; errors=[]
    for name,url in DIRECT_SOURCES:
        try:
            raw,final,kind=fetch(url)
            if raw and kind=='html':
                pool+=source_links(raw,final)
                # Algumas fontes têm a página do certame como destino direto.
                if VUNESP_DETAIL.match(urlparse(final).path):pool.append(final)
        except Exception as e: errors.append(f'{name}: {type(e).__name__}')
    # Bing RSS entrega URLs de resultado; nunca usamos seu texto como evidência.
    for query in SITE_QUERIES:
        try:
            rss='https://www.bing.com/search?'+urlencode({'q':query,'format':'rss'})
            response=SESSION.get(rss,timeout=14)
            response.raise_for_status()
            soup=BeautifulSoup(response.content,'xml')
            for node in soup.find_all('item'):
                link=node.find('link')
                if link and link.get_text(strip=True) and trusted(link.get_text(strip=True)):
                    pool.append(link.get_text(strip=True))
        except Exception as e:errors.append(f'Pesquisa complementar: {type(e).__name__}')
    # Limite operacional evita milhares de páginas ou bloqueios das fontes.
    return list(dict.fromkeys(pool))[:240],errors

def career(title,body):
    t=norm(title+' '+body[:900])
    for name,terms in CAREERS.items():
        if any(words_has(t,x) for x in terms):return name
    return None

def parse_date(d,m,y=None):
    mon=MONTHS.get(norm(m)) if not m.isdigit() else int(m)
    if not mon:return None
    year=int(y) if y else TODAY.year
    try:out=date(year,mon,int(d))
    except ValueError:return None
    if not y:
        # Intervalos com ano omitido em portais; só inferimos ano em janela próxima.
        if out < TODAY-timedelta(days=75):
            try:out=out.replace(year=year+1)
            except ValueError:return None
    return out

DATE_TOKEN=r'(\d{1,2})\s*(?:/|de\s+)(\d{1,2}|janeiro|fevereiro|mar[cç]o|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)(?:\s*(?:/|de\s+)(20\d{2}))?'
DEADLINE_PATTERNS=(
 re.compile(r'inscricoes?\s+(?:se\s+)?(?:encerram|terminam)\s+em\s+'+DATE_TOKEN,re.I),
 re.compile(r'(?:inscri(?:c|ç)(?:ao|ões|oes|ões|ao)|inscri(?:c|ç)oes)\s*(?:abertas?\s*)?(?:ate|terminam\s+em|encerram\s+em)\s*(?:o\s+dia\s*)?'+DATE_TOKEN,re.I),
 re.compile(r'(?:prazo\s+de\s+inscricoes|periodo\s+de\s+inscricoes)[^.\n]{0,100}?(?:ate|a)\s*'+DATE_TOKEN,re.I),
)
DATE_SIMPLE=re.compile(r'(\d{1,2})/(\d{1,2})(?:/(20\d{2}))?')

def registration_deadline(text):
    t=norm(text)
    # Regra explícita: primeiro uma frase de inscrições com data de encerramento.
    for regex in DEADLINE_PATTERNS:
        for match in regex.finditer(t):
            d=parse_date(*match.groups())
            if d and TODAY<=d<=TODAY+timedelta(days=130):return d
    # Formato direto da página específica da Vunesp: 'Inscrições: 28/10 10/12'.
    p=re.search(r'inscricoes\s*:\s*(\d{1,2}/\d{1,2}(?:/20\d{2})?)\s+(\d{1,2}/\d{1,2}(?:/20\d{2})?)',t)
    if p:
        starts=DATE_SIMPLE.fullmatch(p.group(1)); ends=DATE_SIMPLE.fullmatch(p.group(2))
        if starts and ends:
            a=parse_date(*starts.groups()); b=parse_date(*ends.groups())
            if a and b and b<a:
                b=parse_date(ends.group(1),ends.group(2),str(a.year+1))
            if a and b and a<=TODAY<=b and b<=TODAY+timedelta(days=130):return b
    return None

def salary_for_job(title,text):
    t=norm(text)
    # Em editais com vários cargos, o maior salário é FAIXA, não é salário do cargo alvo.
    if 'faixa salarial' in t or 'salarios de r$' in t or 'salarios entre' in t:
        return None,'Faixa salarial de vários cargos: conferir salário do cargo'
    matches=[]
    for m in SALARY_RE.finditer(text):
        try:n=float(m.group(1).replace('.','').replace(',','.'))
        except ValueError:continue
        if 1000<=n<=150000:matches.append(n)
    amounts=sorted(set(matches))
    if len(amounts)==1:return amounts[0],None
    if len(amounts)>1:return None,'Múltiplos valores: não é possível atribuir ao cargo'
    return None,'Salário não informado na página'

def location(title,text):
    t=norm(title+' '+text[:900]); head=norm(title+' '+text[:480])
    # Prefeitura indica cidade do órgão, mas prova em cidade não garante lotação.
    match=re.search(r'prefeitura\s+(?:municipal\s+)?de\s+([a-z\s]+?)(?:\s*[-–|:]|\s*\(|$)',head)
    if match:
        candidate=match.group(1).strip()
        for city,label in CITIES.items():
            if candidate==city or candidate.startswith(city+' '):return label,'municipal'
    if any(x in head for x in CAPITAL_MARKERS):return 'São Paulo (capital)','capital'
    seen=[label for city,label in CITIES.items() if city!='sao paulo' and words_has(t,city)]
    seen=list(dict.fromkeys(seen))
    if len(seen)==1:
        # Citação da cidade não comprova lotação; sempre revisão.
        return seen[0],'citada'
    return 'Lotação não confirmada','indefinida'

def open_links(soup,url):
    edital=inscricao=None
    for a in soup.find_all('a',href=True):
        link=urljoin(url,a.get('href',''))
        if not trusted(link):continue
        label=norm(a.get_text(' ',strip=True))
        if not edital and ('edital de abertura' in label or 'edital completo' in label or (label=='edital')):
            edital=link
        if not inscricao and any(s in label for s in ('inscreva-se','fazer inscricao','realizar inscricao','inscricoes online','inscricao')):
            if 'resultado' not in label:inscricao=link
    return edital,inscricao

def selection_context(title,body):
    title_norm=norm(title)
    body_norm=norm(body)
    if any(words_has(title_norm,x) for x in DISQUALIFY_TITLE):return False
    if any(x in title_norm[:280] for x in ACADEMIC_TERMS):return False
    if not any(t in body_norm[:2400] for t in ('concurso publico','concurso de provas','concurso para',
                                              'edital de abertura','inscricoes:','inscricoes abertas',
                                              'processo seletivo publico')):
        return False
    return True

def parse_text_page(html,url):
    soup=BeautifulSoup(html,'html.parser')
    edital,registration=open_links(soup,url)
    # Link labels often reveal official opening notice; examine at most 2 such documents.
    for tag in soup(['script','style','nav','footer','header','noscript']):tag.decompose()
    title_tag=soup.find('h1') or soup.find('h2') or soup.find('title')
    title=title_tag.get_text(' ',strip=True)[:220] if title_tag else ''
    title=title or urlparse(url).path.strip('/')
    text=re.sub(r'\s+',' ',soup.get_text(' ',strip=True))[:25000]
    return title,text,edital,registration

def review_page(url):
    raw,final,kind=fetch(url)
    if not raw:return rejected('pagina_sem_conteudo')
    if kind=='pdf':
        title=urlparse(final).path.rsplit('/',1)[-1]
        text=raw
        edital,registration=final,None
    else:
        title,text,edital,registration=parse_text_page(raw,final)
    # Entire article titles about outcomes or academic admissions are excluded outright.
    if not selection_context(title,text):return rejected('sem_contexto_de_concurso_ou_resultado')
    group=career(title,text)
    if not group:return rejected('cargo_nao_identificado')
    # On a real public call, the opening edital usually contains better facts than the landing page.
    # Do not treat a salary range across multiple positions as proof of the target position salary.
    doc_text=''
    if edital and edital!=final and trusted(edital):
        try:
            extracted,_,doc_kind=fetch(edital)
            if doc_kind=='pdf' and extracted:doc_text=extracted[:45000]
        except Exception:rejected('edital_pdf_inacessivel')
    combined=(text+' '+doc_text)[:65000]
    if doc_text and not group:group=career(title,combined)
    deadline=registration_deadline(combined)
    if not deadline:return rejected('prazo_de_inscricao_nao_identificado')
    loc,loc_type=location(title,combined)
    if loc_type=='indefinida':return rejected('lotacao_sem_cidade_permitida')
    if any(words_has(norm(title),city) for city in OUTSIDE) and loc_type not in ('municipal','capital'):
        return rejected('cidade_fora_da_regiao')
    salary,why=salary_for_job(title,combined)
    if salary is not None and salary<=MIN_SALARY:return rejected('salario_inferior_ao_piso')
    if 'vunesp.com.br' in urlparse(final).netloc: registration=registration or final
    if 'pciconcursos.com.br' in urlparse(final).netloc:
        registration=None # Portal agregador não é link de inscrição oficial
    # For strict highlights, landing page and edital must describe one named job and
    # salary; a page for an entire multi-job selection stays under review.
    multi_cargo=any(x in norm(combined[:1000]) for x in ('diversos cargos','faixa salarial','salarios entre','varios cargos'))
    confirmed=(loc_type in ('municipal','capital') and 'pciconcursos.com.br' not in urlparse(final).netloc and salary is not None
               and salary>MIN_SALARY and bool(registration) and not multi_cargo)
    issues=[]
    if loc_type not in ('municipal','capital'):issues.append('Cidade de exercício não comprovada')
    if salary is None:issues.append(why or 'Salário não comprovado por cargo')
    if not registration:issues.append('Não foi encontrado link específico de inscrição')
    if multi_cargo:issues.append('Edital de múltiplos cargos: verificar remuneração individual')
    item={
      'id':hashlib.sha256(final.encode()).hexdigest()[:16],
      'title':title,'organizer':urlparse(final).hostname or '',
      'area':group,'salary':salary,'deadline':deadline.isoformat(),
      'location':loc,'location_status':'capital_abc' if loc_type in ('municipal','capital') else 'uncertain',
      'status':'apto_para_conferencia' if confirmed else 'revisao',
      'reason':'; '.join(issues),
      'summary':'Conferir no edital original cargo, formação, lotação e vigência das inscrições.',
      'source_url':final,'edital_url':edital,'registration_url':registration,
      'published':TODAY.isoformat()
    }
    return item


# Pesquisa complementar em notícias e agregadores. Nunca promove notícia a
# inscrição confirmada: a aba "Para conferir" exige conferência do edital.
NEWS_QUERIES = [
  '"concurso público" "São Paulo" "médico" inscrições',
  '"concurso público" "São Paulo" "procurador" inscrições',
  '"concurso público" "São Paulo" "auditor" inscrições',
  '"concurso público" "São Paulo" "economista" inscrições',
  '"concurso público" "São Paulo" "analista" inscrições',
  '"concurso público" "Guarulhos" inscrições',
  '"concurso público" "Osasco" inscrições',
  '"concurso público" "Barueri" inscrições',
  '"concurso público" "Taboão da Serra" inscrições',
  '"concurso público" "Santo André" inscrições',
  '"concurso público" "São Bernardo do Campo" inscrições',
  '"concurso público" "São Caetano do Sul" inscrições',
  '"concurso público" "Diadema" inscrições',
  '"concurso público" "Mauá" inscrições',
  '"concurso público" "TRF3" inscrições',
  '"concurso público" "TJSP" inscrições',
  '"concurso público" "TCE SP" inscrições',
  'site:pciconcursos.com.br "São Paulo" "médico" concurso',
  'site:pciconcursos.com.br "São Paulo" "procurador" concurso',
  'site:pciconcursos.com.br "São Paulo" "auditor" concurso',
  'site:concursosfcc.com.br "São Paulo" inscrições concurso',
  'site:vunesp.com.br "São Paulo" inscrições concurso',
  'site:conhecimento.fgv.br/concursos "São Paulo" inscrições',
]
NEWS_BLOCK = (
 'resultado','resultados','gabarito','gabaritos','notas','nota de corte',
 'classificacao','homologacao','convocacao','nomeacao','provas aplicadas',
 'local de prova','data da prova','lista de aprovados','concurso encerrado',
 'inscricoes encerradas','mestrado','doutorado','residencia medica',
 'residencia multiprofissional','vestibular','bolsa de estudos',
 'curso gratuito','processo seletivo de alunos','pos-graduacao',
 'concurso de redação','concurso cultural'
)
# Estados que não podem ser confundidos com municípios da Grande São Paulo.
NEWS_OUTSIDE = ('acre','amazonas','rondonia','roraima','amapa','tocantins',
 'paraiba','pernambuco','ceara','alagoas','sergipe','bahia','piaui',
 'maranhao','mato grosso','goias','parana','santa catarina',
 'rio grande do sul','minas gerais','rio de janeiro','espirito santo',
 'distrito federal','rio branco','manaus','recife','fortaleza',
 'curitiba','belo horizonte','porto alegre','goiania','brasilia')
NEWS_CITIES = tuple(x for x in CITIES if x != 'sao paulo')
PUBLIC_JOBS = ('concurso publico','concurso para','concurso da','concurso do',
 'edital de concurso','concurso abre','concurso oferece','concurso com')
OPEN_WORDS = ('inscricoes','inscricao','edital','vagas','prazo','selecao')
NEWS_CAREERS = (
 'medico','medica','cirurgiao','clinico','procurador','advogado',
 'auditor','economista','analista','defensor','promotor','juiz',
 'magistratura','perito','fiscal','controlador','tributario',
 'nivel superior','ensino superior','especialista','gestao publica','professor universitario'
)

def news_lead(title, snippet, url, pubdate):
    title_n=norm(title)
    t=norm(title+' '+snippet)
    if any(x in title_n for x in NEWS_BLOCK):return None
    if any(words_has(t,x) for x in NEWS_OUTSIDE):return None
    if not ('concurso' in t or 'edital' in t):return None
    if not any(x in t for x in OPEN_WORDS) and 'concurso' not in title_n:return None
    if not any(words_has(t,x) for x in NEWS_CAREERS):return None
    # Só aceitar município explicitamente citado, não "Estado de SP".
    matches=[CITIES[c] for c in NEWS_CITIES if words_has(t,c)]
    capital=any(x in t for x in CAPITAL_MARKERS) or 'sao paulo (sp)' in t or 'cidade de sao paulo' in t
    statewide=('sao paulo' in t or re.search(r'\bsp\b',t)) and not any(words_has(t,x) for x in NEWS_OUTSIDE)
    if not matches and not capital and not statewide:
        return None
    area=career(title,snippet)
    if not area:return None
    # Um salário máximo de notícia nunca prova a remuneração do cargo.
    salary, why=salary_for_job(title, title+' '+snippet)
    if salary is not None and salary<MIN_SALARY:return None
    if pubdate:
        try:
            d=parsedate_to_datetime(pubdate)
            if d.tzinfo is None:d=d.replace(tzinfo=timezone.utc)
            if (datetime.now(timezone.utc)-d.astimezone(timezone.utc)).days>45:return None
        except (ValueError,TypeError,OverflowError):pass
    if not url.startswith('https://'):return None
    loc=matches[0] if len(set(matches))==1 else ('São Paulo (capital)' if capital and not matches else ('Estado de São Paulo — lotação não confirmada' if statewide and not matches else 'Município a confirmar'))
    return {
      'id':hashlib.sha256(('news:'+url).encode()).hexdigest()[:16],
      'title':title[:210],'organizer':urlparse(url).hostname or 'Notícia',
      'area':area,'salary':None,'deadline':None,
      'location':loc,'location_status':'uncertain','status':'revisao',
      'reason':'Notícia/portal de divulgação: conferir edital, inscrições, cargo, salário acima de R$ 15 mil e lotação. '
               + ('Valor citado na notícia não comprova salário do cargo.' if salary else 'Salário ainda não comprovado.'),
      'summary':snippet[:350],'source_url':url,
      'edital_url':None,'registration_url':None,'published':TODAY.isoformat()
    }

def discover_news():
    leads=[];errors=[];seen=set();rss_total=0; examples=[]
    # Google Notícias RSS é uma fonte adicional, não o único mecanismo.
    for query in NEWS_QUERIES:
        try:
            rss='https://news.google.com/rss/search?'+urlencode({
                'q':query+' when:30d','hl':'pt-BR','gl':'BR','ceid':'BR:pt-419'})
            r=SESSION.get(rss,timeout=14)
            r.raise_for_status()
            soup=BeautifulSoup(r.content,'xml')
            for entry in soup.find_all('item')[:35]:
                title=entry.find('title')
                link=entry.find('link')
                desc=entry.find('description')
                date_tag=entry.find('pubDate')
                if not title or not link:continue
                u=link.get_text(strip=True)
                rss_total+=1
                if len(examples)<6: examples.append(title.get_text(' ',strip=True)[:130])
                if u in seen:continue
                seen.add(u)
                snippet=BeautifulSoup(desc.get_text(' ',strip=True) if desc else '', 'html.parser').get_text(' ',strip=True)
                lead=news_lead(title.get_text(' ',strip=True),snippet,u,
                               date_tag.get_text(strip=True) if date_tag else None)
                if lead:leads.append(lead)
        except Exception as exc:
            errors.append('Notícias: '+type(exc).__name__)
    print('RSS notícias examinadas:',rss_total,'exemplos:',examples)
    return leads[:100],errors

def main():
    links,errors=discover()
    print('Amostra páginas:',links[:8])
    approved=[];review=[];discarded=0
    news,news_errors=discover_news()
    errors.extend(news_errors)
    def get_one(url):
        try:return review_page(url),None
        except Exception as ex:return None,type(ex).__name__
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        for result,err in pool.map(get_one,links):
            if err:errors.append(err)
            if not result:discarded+=1;continue
            (approved if result['status']=='apto_para_conferencia' else review).append(result)
    # Notícias ficam somente em revisão, nunca em destaque.
    existing={(norm(x['title']),norm(x['location'])) for x in approved+review}
    for lead in news:
        key=(norm(lead['title']),norm(lead['location']))
        if key not in existing:
            review.append(lead);existing.add(key)
    approved.sort(key=lambda x:(x['deadline'],x['title']))
    review.sort(key=lambda x:(x['deadline'] or '9999',x['title']))
    data={
        'updated_at':datetime.now(timezone.utc).isoformat(),
        'note':'Fontes oficiais e bancas. As vagas em destaque passaram por validação automatizada; confira edital, cargo, salário, lotação e disponibilidade antes de se inscrever. A coleta não é exaustiva.',
        'items':approved,
        'review':review,
        'stats':{'links_oficiais_analisados':len(links),'noticias_triadas':len(news),'destaques':len(approved),
                 'revisao':len(review),'descartados':discarded,'falhas':len(errors)},
        'source_errors':errors[:15],
        'diagnostico_descartes':dict(DIAG),
        'limitations':['Automação de triagem; a aprovação depende de leitura do edital.', 'Portais podem bloquear acessos e não expor PDFs de modo automatizado.'],
    }
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    OUTPUT.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Notícias candidatas para revisão:',len(news))
    print('Páginas oficiais:',len(links),'destaques:',len(approved),'revisão:',len(review),
          'descartadas:',discarded,'falhas:',len(errors))
    print('Motivos dos descartes:', json.dumps(dict(DIAG), ensure_ascii=False))
    if errors:print('Falhas parciais:', '; '.join(errors[:6]))

if __name__=='__main__':main()
