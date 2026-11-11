# Radar de Concursos — São Paulo / ABC

Um painel HTML para acompanhar notícias sobre concursos que **podem** interessar a um profissional com graduação em Direito, Medicina e Economia, priorizando remuneração divulgada a partir de **R$ 12.000** e São Paulo/ABC.

## Como publicar gratuitamente para seu pai acessar de qualquer dispositivo

1. Crie uma conta em [GitHub](https://github.com/) ou entre na sua conta.
2. Crie um repositório **público**, por exemplo `radar-concursos-pai`. Envie **todos** os arquivos e pastas deste ZIP para a raiz do repositório, incluindo `.github/workflows/atualizar.yml` (a pasta começa com ponto).
3. Em **Settings → Pages → Build and deployment**, selecione **Deploy from a branch**, a branch `main` e a pasta `/ (root)`. Clique em **Save**.
4. Em **Actions**, escolha **Atualizar concursos** e clique em **Run workflow** para executar a primeira coleta. Ative Actions caso o GitHub peça permissão. Em **Settings → Actions → General → Workflow permissions**, permita leitura e escrita se o commit automático for bloqueado.
5. O endereço de acesso será parecido com `https://SEU-USUARIO.github.io/radar-concursos-pai/`. Esse endereço só existirá depois que você publicar o repositório.
6. Salve esse endereço nos favoritos do navegador de seu pai. As buscas estão programadas para 07h e 19h, horário de Brasília (execuções agendadas podem atrasar). O HTML recarrega os dados a cada 30 minutos quando estiver aberto.

> **Importante:** um arquivo HTML sozinho não consegue fazer buscas confiáveis e periódicas na internet. A atualização é executada no servidor gratuito de automações do GitHub, desde que a configuração acima seja concluída. O agendamento pode ser suspenso pelo GitHub em repositórios públicos inativos e depende da disponibilidade dos serviços.

## O que o robô faz

- Pesquisa anúncios recentes por 20 combinações de cargo, cidade e órgão utilizando RSS de notícias do Google (dependência externa sem garantia de continuidade).
- Remove anúncios que mencionam um salário único **inferior a R$ 12 mil**.
- Mantém anúncios sem salário ou com múltiplos salários **como pendentes de análise** para não esconder possibilidades interessantes.
- Tenta extrair a data-limite de inscrição explicitamente mencionada e identificar, quando possível, links a editais e inscrições em sites oficiais.
- Exibe links para **fontes** quando o edital oficial não é identificável; **não inventa** URLs de inscrição.
- Mantém filtros por área, localização provável, salário informado, prazo e favoritos.

## Limitações que devem ser conhecidas

**Este é um radar de triagem, NÃO uma base oficial de concursos abertos.** Os resultados podem conter concursos encerrados, cargos com remunerações anunciadas para outra especialidade, lotações fora da região, cadastros de reserva ou notícias duplicadas. A presença de “São Paulo” na notícia não comprova lotação na capital; até mesmo municípios do ABC citados exigem conferência no edital. Datas extraídas de manchetes podem estar desatualizadas. As fontes de notícias podem não cobrir todos os editais, e RSS ou links podem falhar. Nenhum processo de inscrição é realizado automaticamente.

**Segurança:** confirme a legitimidade da banca no edital oficial antes de fornecer documentos, pagar taxas ou fazer cadastro. O painel não pede dados pessoais do candidato.

## Como testar localmente

Abra `index.html` em um navegador; alguns navegadores bloqueiam `fetch` para arquivos `file://`, então é melhor executar:

```sh
python3 -m http.server 8000
```

Acesse `http://localhost:8000`. Para gerar dados, execute `python3 update.py` em um computador com internet (somente biblioteca padrão de Python). O arquivo `data/concursos.json` incluído no ZIP está vazio por padrão: **não representa falta de concursos**, apenas ausência da primeira busca automática.

## Personalização

Edite a lista `QUERIES` em `update.py` para ampliar/restringir a pesquisa. O limite salarial está em `if amount is not None and amount < 12000`. O monitoramento *não* verifica limites etários ou requisitos profissionais; essas verificações só podem ser feitas lendo o edital.


## Atualização de critérios — novembro/2026

- Inclui **Osasco, Taboão da Serra, Barueri e Guarulhos**, além de São Paulo capital e ABC.
- Exclui automaticamente notícias sobre inscrição em mestrado, doutorado, vestibular, residência médica e cursos acadêmicos.
- Exige indicadores de **concurso para cargo público** e de cargo de interesse, não apenas a palavra "edital".
- Exclui salários identificados abaixo de R$ 12.000; resultados sem salário explícito ficam **ocultos por padrão** no site, mas podem ser mostrados para revisão.
- "Cidade citada" **não comprova lotação**; confira sempre o edital.
- Google Notícias pode retornar notícias incompletas ou anúncios de concursos antigos; o radar é triagem inicial, **não certificação de inscrição aberta**.

### Como atualizar seu repositório
No GitHub, abra `update.py` e `index.html`, clique no ícone do lápis, substitua o conteúdo pelo dos arquivos desta versão e confirme cada alteração. Depois rode `Actions > Atualizar concursos > Run workflow` para substituir os resultados antigos em `data/concursos.json`.
