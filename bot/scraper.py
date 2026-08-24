"""
Navega pela listagem de "Reports Pendentes" e pela tela de um report
individual (ANALISANDO REPORT ID: XXXX).

IMPORTANTE - PONTO DE CALIBRAÇÃO:
Este arquivo foi escrito olhando só para PRINTS DE TELA do painel (não o
HTML real). Os seletores abaixo usam texto visível (ex: "Provas",
"Resultado da analise") porque isso é o que mais resiste a pequenas
mudanças de layout - mas é bem possível que, na primeira execução real,
algum seletor precise de ajuste fino.
"""
import re
import time
from datetime import datetime
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException


def ir_para_pendentes(driver, config, timeout=30):
    driver.get(config["url_pendentes"])
    WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located(
            (By.XPATH, "//table | //*[contains(text(),'REPORTS PENDENTES')]")
        )
    )


def esta_logado(driver, config, timeout=6):
    """Verifica rapidamente se a tela de pendentes carregou sem pedir login."""
    driver.get(config["url_pendentes"])
    try:
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located(
                (By.XPATH, "//table | //*[contains(text(),'REPORTS PENDENTES')]")
            )
        )
        return True
    except TimeoutException:
        return False


def _texto_header(cell):
    return (cell.text or "").strip().upper()


def _obter_linhas_dados(tabela):
    """Pega as linhas de dado da tabela evitando o cabeçalho."""
    linhas = tabela.find_elements(By.XPATH, ".//tbody//tr")
    if linhas:
        return linhas
    todas = tabela.find_elements(By.XPATH, ".//tr")
    return [tr for tr in todas if not tr.find_elements(By.XPATH, "./th")]


def _esperar_linhas_carregarem(driver, timeout=15):
    """Espera pelo menos 1 linha de dado aparecer na tabela para iniciar a leitura."""
    try:
        WebDriverWait(driver, timeout).until(
            lambda d: any(
                _obter_linhas_dados(t) for t in d.find_elements(By.XPATH, "//table")
            )
        )
    except TimeoutException:
        pass 


def listar_reports_do_dia(driver, data_str, max_scrolls=150):
    """
    Usa Scroll Infinito para carregar os reports. Para automaticamente assim 
    que passar do bloco de datas alvo, otimizando o tempo.
    """
    encontrados_ordem = []
    encontrados_set = set()
    diagnostico = {
        "tabelas_na_pagina": 0,
        "linhas_na_tabela_escolhida": 0,
        "amostra_datas": [],
        "scrolls_realizados": 0,
        "paginacao_encontrada": False, 
        "paginas_percorridas": 1
    }

    try:
        data_alvo = datetime.strptime(data_str, "%d/%m/%Y")
    except ValueError:
        data_alvo = None

    _esperar_linhas_carregarem(driver, timeout=15)

    tabelas = driver.find_elements(By.XPATH, "//table")
    if not tabelas:
        raise RuntimeError("Não encontrei nenhuma <table> na página de pendentes.")

    diagnostico["tabelas_na_pagina"] = len(tabelas)

    # Escolhe a tabela com mais linhas (tabela principal)
    tabela = max(tabelas, key=lambda t: len(_obter_linhas_dados(t)))
    headers = tabela.find_elements(By.XPATH, ".//thead//th")
    if not headers:
        headers = tabela.find_elements(By.XPATH, ".//tr[1]/th | .//tr[1]/td")

    idx_criado = None
    idx_numero = None
    for i, h in enumerate(headers):
        texto = _texto_header(h)
        if "CRIADO" in texto:
            idx_criado = i
        if texto == "#":
            idx_numero = i

    if idx_criado is None or idx_numero is None:
        raise RuntimeError("Não encontrei as colunas '#' e/ou 'CRIADO' na tabela...")

    linhas_processadas = 0
    tentativas_sem_novas_linhas = 0
    viu_data_alvo = False
    terminou_bloco = False

    for scroll in range(max_scrolls):
        # 1. Re-buscar tabela para evitar erro de elementos obsoletos (Stale Element)
        tabelas = driver.find_elements(By.XPATH, "//table")
        tabela = max(tabelas, key=lambda t: len(_obter_linhas_dados(t)))
        linhas = _obter_linhas_dados(tabela)

        if scroll == 0:
            diagnostico["linhas_na_tabela_escolhida"] = len(linhas)

        # 2. Verifica se a tabela parou de crescer (fim da página real)
        if len(linhas) == linhas_processadas:
            tentativas_sem_novas_linhas += 1
            if tentativas_sem_novas_linhas >= 3:
                break
        else:
            tentativas_sem_novas_linhas = 0

        # 3. Processa apenas as linhas NOVAS carregadas
        for i in range(linhas_processadas, len(linhas)):
            try:
                celulas = linhas[i].find_elements(By.XPATH, "./td")
                if len(celulas) <= max(idx_criado, idx_numero):
                    continue

                texto_criado = celulas[idx_criado].text.strip()
                data_da_linha_str = texto_criado.split(" ")[0]

                if scroll == 0 and len(diagnostico["amostra_datas"]) < 5:
                    diagnostico["amostra_datas"].append(texto_criado)

                # Lógica de agrupamento de data
                if data_da_linha_str == data_str:
                    viu_data_alvo = True
                    numero = celulas[idx_numero].text.strip()
                    if numero not in encontrados_set:
                        encontrados_set.add(numero)
                        encontrados_ordem.append(numero)
                elif viu_data_alvo:
                    # Estávamos lendo a data certa, e de repente a data mudou.
                    # Isso significa que todos os reports desse dia já foram lidos!
                    terminou_bloco = True
                    break
                else:
                    # Se as datas são mais antigas que a alvo e nem achamos ela, para também.
                    if data_alvo:
                        try:
                            data_linha = datetime.strptime(data_da_linha_str, "%d/%m/%Y")
                            if data_linha < data_alvo:
                                terminou_bloco = True
                                break
                        except ValueError:
                            pass

            except Exception:
                continue # Ignora pequenas falhas de leitura na célula e continua

        linhas_processadas = len(linhas)
        diagnostico["scrolls_realizados"] = scroll + 1
        diagnostico["paginas_percorridas"] = scroll + 1  # Mantido pro log do app.py não quebrar

        if terminou_bloco:
            break

        # 4. Executa o Scroll
        try:
            driver.execute_script("arguments[0].scrollIntoView(true);", linhas[-1])
            time.sleep(1.5) # Aguarda 1.5s para o site carregar novas linhas
        except Exception:
            time.sleep(1)

    return encontrados_ordem, diagnostico


def abrir_report_por_id(driver, config, numero, timeout=30):
    """Navega DIRETO para a tela do report pela URL."""
    url = config["url_analisar_template"].format(id=numero)
    driver.get(url)
    WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located(
            (By.XPATH, "//*[contains(text(),'ANALISANDO REPORT') or contains(text(),'Provas')]")
        )
    )


def _extrair_bloco_apos_rotulo(texto_completo, rotulo, proximos_rotulos):
    idx_inicio = texto_completo.find(rotulo)
    if idx_inicio == -1:
        return ""
    idx_inicio += len(rotulo)
    resto = texto_completo[idx_inicio:]

    idx_fim = len(resto)
    for prox in proximos_rotulos:
        pos = resto.find(prox)
        if pos != -1 and pos < idx_fim:
            idx_fim = pos

    return resto[:idx_fim].strip()


def _ler_texto_estavel(elemento, tentativas=8, intervalo=0.3):
    anterior = None
    for _ in range(tentativas):
        atual = elemento.text.strip()
        if atual == anterior and atual != "":
            return atual
        anterior = atual
        time.sleep(intervalo)
    return anterior or ""


def ler_report_atual(driver, report_id=None):
    """Lê os dados relevantes da tela do report atual."""
    if report_id is None:
        titulo = driver.find_element(By.XPATH, "//*[contains(text(),'ANALISANDO REPORT ID')]").text
        m = re.search(r"(\d+)", titulo)
        report_id = m.group(1) if m else None

    texto_provas = ""
    debug_contexto = ""

    try:
        label = WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.XPATH, "//label[normalize-space(text())='Provas']"))
        )
        valor_el = label.find_element(By.XPATH, "following-sibling::p[1]")
        texto_provas = _ler_texto_estavel(valor_el)
        debug_contexto = f"(via label>p) {texto_provas!r}"
    except Exception as e:
        debug_contexto = f"(método principal falhou: {e})"

    if not texto_provas:
        corpo = driver.find_element(By.TAG_NAME, "body").text
        idx = corpo.find("Provas")
        if idx != -1:
            debug_contexto += f" | contexto bruto: {corpo[idx:idx + 300]!r}"
        texto_provas = _extrair_bloco_apos_rotulo(
            corpo,
            "Provas",
            ["Descrição do Report", "Descricao do Report", "Jogadores reportados",
             "Resultado da analise", "Resultado da análise"],
        )

    return {"report_id": report_id, "texto_provas": texto_provas, "debug_contexto": debug_contexto}