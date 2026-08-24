"""
Executa, na tela de um report já aberto, a sequência:
  1. Abre "Resultado da análise" (select#reportResult) e escolhe "Inválido"
  2. Escreve em "Comentários da Staff" (textarea#staffComments): "Bot - <inicial>"
  3. MODO TESTE  -> para aqui e espera você clicar manualmente em
                    "Notificar report inválido"
     MODO AUTO   -> clica sozinho em "Notificar report inválido"

IDs confirmados via inspeção real da página (F12): #reportResult e
#staffComments. Usar ID é bem mais confiável que buscar por texto, já que
não muda mesmo se o texto do rótulo for ajustado no futuro.
"""
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC


def marcar_como_invalido(driver, config, inicial_staff, modo_automatico, callback_aguardar_manual=None):
    """
    callback_aguardar_manual: função sem argumentos que o app GUI passa para
    pausar e só continuar quando o usuário confirmar (usado no modo teste).
    """
    texto_opcao = config["resultado_invalido_texto_opcao"]

    # 1) Dropdown "Resultado da análise"
    try:
        select_el = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "reportResult"))
        )
    except Exception:
        select_el = driver.find_element(
            By.XPATH,
            "//*[contains(text(),'Resultado da analise') or contains(text(),'Resultado da análise')]"
            "/following::select[1]",
        )
    Select(select_el).select_by_visible_text(texto_opcao)

    # 2) Campo "Comentários da Staff"
    comentario = config["comentario_staff_template"].format(inicial=inicial_staff)
    try:
        campo_comentario = driver.find_element(By.ID, "staffComments")
    except Exception:
        campo_comentario = driver.find_element(
            By.XPATH,
            "//*[contains(text(),'Coment') and contains(text(),'Staff')]"
            "/following::textarea[1]",
        )
    campo_comentario.clear()
    campo_comentario.send_keys(comentario)
    # Tira o foco do campo (Tab) antes de seguir - em apps Vue/React, o valor
    # digitado às vezes só é "registrado" de verdade no estado da aplicação
    # quando o campo perde o foco (evento blur/change), não a cada tecla.
    campo_comentario.send_keys(Keys.TAB)

    # 3) Notificar
    texto_botao = config["texto_botao_notificar"]
    botao_notificar = driver.find_element(
        By.XPATH, f"//button[contains(., '{texto_botao}')] | //a[contains(., '{texto_botao}')]"
    )

    if modo_automatico:
        botao_notificar.click()
        return "notificado_automatico"
    else:
        if callback_aguardar_manual:
            callback_aguardar_manual()
        return "aguardando_clique_manual"
