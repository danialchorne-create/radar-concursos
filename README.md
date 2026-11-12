# Radar de Concursos — São Paulo e Grande São Paulo

Site público para descobrir **concursos para cargos públicos** relevantes a uma pessoa formada em **Direito, Medicina e Economia pela USP**, com **OAB**, **residência médica**, atuação como **cirurgião e clínico geral** e **mestrado em Finanças**.

## Critérios

- Remuneração desejada: **acima de R$ 15.000 mensais**. Não considerar faixas salariais genéricas de editais com vários cargos como prova do salário específico.
- Regiões: **São Paulo capital, Guarulhos, Taboão da Serra, Barueri, Osasco, Santo André, São Bernardo do Campo, São Caetano do Sul, Diadema, Mauá, Ribeirão Pires e Rio Grande da Serra**.
- Áreas: Medicina, Direito, Economia/Finanças e cargos que aceitem graduação superior em qualquer área.
- Não sugerir vestibulares, mestrados, doutorados, residências, cursos, divulgações de notas ou gabaritos como concursos abertos.
- Aos 60 anos, conferir restrições legais específicas de cada cargo, mas não presumir inelegibilidade por idade.

## Como funciona

O arquivo `update.py` pesquisa páginas oficiais e bancas (incluindo **FCC, Vunesp e FGV**), agrega páginas do **PCI Concursos** e realiza buscas de notícias recentes. As notícias e páginas do PCI são **pistas para verificação**, nunca confirmação automática de abertura. Os dados são gravados em `data/concursos.json`.

O painel `index.html` possui duas abas:

- **Em destaque** — oportunidades que passaram pelas verificações automatizadas de salário, prazo e localização. **Ainda é obrigatório ler o edital** antes da inscrição.
- **Para conferir** — concursos encontrados em notícias, PCI ou páginas incompletas. Não há comprovação automática de inscrição aberta, salário ou lotação; podem conter resultados não pertinentes.

A atualização roda no **GitHub Actions às 7h e 19h (horário de Brasília)**, quando o GitHub executar a tarefa, e também é disparada automaticamente em alterações do código. Ações agendadas podem atrasar. Para executar manualmente: **Actions → Atualizar concursos → Run workflow**.

## Limitações reais

A internet não oferece uma API aberta e uniforme de todos os concursos. Fontes podem bloquear acessos automáticos; algumas usam JavaScript ou PDF digitalizado. O sistema não tem garantia de completude e não substitui a leitura do edital. Uma notícia sobre concurso do estado de São Paulo **não comprova lotação na capital/ABC**. O radar separa pistas de oportunidades classificadas e exibe diagnóstico em logs, sem tratar erro de acesso como ausência de vagas.

**Link do painel:** https://danialchorne-create.github.io/radar-concursos/
