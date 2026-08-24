# GC - Bot de Triagem de Toxicidade

Automatiza a "limpeza" de reports de toxicidade que não têm prova válida: lê o campo **Provas**, decide se é claramente inválido (sem link, ou só link de partida/perfil/busca) e, se for, marca **Inválido**, clica em **Notificar** e depois em **Salvar**, escrevendo **"Bot - <inicial>"** no comentário da staff.

Se o report tiver um link de vídeo/print/áudio reconhecido, ou um link que o bot não conhece, ele **nunca decide sozinho** — pula o report e o deixa na fila para revisão manual humana.

## 1. Como rodar (equipe / uso do dia a dia)

1. Pegue a pasta `dist/` ou a pasta zipada que foi enviada para você — ela deve conter o `gc_toxicidade_bot.exe` e o `config.json`.
2. Dê dois cliques no `gc_toxicidade_bot.exe`. Não precisa instalar Python, JDK nem nada — só precisa ter o navegador escolhido (Edge/Chrome/Firefox) já instalado no Windows.
3. Preencha o painel:
   - **Nome**: seu nome completo (vai pro log/auditoria).
   - **Inicial**: a letra que entra no comentário (ex: Celso → C, vira "Bot - C").
   - **Data a limpar**: dd/mm/aaaa (mesma data que aparece na coluna "Criado").
   - **Navegador**: qual navegador abrir.
   - **Modo**: comece sempre em **teste** — o bot preenche tudo e **para**, esperando você confirmar manualmente. Depois de validar que está tudo certo, mude para **automático**.
   - **Qtde (vazio=todos)**: limita quantos reports o bot vai processar de uma vez.
4. Clique em **▶ Iniciar Triagem**.
5. **Primeira vez**: o navegador vai abrir deslogado do painel interno — faça login manualmente uma vez. Da próxima vez que rodar o bot, já vai abrir logado (o login fica salvo na pasta `browser_profile`, que fica do lado do `.exe`).
6. Se a data digitada não tiver nenhum report pendente, o bot faz a rolagem até o fim, avisa no log e não faz nada.

Ao finalizar, o painel exibe um resumo formatado para copiar e colar para a equipe, e também **salva um arquivo `.txt` automaticamente** na pasta `resumos/` com o histórico. Além disso, o CSV completo fica salvo em `logs/processed_reports.csv`.

## 2. 💣 Invalidação em Massa (Nova Função)

Se você possui uma lista de IDs que já sabe que são inválidos:
1. Clique no botão laranja **💣 Invalidação em Massa** no canto superior direito.
2. Cole os IDs dos reports na caixa de texto (um por linha).
3. Selecione o **Motivo da Invalidação** no menu (Inválido Padrão, Duplicado, Sem Provas). O bot assinará o comentário de acordo (ex: `Bot - C - Duplicado`).
4. Confirme e deixe o bot invalidar e notificar todos automaticamente.

## 3. Ajustando as regras de link válido/inválido

Abra `config.json` (do lado do `.exe`) com qualquer editor de texto:

- `whitelist_dominios`: domínios que contam como prova real (youtube, streamable, imgur, medal.tv, prnt.sc, twitch, dropbox, etc.). Pode adicionar outros.
- `blacklist_padroes`: trechos de URL que NÃO contam como prova (link de partida/perfil da própria GamersClub, google.com, etc.).
- Qualquer link que não esteja em nenhuma das duas listas é tratado como **ambíguo** e o bot pula o report — não decide sozinho.

**Atenção**: Se surgir um padrão novo de link que a comunidade passou a usar, basta adicioná-lo em uma dessas duas listas no `.json` e o bot aprenderá na mesma hora.

## 4. Gerando o .exe (só precisa ser feito uma vez, por uma pessoa)

Pré-requisito nessa máquina específica: Python 3.10+ instalado (https://python.org — marque "Add to PATH" na instalação).

1. Abra o Prompt de Comando nesta pasta do projeto.
2. Rode: `build.bat`
3. Aguarde — isso baixa as bibliotecas (Selenium, CustomTkinter, PyInstaller) e gera o executável em `dist\gc_toxicidade_bot.exe`.
4. Crie uma pasta nova, coloque esse `.exe` dentro junto com o `config.json`. Zipe e mande para a equipe. Ninguém além de quem gerou o build precisa ter Python instalado.

## 5. Sobre o "driver" do navegador

O Selenium (versão usada aqui) baixa sozinho, na primeira execução, um arquivo pequeno (o "driver") que combina com a versão do navegador instalado — isso acontece automaticamente e não exige instalação manual, só uma conexão com a internet na primeira vez.

## 6. Tratamento de Falsos Positivos (Antivírus)

Como este software foi compilado em Python e não possui assinatura digital corporativa embutida, o **Windows Defender** ou outros antivírus podem sinalizá-lo como "Suspeito". Isso ocorre porque o bot precisa acessar as pastas temporárias do navegador para manter o login da GC salvo.
- **Solução:** Se o Windows bloquear a execução, basta ir em *Segurança do Windows > Proteção contra vírus e ameaças > Gerenciar configurações > Exclusões* e adicionar a pasta do bot. 

## 7. Estrutura do projeto

```text
gc_toxicidade_bot/
  app.py                 -> interface gráfica (CustomTkinter) + orquestração
  config.json            -> URLs, regras, motivos e listas de domínios
  bot/
    browser.py           -> abre o navegador com perfil persistente
    scraper.py           -> lê a listagem e faz scroll infinito
    evidence.py          -> regras Regex de Provas
    actions.py           -> marca Inválido, notifica (btn-warning) e salva
    storage.py           -> logs e histórico
  logs/                  -> csv de histórico (criado auto)
  resumos/               -> relatórios formatados em .txt (criado auto)
  browser_profile/       -> sessão logada (criado auto)
  build.bat              -> gera o .exe
  requirements.txt