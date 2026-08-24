"""
Executa, na tela de um report já aberto, a sequência:
  1. Abre "Resultado da análise" (select#reportResult) e escolhe "Inválido"
  2. Escreve em "Comentários da Staff" (textarea name=staffComments): "Bot - <inicial>"
  3. MODO TESTE  -> para aqui e espera você clicar manualmente
     MODO AUTO   -> Clica em "Notificar" (Amarelo) e depois em "Salvar" (Azul)
"""
import time
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC


def marcar_como_invalido(driver, config, inicial_staff, modo_automatico, callback_aguardar_manual=None):
    texto_opcao = config["resultado_invalido_texto_opcao"]

    # 1) Dropdown "Resultado da análise"
    try:
        select_el = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "reportResult"))
        )
    except Exception:
        select_el = driver.find_element(
            By.XPATH,
            "//*[contains(text(),'Resultado da analise') or contains(text(),'Resultado da análise')]/following::select[1]"
        )
    Select(select_el).select_by_visible_text(texto_opcao)

    # 2) Campo "Comentários da Staff"
    comentario = config["comentario_staff_template"].format(inicial=inicial_staff)
    try:
        campo_comentario = driver.find_element(By.NAME, "staffComments")
    except Exception:
        campo_comentario = driver.find_element(
            By.XPATH,
            "//*[contains(text(),'Coment') and contains(text(),'Staff')]/following::textarea[1]"
        )
    
    campo_comentario.clear()
    campo_comentario.send_keys(comentario)
    campo_comentario.send_keys(Keys.TAB)
    time.sleep(0.5)

    # --- CLIQUES AUTOMÁTICOS ---
    if modo_automatico:
        
        # 3) Clica no botão NOTIFICAR (amarelo) PRIMEIRO!
        sucesso_notificar = False
        erro_encontrado = ""
        
        for tentativa in range(3):
            try:
                xpath_notificar = "//button[contains(@class, 'btn-warning')]"
                botao_notificar = WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.XPATH, xpath_notificar))
                )
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", botao_notificar)
                time.sleep(0.5)
                driver.execute_script("arguments[0].click();", botao_notificar)
                
                sucesso_notificar = True
                time.sleep(1) # Aguarda 1 seg para o sistema registrar o clique amarelo
                break
            except Exception as e:
                erro_encontrado = type(e).__name__
                time.sleep(2)
                
        if not sucesso_notificar:
            return f"falha_ao_notificar (Erro: {erro_encontrado})"

        # 4) Clica no botão SALVAR (azul) POR ÚLTIMO (já que ele atualiza a página)
        try:
            botao_salvar = WebDriverWait(driver, 3).until(
                EC.presence_of_element_located((By.XPATH, "//button[contains(normalize-space(), 'Salvar')]"))
            )
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", botao_salvar)
            time.sleep(0.5)
            driver.execute_script("arguments[0].click();", botao_salvar)
            time.sleep(1) # Dá tempo pro submit acontecer antes de fechar a aba
        except Exception as e:
            print(f"Aviso: Falha ao tentar clicar em Salvar: {e}")

        return "notificado_automatico"
            
    else:
        # Modo Teste
        if callback_aguardar_manual:
            callback_aguardar_manual()
        return "aguardando_clique_manual"