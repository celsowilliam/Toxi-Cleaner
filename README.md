# GC - Bot de Triagem de Toxicidade

Automatiza a "limpeza" de reports de toxicidade que não têm prova válida:
lê o campo **Provas**, decide se é claramente inválido (sem link, ou só
link de partida/perfil/busca) e, se for, marca **Inválido**, escreve
**"Bot - <inicial>"** no comentário da staff e notifica.

Se o report tiver um link de vídeo/print/áudio reconhecido, ou um link
que o bot não conhece, ele **nunca decide sozinho** — pula o report e
registra "revisão manual necessária" no log.

## 1. Como rodar (equipe / uso do dia a dia)

1. Pegue a pasta `dist/` (gerada pelo passo de build abaixo) — tem
   `gc_toxicidade_bot.exe` e `config.json`.
2. Dá dois cliques no `gc_toxicidade_bot.exe`. Não precisa instalar
   Python, JDK nem nada — só precisa ter o navegador escolhido
   (Edge/Chrome/Firefox) já instalado no Windows, o que já vem de fábrica.
3. Preencha o painel:
   - **Nome**: seu nome completo (vai pro log/auditoria).
   - **Inicial**: a letra que entra no comentário (ex: Celso → C, vira "Bot - C").
   - **Data para limpar**: dd/mm/aaaa (mesma data que aparece na coluna "Criado").
   - **Navegador**: qual navegador abrir.
   - **Modo**: comece sempre em **teste** — o bot preenche tudo e
     **para**, esperando você clicar em "Notificar report inválido" você
     mesmo no navegador, e só continua depois que você confirmar no painel.
     Depois de validar que está tudo certo, mude para **automático**.
   - **Tamanho do lote**: de quantos em quantos reports o bot pausa
     para você conferir (padrão 3, como pedido).
4. Clique em **Iniciar**.
5. **Primeira vez**: o navegador vai abrir deslogado do painel interno —
   faça login manualmente uma vez. Da próxima vez que rodar o bot, já
   vai abrir logado (o login fica salvo na pasta `browser_profile`, que
   fica do lado do `.exe`).
6. Se a data digitada não tiver nenhum report pendente, o bot avisa no
   log e não faz nada (não trava, não tenta "adivinhar" outra data).

Todo report tocado fica registrado em `logs/processed_reports.csv`
(abre no Excel): número do report, data, quem processou, resultado,
motivo e quais links foram encontrados. O contador que aparece no
painel conta os reports desta sessão; o CSV é o histórico completo.

## 2. Ajustando as regras de link válido/inválido

Abra `config.json` (do lado do `.exe`) com qualquer editor de texto:

- `whitelist_dominios`: domínios que contam como prova real (youtube,
  streamable, imgur, medal.tv, prnt.sc, etc.). Pode adicionar outros.
- `blacklist_padroes`: trechos de URL que NÃO contam como prova (link
  de partida/perfil da própria GamersClub, google.com, etc.).
- Qualquer link que não esteja em nenhuma das duas listas é tratado
  como **ambíguo** e o bot pula o report — não decide sozinho.

**Atenção**: em um dos prints que vocês mandaram, o campo Provas tinha
um link `gamersclub.com.br/report/XXXXX` (diferente de `lobby/match`).
Esse padrão **não está em nenhuma lista por padrão** — o bot vai tratá-lo
como ambíguo até vocês decidirem se ele conta como prova válida ou não
e adicionarem na lista certa.

## 3. Gerando o .exe (só precisa ser feito uma vez, por uma pessoa)

Pré-requisito nessa máquina específica: Python 3.10+ instalado
(https://python.org — marque "Add to PATH" na instalação).

1. Abra o Prompt de Comando nesta pasta do projeto.
2. Rode: `build.bat`
3. Aguarde — isso baixa as bibliotecas (Selenium, PyInstaller) e gera
   o executável em `dist\gc_toxicidade_bot.exe`.
4. Zipe a pasta `dist\` e mande para a equipe. Ninguém além de quem
   gerou o build precisa ter Python instalado.

## 4. Sobre o "driver" do navegador

O Selenium (versão usada aqui) baixa sozinho, na primeira execução, um
arquivo pequeno (o "driver") que combina com a versão do navegador
instalado — isso acontece automaticamente e não exige instalação manual,
só uma conexão com a internet na primeira vez.

## 5. Limitações conhecidas / o que pode precisar de ajuste fino

Este projeto foi escrito a partir de **prints de tela** do painel
interno, não do HTML real da página. Os seletores usados (em
`bot/scraper.py` e `bot/actions.py`) procuram por **texto visível**
("Provas", "Resultado da analise", "Comentários da Staff", "Notificar
report inválido") porque isso costuma ser mais estável que depender de
classes/IDs internos — mas é possível que, na primeira rodada real,
algum campo não seja encontrado exatamente como esperado (por exemplo,
se houver paginação na listagem de pendentes, isso ainda não está
tratado). Se isso acontecer, o bot avisa qual passo falhou no log; me
mande a mensagem de erro (ou um "Inspecionar elemento" da parte que
falhou) que eu ajusto o seletor certinho.

## 5.1. Erro "No module named 'selenium.webdriver.edge.webdriver'"

Se aparecer esse erro ao rodar o `.exe`, é o PyInstaller não incluindo um
módulo do Selenium que só é carregado na hora de usar o Edge/Chrome/Firefox
(ele não consegue detectar isso sozinho no modo `--onefile`). Já corrigimos
isso no `build.bat` (linha `--collect-all selenium`). Para gerar o `.exe`
de novo com a correção:

1. Apague as pastas `build\` e `dist\` (o PyInstaller guarda cache antigo
   nelas e pode reaproveitar um `.exe` quebrado se não apagar).
2. Rode `build.bat` de novo.
3. Distribua o novo `dist\gc_toxicidade_bot.exe` para a equipe.

## 6. Estrutura do projeto

```
gc_toxicidade_bot/
  app.py              -> painel gráfico + orquestração
  config.json          -> URLs, listas de domínios válidos/inválidos, textos
  bot/
    browser.py          -> abre o navegador com perfil persistente (login salvo)
    scraper.py            -> lê a listagem de pendentes e a tela do report
    evidence.py            -> decide se Provas é válido/inválido/ambíguo
    actions.py               -> marca Inválido, escreve comentário, notifica
    storage.py                -> log em CSV + contador
  logs/
    processed_reports.csv      -> histórico (criado automaticamente)
  browser_profile/               -> perfil do navegador / sessão logada (criado automaticamente)
  build.bat                       -> gera o .exe
  requirements.txt
```
