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

ROOT=Path(__file__).resolve().parent
OUTPUT=ROOT/'data'/'concursos.json'
BRT=timezone(timedelta(hours=-3))
TODAY=datetime.now(BRT).date()
MIN_SALARY=12000
USER_AGENT='RadarConcursosSP/4.0 (public-edital-monitor; GitHub Actions)'
DIAG=Counter()
DIAG_LOCK=Lock()
def rejected(reason):
    with DIAG_LOCK: DIAG[reason] += 1
    return None
SESSION=requests.Session()
SESSION.headers.update({'User-Agent':USER_AGENT,'Accept-Language':'pt-BR,pt;q=0.9'})
TRUSTED_DOMAINS=(
    'vunesp.com.br','concursosfcc.com.br','conhecimento.fgv.br',
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
                           'cargo de nivel superior','nivel superior em qualquer area')
}
# Fontes diretas: páginas oficiais de concursos ou mecanismos internos da banca.
DIRECT_SOURCES=[
 ('Vunesp - Direito','https://www.vunesp.com.br/?b=PROCURADOR'),
 ('Vunesp - Medicina','https://www.vunesp.com.br/?b=MEDICO'),
 ('Vunesp - Auditoria','https://www.vunesp.com.br/?b=AUDITOR'),
 ('Vunesp - São Paulo','https://www.vunesp.com.br/?b=SAO%20PAULO'),
 ('Vunesp - Guarulhos','https://www.vunesp.com.br/?b=GUARULHOS'),
 ('Vunesp - Osasco','https://www.vunesp.com.br/?b=OSASCO'),
 ('FCC - inscrições abertas','https://www.concursosfcc.com.br/'),
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
    if not trusted(url): raise ValueError('URL não é de fonte permitida')
    r=SESSION.get(url,timeout=16,allow_redirects=True)
    r.raise_for_status()
    if not trusted(r.url): raise ValueError('Redirecionamento externo não permitido')
    if len(r.content)>3_000_000:raise ValueError('Página acima do limite')
    if 'pdf' in r.headers.get('content-type','').lower():
        # PDF é fornecido como link, não tentamos tratá-lo como HTML.
        return None,r.url
    return r.text,r.url

def source_links(page,base):
    soup=BeautifulSoup(page,'html.parser')
    result=[]
    for a in soup.find_all('a',href=True):
        href=urljoin(base,a.get('href',''))
        if not trusted(href):continue
        path=urlparse(href).path
        label=a.get_text(' ',strip=True)
        if (VUNESP_DETAIL.match(path) or ('concurso' in norm(href) and len(label)>5)
            or ('edital' in norm(href) and len(label)>5)):
            result.append(href)
    return result

def discover():
    pool=[]; errors=[]
    for name,url in DIRECT_SOURCES:
        try:
            raw,final=fetch(url)
            if raw:
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

def review_page(url):
    raw,final=fetch(url)
    if not raw:return rejected("pagina_sem_html")
    soup=BeautifulSoup(raw,'html.parser')
    for tag in soup(['script','style','nav','footer','header','noscript']):tag.decompose()
    title_tag=soup.find('h1') or soup.find('h2') or soup.find('title')
    title=title_tag.get_text(' ',strip=True)[:220] if title_tag else ''
    title=title or urlparse(final).path.strip('/')
    text=soup.get_text(' ',strip=True)
    text=re.sub(r'\s+',' ',text)[:20000]
    if not selection_context(title,text):return rejected("sem_contexto_de_concurso_ou_resultado")
    group=career(title,text)
    if not group:return rejected("cargo_nao_identificado")
    # Não aceita resultado ou prazo expirado como inscrição.
    ntitle=norm(title)
    if any(words_has(ntitle,k) for k in DISQUALIFY_TITLE):return rejected("pagina_de_resultado_ou_curso")
    end=registration_deadline(text)
    if not end:return rejected("prazo_de_inscricao_nao_identificado")
    loc,loc_type=location(title,text)
    salary,why=salary_for_job(title,text)
    edital,registration=open_links(soup,final)
    if 'vunesp.com.br' in urlparse(final).netloc:registration=registration or final
    # Critério conservador: órgão municipal localizado + remuneração exata.
    # Citação geográfica e salários gerais/ambíguos ficam apenas em revisão.
    confirmed=(loc_type in ('municipal','capital') and salary is not None
               and salary>=MIN_SALARY and bool(registration))
    if salary is not None and salary<MIN_SALARY:return rejected("salario_inferior_ao_piso")
    status='apto_para_conferencia' if confirmed else 'revisao'
    reason=[]
    if not confirmed:
        if loc_type not in ('municipal','capital'):reason.append('Cidade de exercício não comprovada')
        if salary is None:reason.append(why or 'Salário a conferir')
        if not registration:reason.append('Link de inscrição não localizado')
    # Descarta candidaturas sem sequer localidade plausível, inclusive concursos de outro estado.
    nt=norm(title+' '+text[:900])
    if loc_type=='indefinida':return rejected("lotacao_sem_cidade_permitida")
    if any(words_has(norm(title),c) for c in OUTSIDE) and loc_type not in ('municipal','capital'):return rejected("cidade_fora_da_regiao")
    # Link oficial e título, não texto de manchete de terceiros.
    item={
        'id':hashlib.sha256(final.encode()).hexdigest()[:16],
        'title':title,'organizer':urlparse(final).hostname or '',
        'area':group,'salary':salary,'deadline':end.isoformat(),
        'location':loc,'location_status':'capital_abc' if loc_type in ('municipal','capital') else 'uncertain',
        'status':status, 'reason':'; '.join(reason),
        'summary':'Verifique o edital original para requisitos, inscrição e lotação.',
        'source_url':final,'edital_url':edital,'registration_url':registration,
        'published':TODAY.isoformat()
    }
    return item

def main():
    links,errors=discover()
    approved=[];review=[];discarded=0
    def get_one(url):
        try:return review_page(url),None
        except Exception as ex:return None,type(ex).__name__
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        for result,err in pool.map(get_one,links):
            if err:errors.append(err)
            if not result:discarded+=1;continue
            (approved if result['status']=='apto_para_conferencia' else review).append(result)
    approved.sort(key=lambda x:(x['deadline'],x['title']))
    review.sort(key=lambda x:(x['deadline'],x['title']))
    data={
        'updated_at':datetime.now(timezone.utc).isoformat(),
        'note':'Fontes oficiais e bancas. As vagas em destaque passaram por validação automatizada; confira edital, cargo, salário, lotação e disponibilidade antes de se inscrever. A coleta não é exaustiva.',
        'items':approved,
        'review':review,
        'stats':{'links_oficiais_analisados':len(links),'destaques':len(approved),
                 'revisao':len(review),'descartados':discarded,'falhas':len(errors)},
        'source_errors':errors[:15],
        'diagnostico_descartes':dict(DIAG),
    }
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    OUTPUT.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Páginas oficiais:',len(links),'destaques:',len(approved),'revisão:',len(review),
          'descartadas:',discarded,'falhas:',len(errors))
    print('Motivos dos descartes:', json.dumps(dict(DIAG), ensure_ascii=False))
    if errors:print('Falhas parciais:', '; '.join(errors[:6]))

if __name__=='__main__':main()
