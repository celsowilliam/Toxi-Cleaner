"""
GC - ToxiCleaner (Bot de Triagem de Toxicidade)
Painel Completo com Firebase, Notificações e Comentários.
"""
import os
import sys
import json
import queue
import threading
import subprocess
from datetime import datetime

# 🖼️ IMPORTA O PILLOW PARA PROCESSAR A LOGO
try:
    from PIL import Image
except ImportError:
    Image = None

try:
    import requests
except ImportError:
    requests = None

try:
    from plyer import notification
    import winsound
except ImportError:
    notification = None

# 🛡️ IMPORTA AS SENHAS DO ARQUIVO ESCONDIDO (credenciais.py)
try:
    from credenciais import FIREBASE_URL, FIREBASE_SECRET
except ImportError:
    FIREBASE_URL = ""
    FIREBASE_SECRET = ""

import customtkinter as ctk
from tkinter import messagebox

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bot import browser, scraper, evidence, actions, storage

VERSAO_ATUAL = "1.1"

def base_dir():
    """Captura o caminho correto dos arquivos (leitura do .exe)"""
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))

def pasta_do_exe():
    """Captura a pasta real onde o usuário colocou o .exe (para salvar coisas de forma permanente)"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def carregar_preferencias_usuario():
    """Lê todas as preferências salvas do usuário na pasta raiz"""
    caminho = os.path.join(pasta_do_exe(), "preferencias_user.json")
    if os.path.exists(caminho):
        try:
            with open(caminho, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception: pass
    return {}

# Fallback global de segurança para evitar NameError
try:
    prefs = carregar_preferencias_usuario()
except Exception:
    prefs = {}

def salvar_preferencias_usuario(nome, inicial, modo, exibir_terminal=False, exibir_pausar=True, exibir_barra=True, tema_claro=False, historico_nuvem="Perguntar sempre"):
    """Salva todas as preferências de forma definitiva ao lado do .exe"""
    caminho = os.path.join(pasta_do_exe(), "preferencias_user.json")
    dados = {
        "nome": nome,
        "inicial": inicial,
        "modo": modo,
        "exibir_terminal": exibir_terminal,
        "exibir_pausar": exibir_pausar,
        "exibir_barra": exibir_barra,
        "tema_claro": tema_claro,
        "historico_nuvem": historico_nuvem
    }
    try:
        with open(caminho, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
    except Exception: pass

def disparar_notificacao(titulo, mensagem):
    if notification:
        try:
            winsound.MessageBeep(winsound.MB_ICONASTERISK)
            notification.notify(title=titulo, message=mensagem, app_name="ToxiCleaner", timeout=5)
        except Exception: pass

def carregar_config(fila_log=None):
    caminho_local = os.path.join(base_dir(), "config.json")
    if fila_log: fila_log.put(("log", "📁 Regras carregadas do arquivo LOCAL (Modo Dev)."))
    with open(caminho_local, "r", encoding="utf-8") as f: 
        return json.load(f)

def salvar_historico_firebase(dados):
    if not requests or not FIREBASE_URL: return
    url = f"{FIREBASE_URL.rstrip('/')}/historico.json?auth={FIREBASE_SECRET}"
    try: requests.post(url, json=dados, timeout=5)
    except Exception: pass

def ler_historico_firebase():
    if not requests or not FIREBASE_URL: return {}
    url = f"{FIREBASE_URL.rstrip('/')}/historico.json?auth={FIREBASE_SECRET}"
    try:
        r = requests.get(url, timeout=5)
        return r.json() if r.status_code == 200 and r.json() else {}
    except Exception: return {}

# --- WORKER DO BOT ---
class BotWorker(threading.Thread):
    def __init__(self, config, staff_nome, staff_inicial, data_str, navegador,
                 modo_automatico, quantidade_maxima, fila_eventos, headless=False, 
                 zona_teste=False, lista_massa=None, motivo_massa="Inválido (Padrão)"):
        super().__init__(daemon=True)
        self.config = config
        self.staff_nome = staff_nome
        self.staff_inicial = staff_inicial
        self.data_str = data_str
        self.navegador = navegador
        self.modo_automatico = modo_automatico
        self.quantidade_maxima = quantidade_maxima
        self.fila = fila_eventos
        self.headless = headless
        self.zona_teste = zona_teste
        self.lista_ids_forcados = lista_massa
        self.motivo_massa = motivo_massa
        
        self._parar = threading.Event()
        self._pausar = threading.Event()
        self._pausar.set()

    def parar(self):
        self._parar.set()
        self._pausar.set()

    def pausar(self):
        self._pausar.clear()

    def retomar(self):
        self._pausar.set()

    def log(self, msg):
        self.fila.put(("log", msg))

    def pedir_login_manual(self):
        evento = threading.Event()
        resposta = {}
        self.fila.put(("pedir_login", evento, resposta))
        evento.wait()
        return resposta.get("ok", False)

    def pedir_ok_manual(self, report_id):
        evento = threading.Event()
        resposta = {}
        self.fila.put(("pedir_ok_manual", report_id, evento, resposta))
        evento.wait()
        return resposta.get("ok", False)

    def run(self):
        driver = None
        total_processados = 0
        reports = []
        
        from bot import actions
        actions.MEMORIA_REPORTS_VISTOS.clear()
        
        try:
            msg_head = "(Modo Fantasma 👻)" if self.headless else ""
            if self.zona_teste:
                self.log("🧪 ZONA DE TESTE ATIVA: As ações na GC e notificações serão simuladas.")
            
            self.log(f"Iniciando abertura do {self.navegador} {msg_head}...")
            driver = browser.abrir_navegador(self.navegador, self.config, headless=self.headless)

            self.log("Verificando status de login na Gamers Club...")
            if not scraper.esta_logado(driver, self.config, timeout=6):
                if self.headless:
                    self.log("❌ ERRO: Bot deslogado no Modo Fantasma! Faça o 1º login no modo normal.")
                    self.fila.put(("fim", 0, 0))
                    return
                self.log("⚠ Sessão não encontrada. Faça login...")
                self.fila.put(("notificar", "Ação Necessária", "O bot precisa do seu login na GC!"))
                if not self.pedir_login_manual():
                    self.fila.put(("fim", 0, 0))
                    return

            if self.lista_ids_forcados:
                self.log("Modo Invalidação em Massa ativado.")
                reports = self.lista_ids_forcados
            else:
                self.log("Acessando reports pendentes...")
                scraper.ir_para_pendentes(driver, self.config)
                self.log(f"Buscando reports do dia {self.data_str}...")
                reports, _ = scraper.listar_reports_do_dia(driver, self.data_str)
                if not reports:
                    self.log(f"⚠ Nenhum report pendente para a data {self.data_str}.")
                    self.fila.put(("fim", 0, 0))
                    return
                if self.quantidade_maxima and len(reports) > self.quantidade_maxima:
                    reports = reports[: self.quantidade_maxima]

            self.fila.put(("total_encontrado", len(reports)))

            for index, numero in enumerate(reports):
                if self._parar.is_set():
                    break
                if not self._pausar.is_set():
                    self.log("⏸️ Bot pausado...")
                    self._pausar.wait()
                    if self._parar.is_set():
                        break
                    self.log("▶️ Bot retomado!")

                self.log(f"--- Abrindo report #{numero} ---")
                try:
                    scraper.abrir_report_por_id(driver, self.config, numero)
                    if self.lista_ids_forcados:
                        dados = {"texto_provas": f"Invalidação forçada - {self.motivo_massa}"}
                        resultado = {"status": "invalido", "motivo": "Invalidação em massa"}
                    else:
                        dados = scraper.ler_report_atual(driver, report_id=numero)
                        resultado = evidence.classificar_provas(dados["texto_provas"], self.config["whitelist_dominios"], self.config["blacklist_padroes"])
                except Exception as e:
                    self.log(f"❌ Erro ao ler report #{numero}: {e}")
                    continue

                texto_provas_bruto = dados.get('texto_provas', "Nenhuma prova informada")
                resumo_desc = dados.get('resumo_desc', "") 

                import re
                from bot import actions
                from selenium.webdriver.common.by import By
                
                try:
                    corpo_pagina_original = driver.find_element(By.TAG_NAME, "body").text.lower()
                except:
                    corpo_pagina_original = ""
                
                padrao_silencioso = re.compile(r'\b(hack\w*|wall\w*|wh|xit\w*|chit\w*|cheat\w*|aimbot|spinbot|macro|script|smurf\w*)\b')
                eh_report_silencioso = bool(padrao_silencioso.search(corpo_pagina_original))
                
                eh_duplicado = False
                try:
                    jog_match = re.search(r'jogador:\s*(\d+)', corpo_pagina_original)
                    jogador_id = jog_match.group(1) if jog_match else "sem_jog"

                    provas_seguras = texto_provas_bruto.strip().lower()
                    
                    desc_segura = ""
                    if "descrição do report" in corpo_pagina_original:
                        partes = corpo_pagina_original.split("descrição do report")
                        if len(partes) > 1:
                            desc_segura = partes[-1].split("jogadores reportados")[0].strip()
                    
                    assinatura_atual = f"{provas_seguras}|{desc_segura}|{jogador_id}"
                    
                    if (provas_seguras and provas_seguras != "nenhuma prova informada") or desc_segura:
                        if assinatura_atual in actions.MEMORIA_REPORTS_VISTOS:
                            eh_duplicado = True
                        else:
                            actions.MEMORIA_REPORTS_VISTOS.add(assinatura_atual)
                except Exception as e:
                    self.log(f"⚠️ Erro ao checar duplicidade: {e}")

                if eh_duplicado or eh_report_silencioso:
                    resultado["status"] = "invalido"

                if self.zona_teste:
                    if eh_duplicado:
                        status_fmt = "Inválido - Duplicado ❌ (Simulado)"
                    elif eh_report_silencioso:
                        status_fmt = "Inválido - Hack/Smurf ❌ (Simulado)"
                    elif resultado["status"] == "invalido":
                        status_fmt = "inválido ❌ (Simulado)"
                    else:
                        status_fmt = "válido ✅ (Simulado)"
                    
                    self.log(f"🧪 [ZONA DE TESTE] Report #{numero} analisado -> Status: {status_fmt}")
                    self.fila.put(("resultado", numero, status_fmt, texto_provas_bruto, resumo_desc))
                    
                    total_processados += 1
                    self.fila.put(("contador", total_processados))
                    if not self.lista_ids_forcados:
                        scraper.ir_para_pendentes(driver, self.config)
                    continue

                if resultado["status"] == "invalido":
                    self.log(f"Report #{numero}: SEM PROVA -> Inválido.")
                    try:
                        inicial_usada = self.staff_inicial if not self.lista_ids_forcados or self.motivo_massa == "Inválido (Padrão)" else f"{self.staff_inicial} - {self.motivo_massa}"
                        
                        if not self.modo_automatico:
                            self.fila.put(("notificar", "Ação Necessária (Manual)", f"Valide o report #{numero}."))
                        
                        actions.marcar_como_invalido(
                            driver, 
                            self.config, 
                            inicial_usada, 
                            self.modo_automatico, 
                            callback_aguardar_manual=lambda rid=numero: self.pedir_ok_manual(rid),
                            eh_duplicado=eh_duplicado,
                            eh_hack=eh_report_silencioso
                        )
                        
                        status_card = "inválido ❌"
                        if eh_duplicado:
                            status_card = "Inválido - Duplicado ❌"
                        elif eh_report_silencioso:
                            status_card = "Inválido - Hack/Smurf ❌"
                        
                        self.fila.put(("resultado", numero, status_card, texto_provas_bruto, resumo_desc))
                    except Exception as e:
                        self.log("⚠️ Ação cancelada pelo usuário ou falhou.")
                        self.fila.put(("resultado", numero, "Cancelado 🛑", texto_provas_bruto, resumo_desc))
                        
                elif resultado["status"] == "valido":
                    self.fila.put(("resultado", numero, "válido ✅", texto_provas_bruto, resumo_desc))
                else:
                    self.fila.put(("resultado", numero, "Revisão Manual ⚠️", texto_provas_bruto, resumo_desc))

                total_processados += 1
                self.fila.put(("contador", total_processados))
                if not self.lista_ids_forcados:
                    scraper.ir_para_pendentes(driver, self.config)

            self.log(f"✅ Processo concluído! Total: {total_processados}")
            self.fila.put(("fim", total_processados, len(reports)))

        except Exception as e:
            self.log(f"❌ Erro crítico: {e}")
            self.fila.put(("fim", 0, 0))
        finally:
            if driver is not None:
                try:
                    driver.quit()
                except Exception:
                    pass

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        try:
            self.prefs = carregar_preferencias_usuario()
            if not isinstance(self.prefs, dict):
                self.prefs = {}
        except Exception:
            self.prefs = {}

        self.title(f"GC - ToxiCleaner v{VERSAO_ATUAL} (Bot de Triagem)")
        self.geometry("1150x700")
        
        self.fila = queue.Queue()
        self.config_data = carregar_config(self.fila)
        self.worker = None
        self.em_pausa = False
        self.resultados_reports = []
        self.total_encontrados = 0
        self.hora_inicio = ""

        self.var_nome = ctk.StringVar(value=self.prefs.get("nome", ""))
        self.var_inicial = ctk.StringVar(value=self.prefs.get("inicial", ""))
        self.var_modo = ctk.StringVar(value=self.prefs.get("modo", "manual (clico em Notificar)"))
        self.var_data = ctk.StringVar(value=datetime.now().strftime("%d/%m/%Y"))
        
        self.var_navegador = ctk.StringVar(value="edge")
        self.var_quantidade = ctk.StringVar(value="")

        self.cfg_mostrar_staff = ctk.BooleanVar(value=True)
        self.cfg_mostrar_data = ctk.BooleanVar(value=True)
        self.cfg_mostrar_total = ctk.BooleanVar(value=True)
        self.cfg_mostrar_id = ctk.BooleanVar(value=True)
        self.cfg_mostrar_provas = ctk.BooleanVar(value=True)
        self.cfg_modo_fantasma = ctk.BooleanVar(value=False)
        
        self.cfg_tema_claro = ctk.BooleanVar(value=self.prefs.get("tema_claro", False))
        self.cfg_salvar_historico = ctk.StringVar(value=self.prefs.get("historico_nuvem", "Perguntar sempre"))
        ctk.set_appearance_mode("Light" if self.cfg_tema_claro.get() else "Dark")

        self.cfg_exibir_terminal = ctk.BooleanVar(value=self.prefs.get("exibir_terminal", False))
        self.cfg_exibir_barra = ctk.BooleanVar(value=self.prefs.get("exibir_barra", True))
        self.cfg_exibir_btn_pausar = ctk.BooleanVar(value=self.prefs.get("exibir_pausar", True))
        self.cfg_zona_teste = ctk.BooleanVar(value=False)

        # Radar de Auto-Save
        for var in [self.var_nome, self.var_inicial, self.var_modo, self.cfg_tema_claro, 
                    self.cfg_salvar_historico, self.cfg_exibir_terminal, 
                    self.cfg_exibir_barra, self.cfg_exibir_btn_pausar]:
            var.trace_add("write", self._auto_salvar_config)

        self._montar_ui()
        
        self.after(150, self._poll_fila)
        self.after(2000, self._verificar_atualizacao)
        self.protocol("WM_DELETE_WINDOW", self._ao_fechar)
        
    def _auto_salvar_config(self, *args):
        try:
            salvar_preferencias_usuario(
                self.var_nome.get().strip(),
                self.var_inicial.get().strip(),
                self.var_modo.get(),
                exibir_terminal=self.cfg_exibir_terminal.get(),
                exibir_pausar=self.cfg_exibir_btn_pausar.get(),
                exibir_barra=self.cfg_exibir_barra.get(),
                tema_claro=self.cfg_tema_claro.get(),
                historico_nuvem=self.cfg_salvar_historico.get()
            )
            ctk.set_appearance_mode("Light" if self.cfg_tema_claro.get() else "Dark")
        except Exception:
            pass

    def _salvar_dados_tempo_real(self, *args):
        self._auto_salvar_config()

    def _atualizar_visibilidade_elementos(self):
        """Alterna entre Terminal + Scroll Único OU Esconde Terminal + Abre 3 Colunas em 100% da tela"""
        if self.cfg_exibir_terminal.get():
            self.txt_log.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
            self.bottom_frame.columnconfigure(0, weight=5)
            self.bottom_frame.columnconfigure(1, weight=5)
            
            self.frame_colunas_resumo.grid_forget()
            self.scroll_resumo.grid(row=1, column=0, sticky="nsew", pady=(0, 10))
        else:
            self.txt_log.grid_remove()
            self.bottom_frame.columnconfigure(0, weight=0)
            self.bottom_frame.columnconfigure(1, weight=10)
            
            self.scroll_resumo.grid_forget()
            self.frame_colunas_resumo.grid(row=1, column=0, sticky="nsew", pady=(0, 10))

        if self.cfg_exibir_btn_pausar.get():
            self.btn_pausar.pack(side="left", padx=(0, 6), before=self.btn_parar)
        else:
            self.btn_pausar.pack_forget()

        if self.cfg_exibir_barra.get():
            self.progress_bar.pack(side="right", padx=(10, 0), pady=5)
        else:
            self.progress_bar.pack_forget()

    def _ao_fechar(self):
        try:
            self._salvar_dados_tempo_real()
        except Exception: pass
        self.destroy()

    def _copiar_para_area_transferencia(self, texto):
        self.clipboard_clear()
        self.clipboard_append(texto)
        self.update()

    def _verificar_atualizacao(self):
        if requests is None: return
        url_versao = "https://raw.githubusercontent.com/celsowilliam/Toxi-Cleaner/refs/heads/master/versao.json"
        try:
            r = requests.get(url_versao, timeout=4)
            if r.status_code == 200:
                dados = r.json()
                versao_github = dados.get("versao", VERSAO_ATUAL)
                url_download = dados.get("url_exe", "")
                lista_novidades = dados.get("novidades", [])
                
                if versao_github != VERSAO_ATUAL:
                    self._log(f"🚀 ATENÇÃO: Uma nova versão ({versao_github}) está disponível!")
                    disparar_notificacao("Atualização Disponível", f"A versão {versao_github} do ToxiCleaner já saiu!")
                    
                    win_pop = ctk.CTkToplevel(self)
                    win_pop.title("Nova Atualização Encontrada!")
                    win_pop.geometry("450x200")
                    win_pop.attributes("-topmost", True)
                    win_pop.transient(self)
                    win_pop.grab_set()

                    ctk.CTkLabel(
                        win_pop, 
                        text=f"🎉 A versão {versao_github} está disponível!\nDeseja atualizar o sistema agora?", 
                        font=ctk.CTkFont(size=14, weight="bold")
                    ).pack(pady=(20, 15))

                    btn_frm = ctk.CTkFrame(win_pop, fg_color="transparent")
                    btn_frm.pack(pady=10)

                    def _atualizar_com_relatorio():
                        win_pop.destroy()
                        if lista_novidades:
                            self._exibir_janela_novidades(versao_github, lista_novidades)
                        if url_download:
                            threading.Thread(target=self._baixar_e_atualizar, args=(url_download,), daemon=True).start()

                    def _atualizar_direto():
                        win_pop.destroy()
                        if url_download:
                            threading.Thread(target=self._baixar_e_atualizar, args=(url_download,), daemon=True).start()

                    def _cancelar():
                        win_pop.destroy()

                    ctk.CTkButton(btn_frm, text="📋 Atualizar e Ver Novidades", command=_atualizar_com_relatorio, fg_color="#6366f1", hover_color="#4f46e5").pack(side="left", padx=5)
                    ctk.CTkButton(btn_frm, text="🚀 Apenas Atualizar", command=_atualizar_direto, fg_color="#2EA043", hover_color="#238636").pack(side="left", padx=5)
                    ctk.CTkButton(btn_frm, text="Cancelar", command=_cancelar, fg_color="#6c757d", hover_color="#5a6268", width=70).pack(side="left", padx=5)

        except Exception: pass

    def _exibir_janela_novidades(self, versao, novidades):
        win_nov = ctk.CTkToplevel(self)
        win_nov.title(f"Relatório de Mudanças - v{versao}")
        win_nov.geometry("480x350")
        win_nov.attributes("-topmost", True)

        ctk.CTkLabel(win_nov, text=f"✨ O que há de novo na v{versao}:", font=ctk.CTkFont(size=16, weight="bold")).pack(pady=(15, 10), padx=15, anchor="w")

        scroll = ctk.CTkScrollableFrame(win_nov, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=15, pady=(0, 15))

        for item in novidades:
            card = ctk.CTkFrame(scroll, fg_color="#2b2b2b", corner_radius=6)
            card.pack(fill="x", pady=4, padx=2)
            ctk.CTkLabel(card, text=item, font=ctk.CTkFont(size=12), justify="left", wraplength=400).pack(fill="x", padx=10, pady=8)

    def _baixar_e_atualizar(self, url):
        self._log("📥 Baixando atualização... Por favor, aguarde e NÃO feche o bot.")
        self.btn_iniciar.configure(state="disabled")
        try:
            resposta = requests.get(url, stream=True, timeout=15)
            resposta.raise_for_status()
            
            caminho_exe_atual = sys.executable
            pasta_atual = os.path.dirname(caminho_exe_atual)
            nome_exe_atual = os.path.basename(caminho_exe_atual)
            caminho_novo_exe = os.path.join(pasta_atual, "novo_update.exe")
            
            with open(caminho_novo_exe, 'wb') as f:
                for chunk in resposta.iter_content(chunk_size=8192):
                    f.write(chunk)
                    
            self._log("✅ Download concluído! O bot vai reiniciar sozinho em 3 segundos...")
            
            caminho_bat = os.path.join(pasta_atual, "atualizador.bat")
            script_bat = f"""@echo off
timeout /t 3 /nobreak > NUL
del "{nome_exe_atual}"
ren "novo_update.exe" "{nome_exe_atual}"
start "" "{nome_exe_atual}"
del "%~f0"
"""
            with open(caminho_bat, "w") as f:
                f.write(script_bat)
                
            subprocess.Popen([caminho_bat], creationflags=subprocess.CREATE_NO_WINDOW, cwd=pasta_atual)
            os._exit(0)
            
        except Exception as e:
            self._log(f"❌ Erro ao baixar a atualização: {e}")
            self.btn_iniciar.configure(state="normal")

    def _abrir_janela_zona_teste(self):
        win_sb = ctk.CTkToplevel(self)
        win_sb.title("🧪 GC - ToxiCleaner (ZONA DE TESTE / SANDBOX)")
        win_sb.geometry("1150x720")
        win_sb.attributes("-topmost", True)

        fila_sb = queue.Queue()
        self.worker_sb = None
        self.em_pausa_sb = False

        sb_var_nome = ctk.StringVar(value=self.var_nome.get())
        sb_var_inicial = ctk.StringVar(value=self.var_inicial.get())
        sb_var_data = ctk.StringVar(value=self.var_data.get())
        sb_var_nav = ctk.StringVar(value="edge")
        sb_var_modo = ctk.StringVar(value="manual (clico em Notificar)")
        sb_var_qtd = ctk.StringVar(value="")
        sb_var_fantasma = ctk.BooleanVar(value=False)

        banner = ctk.CTkFrame(win_sb, fg_color="#0284c7", corner_radius=0)
        banner.pack(fill="x")
        ctk.CTkLabel(banner, text="🧪 AMBIENTE DE TESTE & SIMULAÇÃO (NENHUMA AÇÃO SERÁ ENVIADA À GC)", 
                   font=ctk.CTkFont(size=14, weight="bold"), text_color="white").pack(pady=6)

        main_sb = ctk.CTkFrame(win_sb, fg_color="#0f172a")
        main_sb.pack(fill="both", expand=True, padx=10, pady=10)

        hdr_frame = ctk.CTkFrame(main_sb, fg_color="transparent")
        hdr_frame.pack(fill="x", padx=10, pady=(5, 5))

        try:
            caminho_logo = os.path.join(base_dir(), "gc_logo.png")
            img_pil = Image.open(caminho_logo)
            img_gc = ctk.CTkImage(light_image=img_pil, dark_image=img_pil, size=(32, 32))
            ctk.CTkLabel(hdr_frame, image=img_gc, text="").pack(side="left", padx=(0, 10))
        except Exception: pass

        ctk.CTkLabel(hdr_frame, text="ToxiCleaner Sandbox", font=ctk.CTkFont(size=22, weight="bold"), text_color="#38bdf8").pack(side="left")

        hdr_btns = ctk.CTkFrame(hdr_frame, fg_color="transparent")
        hdr_btns.pack(side="right")

        ctk.CTkButton(hdr_btns, text="📊 Histórico Sandbox", command=lambda: self._abrir_historico(apenas_testes=True), width=130, fg_color="#0284c7", hover_color="#0369a1", text_color="white", font=ctk.CTkFont(weight="bold")).pack(side="left", padx=5)

        settings_frame = ctk.CTkFrame(main_sb, fg_color="transparent")
        settings_frame.pack(fill="x", padx=10, pady=5)
        settings_frame.columnconfigure(0, weight=1); settings_frame.columnconfigure(1, weight=1)

        frm_esq = ctk.CTkFrame(settings_frame, fg_color="#1e293b", corner_radius=10)
        frm_esq.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        ctk.CTkLabel(frm_esq, text="👤 Identificação do Staff (Teste)", font=ctk.CTkFont(size=14, weight="bold"), text_color="#38bdf8").pack(anchor="w", padx=15, pady=(10, 5))

        r1 = ctk.CTkFrame(frm_esq, fg_color="transparent"); r1.pack(fill="x", padx=15, pady=2)
        ctk.CTkLabel(r1, text="Nome:").pack(side="left")
        ctk.CTkEntry(r1, textvariable=sb_var_nome, width=180, height=24).pack(side="right")

        r2 = ctk.CTkFrame(frm_esq, fg_color="transparent"); r2.pack(fill="x", padx=15, pady=2)
        ctk.CTkLabel(r2, text="Inicial:").pack(side="left")
        ctk.CTkEntry(r2, textvariable=sb_var_inicial, width=180, height=24).pack(side="right")

        r3 = ctk.CTkFrame(frm_esq, fg_color="transparent"); r3.pack(fill="x", padx=15, pady=(2, 10))
        ctk.CTkLabel(r3, text="Data a limpar:").pack(side="left")
        ctk.CTkEntry(r3, textvariable=sb_var_data, width=180, height=24).pack(side="right")

        frm_dir = ctk.CTkFrame(settings_frame, fg_color="#1e293b", corner_radius=10)
        frm_dir.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        ctk.CTkLabel(frm_dir, text="⚙️ Configurações da Simulação", font=ctk.CTkFont(size=14, weight="bold"), text_color="#38bdf8").pack(anchor="w", padx=15, pady=(10, 5))

        r4 = ctk.CTkFrame(frm_dir, fg_color="transparent"); r4.pack(fill="x", padx=15, pady=2)
        ctk.CTkLabel(r4, text="Navegador:").pack(side="left")
        ctk.CTkComboBox(r4, variable=sb_var_nav, values=["edge", "chrome", "firefox"], state="readonly", width=180, height=24).pack(side="right")

        r5 = ctk.CTkFrame(frm_dir, fg_color="transparent"); r5.pack(fill="x", padx=15, pady=2)
        ctk.CTkLabel(r5, text="Modo:").pack(side="left")
        ctk.CTkComboBox(r5, variable=sb_var_modo, values=["manual (clico em Notificar)", "automatico (clica sozinho)"], state="readonly", width=180, height=24).pack(side="right")

        r6 = ctk.CTkFrame(frm_dir, fg_color="transparent"); r6.pack(fill="x", padx=15, pady=2)
        ctk.CTkLabel(r6, text="Qtde (vazio=todos):").pack(side="left")
        ctk.CTkEntry(r6, textvariable=sb_var_qtd, width=180, height=24).pack(side="right")

        rg = ctk.CTkFrame(frm_dir, fg_color="transparent"); rg.pack(fill="x", padx=15, pady=(2, 10))
        ctk.CTkLabel(rg, text="Modo Fantasma:").pack(side="left")
        ctk.CTkSwitch(rg, text="Requer 1º login", variable=sb_var_fantasma, switch_height=20, switch_width=40).pack(side="right")

        btn_frame = ctk.CTkFrame(main_sb, fg_color="transparent")
        btn_frame.pack(fill="x", padx=10, pady=5)

        btn_init = ctk.CTkButton(btn_frame, text="Iniciar Teste", width=90, fg_color="#2EA043", hover_color="#238636", text_color="white", font=ctk.CTkFont(weight="bold"))
        btn_init.pack(side="left", padx=(0, 6))

        btn_pausa = ctk.CTkButton(btn_frame, text="Pausar", width=90, state="disabled", fg_color="#3B82F6", hover_color="#2563EB", text_color="white", font=ctk.CTkFont(weight="bold"))
        btn_pausa.pack(side="left", padx=(0, 6))

        btn_parar = ctk.CTkButton(btn_frame, text="Parar", width=90, state="disabled", fg_color="#DA3633", hover_color="#B62324", text_color="white", font=ctk.CTkFont(weight="bold"))
        btn_parar.pack(side="left", padx=(0, 6))

        p_bar = ctk.CTkProgressBar(btn_frame, width=140, height=10)
        p_bar.pack(side="right", padx=(10, 0), pady=5); p_bar.set(0)

        info_frame = ctk.CTkFrame(main_sb, fg_color="transparent")
        info_frame.pack(fill="x", padx=10, pady=(0, 5))
        lbl_count = ctk.CTkLabel(info_frame, text="Reports simulados: 0 / 0", font=ctk.CTkFont(weight="bold"))
        lbl_count.pack(side="left")

        bottom_sb = ctk.CTkFrame(main_sb, fg_color="transparent")
        bottom_sb.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        bottom_sb.columnconfigure(0, weight=5); bottom_sb.columnconfigure(1, weight=5); bottom_sb.rowconfigure(0, weight=1)

        txt_log_sb = ctk.CTkTextbox(bottom_sb, fg_color="#1e293b", text_color="#38bdf8", wrap="word", font=ctk.CTkFont(family="Consolas", size=12))
        txt_log_sb.grid(row=0, column=0, sticky="nsew", padx=(0, 5))

        res_frame_sb = ctk.CTkFrame(bottom_sb, fg_color="transparent")
        res_frame_sb.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        res_frame_sb.rowconfigure(0, weight=0); res_frame_sb.rowconfigure(1, weight=1); res_frame_sb.rowconfigure(2, weight=0)
        res_frame_sb.columnconfigure(0, weight=1)

        ctk.CTkLabel(res_frame_sb, text="Saída e Cards (Simulação)", font=ctk.CTkFont(size=15, weight="bold"), text_color="#38bdf8").grid(row=0, column=0, sticky="w", pady=(0, 5))

        scroll_sb_main = ctk.CTkScrollableFrame(res_frame_sb, fg_color="#1e293b")
        scroll_sb_main.grid(row=1, column=0, sticky="nsew", pady=(0, 5))

        frame_colunas_sb = ctk.CTkFrame(res_frame_sb, fg_color="transparent")
        frame_colunas_sb.columnconfigure(0, weight=1); frame_colunas_sb.columnconfigure(1, weight=1); frame_colunas_sb.columnconfigure(2, weight=1)
        frame_colunas_sb.rowconfigure(0, weight=1)

        col_val_sb = ctk.CTkFrame(frame_colunas_sb, fg_color="#1e1e1e", corner_radius=8)
        col_val_sb.grid(row=0, column=0, sticky="nsew", padx=3, pady=2)
        ctk.CTkLabel(col_val_sb, text="🟢 Válidos", font=ctk.CTkFont(weight="bold"), text_color="#50fa7b").pack(pady=5)
        scroll_sb_val = ctk.CTkScrollableFrame(col_val_sb, fg_color="transparent")
        scroll_sb_val.pack(fill="both", expand=True, padx=2, pady=2)

        col_inv_sb = ctk.CTkFrame(frame_colunas_sb, fg_color="#1e1e1e", corner_radius=8)
        col_inv_sb.grid(row=0, column=1, sticky="nsew", padx=3, pady=2)
        ctk.CTkLabel(col_inv_sb, text="🔴 Inválidos", font=ctk.CTkFont(weight="bold"), text_color="#ff5555").pack(pady=5)
        scroll_sb_inv = ctk.CTkScrollableFrame(col_inv_sb, fg_color="transparent")
        scroll_sb_inv.pack(fill="both", expand=True, padx=2, pady=2)

        col_rev_sb = ctk.CTkFrame(frame_colunas_sb, fg_color="#1e1e1e", corner_radius=8)
        col_rev_sb.grid(row=0, column=2, sticky="nsew", padx=3, pady=2)
        ctk.CTkLabel(col_rev_sb, text="🟡 Avaliação Humana", font=ctk.CTkFont(weight="bold"), text_color="#ffb86c").pack(pady=5)
        scroll_sb_rev = ctk.CTkScrollableFrame(col_rev_sb, fg_color="transparent")
        scroll_sb_rev.pack(fill="both", expand=True, padx=2, pady=2)

        ctk.CTkButton(res_frame_sb, text="⎘ Copiar Resumo Sandbox", fg_color="#0284c7", hover_color="#0369a1", text_color="white", font=ctk.CTkFont(weight="bold")).grid(row=2, column=0, sticky="ew")

        ctk.CTkButton(
            hdr_btns, text="⚙ Config Sandbox", 
            command=lambda: self._abrir_painel_config_sandbox(win_sb, txt_log_sb, bottom_sb, scroll_sb_main, frame_colunas_sb, btn_pausa), 
            width=110, fg_color="#334155", hover_color="#1e293b", 
            text_color="white", font=ctk.CTkFont(weight="bold")
        ).pack(side="left", padx=5)

        def _add_card_sb(container, rid, st, prv):
            card = ctk.CTkFrame(container, fg_color="#0f172a", corner_radius=6)
            card.pack(fill="x", pady=3, padx=2)
            
            top = ctk.CTkFrame(card, fg_color="transparent")
            top.pack(fill="x", padx=8, pady=(4, 2))
            ctk.CTkLabel(top, text=f"Report #{rid}", font=ctk.CTkFont(weight="bold"), text_color="white").pack(side="left")
            ctk.CTkLabel(top, text=st, text_color="#38bdf8", font=ctk.CTkFont(weight="bold")).pack(side="right")
            
            conteudo_frame = ctk.CTkFrame(card, fg_color="#1e293b", corner_radius=6)
            conteudo_frame.pack(fill="x", padx=8, pady=(2, 6))

            linhas = prv.split('\n')
            tem_resumo = len(linhas) > 1

            if tem_resumo:
                ctk.CTkLabel(
                    conteudo_frame, 
                    text=linhas[0], 
                    font=ctk.CTkFont(size=11, weight="bold"), 
                    text_color="#cccccc", justify="left", wraplength=280
                ).pack(anchor="w", padx=8, pady=(6, 0))
                texto_link = linhas[1]
            else:
                texto_link = linhas[0]

            lbl_link = ctk.CTkLabel(
                conteudo_frame, 
                text=texto_link, 
                font=ctk.CTkFont(size=11, underline=True), 
                text_color="#38bdf8", justify="left", wraplength=280, cursor="hand2"
            )
            lbl_link.pack(anchor="w", padx=8, pady=(2, 6) if tem_resumo else (6, 6))

            def _abrir_link_sb(event, texto):
                import webbrowser
                import re
                match = re.search(r'(https?://\S+|file:///\S+)', texto)
                url_final = match.group(1) if match else texto
                webbrowser.open(url_final)

            lbl_link.bind("<Button-1>", lambda e, t=texto_link: _abrir_link_sb(e, t))

        def _checar_fila_sb():
            while not fila_sb.empty():
                try:
                    ev = fila_sb.get_nowait()
                    tp = ev[0]
                    
                    if tp == "log":
                        txt_log_sb.insert("end", f"{ev[1]}\n")
                        txt_log_sb.see("end")
                    elif tp == "resultado":
                        rid, st, prv = ev[1], ev[2], ev[3]
                        res_desc = ev[4] if len(ev) > 4 else ""
                        
                        motivo_real = res_desc if res_desc and res_desc.strip() not in ["", "Outros/Sem tags"] else "Sem motivo especificado"
                        texto_exibicao = f"📌 {motivo_real}\n🔗 {prv}"
                        
                        _add_card_sb(scroll_sb_main, rid, st, texto_exibicao)
                        
                        st_lower = st.lower()
                        if "inválido" in st_lower or "hack" in st_lower or "duplicado" in st_lower:
                            dest = scroll_sb_inv
                        elif "válido" in st_lower:
                            dest = scroll_sb_val
                        else:
                            dest = scroll_sb_rev
                            
                        _add_card_sb(dest, rid, st, texto_exibicao)
                    elif tp == "contador":
                        lbl_count.configure(text=f"Reports simulados: {ev[1]}")
                    elif tp == "fim":
                        btn_init.configure(state="normal")
                        btn_pausa.configure(state="disabled", text="Pausar", fg_color="#3B82F6")
                        btn_parar.configure(state="disabled")
                except queue.Empty:
                    break
            
            if win_sb.winfo_exists():
                win_sb.after(100, _checar_fila_sb)

        def _iniciar_sb():
            nome_sb = sb_var_nome.get().strip()
            inicial_sb = sb_var_inicial.get().strip()

            if not nome_sb or not inicial_sb:
                messagebox.showwarning("Aviso", "Por favor, preencha o Nome e Inicial na Sandbox!")
                return

            btn_init.configure(state="disabled")
            btn_pausa.configure(state="normal")
            btn_parar.configure(state="normal")

            qtd_val = int(sb_var_qtd.get().strip()) if sb_var_qtd.get().strip().isdigit() else None
            modo_teste_str = f"{sb_var_modo.get()} (teste)"

            self.worker_sb = BotWorker(
                self.config_data, nome_sb, inicial_sb,
                sb_var_data.get().strip(), sb_var_nav.get(),
                modo_teste_str, qtd_val, fila_sb,
                headless=sb_var_fantasma.get(), zona_teste=True
            )
            self.worker_sb.start()

        def _toggle_pausa_sb():
            if not self.worker_sb: return
            if self.em_pausa_sb:
                self.worker_sb.retomar()
                self.em_pausa_sb = False
                btn_pausa.configure(text="Pausar", fg_color="#3B82F6")
            else:
                self.worker_sb.pausar()
                self.em_pausa_sb = True
                btn_pausa.configure(text="Retomar", fg_color="#EAB308")

        def _parar_sb():
            if self.worker_sb:
                self.worker_sb.parar()

        btn_init.configure(command=_iniciar_sb)
        btn_pausa.configure(command=_toggle_pausa_sb)
        btn_parar.configure(command=_parar_sb)

        win_sb.after(100, _checar_fila_sb)

    def _tratar_modo_fantasma(self, *args):
        if "teste" in self.var_modo.get():
            self.cfg_modo_fantasma.set(False)
            self.sw_fantasma.configure(state="disabled", text="Desabilitado no Modo Teste")
        else:
            self.sw_fantasma.configure(state="normal", text="Requer 1º login visível")

    def _adicionar_card_resumo(self, container, report_id, status, prova_texto):
        card = ctk.CTkFrame(container, fg_color="#2b2b2b", corner_radius=6)
        card.pack(fill="x", pady=3, padx=2)

        topo = ctk.CTkFrame(card, fg_color="transparent")
        topo.pack(fill="x", padx=8, pady=(4, 0))
        
        ctk.CTkLabel(topo, text=f"Report #{report_id}", font=ctk.CTkFont(weight="bold")).pack(side="left")
        cor_st = "#ff5555" if "inválido" in status.lower() else "#50fa7b" if "válido" in status.lower() else "#ffb86c"
        ctk.CTkLabel(topo, text=status, text_color=cor_st, font=ctk.CTkFont(weight="bold")).pack(side="right")

        txt_prova = ctk.CTkTextbox(card, height=42, font=ctk.CTkFont(size=11), fg_color="#1e1e1e", text_color="#cccccc")
        txt_prova.pack(fill="x", padx=8, pady=(2, 6))
        txt_prova.insert("1.0", prova_texto)
        txt_prova.configure(state="normal")

    def _abrir_historico(self, apenas_testes=False):
        win_hist = ctk.CTkToplevel(self)
        win_hist.title("Histórico Sandbox" if apenas_testes else "Histórico Global - GC")
        win_hist.geometry("700x600")
        win_hist.transient(self)
        win_hist.attributes("-topmost", True)
        win_hist.focus_force()

        frame_lista = ctk.CTkFrame(win_hist, fg_color="transparent")
        frame_lista.pack(fill="both", expand=True)

        tabview = ctk.CTkTabview(frame_lista)
        tabview.pack(fill="both", expand=True, padx=10, pady=10)

        dados_firebase = ler_historico_firebase() or {}
        registros = list(dados_firebase.items())
        registros.reverse()

        estatisticas_por_dia = {}
        for k, reg in registros:
            dt = reg.get('data_triagem', 'S/D')
            if dt not in estatisticas_por_dia:
                estatisticas_por_dia[dt] = {'total_processados': 0, 'max_encontrados': 0, 'execucoes': 0}
            
            reps = reg.get('reports', [])
            estatisticas_por_dia[dt]['total_processados'] += int(reg.get('processados', len(reps)))
            estatisticas_por_dia[dt]['max_encontrados'] = max(estatisticas_por_dia[dt]['max_encontrados'], int(reg.get('encontrados', len(reps))))
            estatisticas_por_dia[dt]['execucoes'] += 1

        dias_vistos = set()

        if apenas_testes:
            tab_teste = tabview.add("🧪 Registros da Zona de Teste")
            scroll_teste = ctk.CTkScrollableFrame(tab_teste, fg_color="transparent")
            scroll_teste.pack(fill="both", expand=True, padx=5, pady=5)

            for key_id, reg in registros:
                modo_reg = str(reg.get('modo', '')).lower()
                if "teste" in modo_reg or "sandbox" in modo_reg:
                    dt = reg.get('data_triagem', 'S/D')
                    is_latest = dt not in dias_vistos
                    dias_vistos.add(dt)
                    
                    stats = estatisticas_por_dia[dt]
                    self._criar_card_historico(scroll_teste, reg, key_id, "#0284c7", win_hist, frame_lista, stats, is_latest)
        else:
            tab_auto = tabview.add("🟢 Automático (Oficial)")
            tab_manual = tabview.add("🟠 Manual (Oficial)")

            scroll_auto = ctk.CTkScrollableFrame(tab_auto, fg_color="transparent")
            scroll_auto.pack(fill="both", expand=True, padx=5, pady=5)

            scroll_manual = ctk.CTkScrollableFrame(tab_manual, fg_color="transparent")
            scroll_manual.pack(fill="both", expand=True, padx=5, pady=5)

            for key_id, reg in registros:
                modo_reg = str(reg.get('modo', '')).lower()
                if "teste" in modo_reg or "sandbox" in modo_reg:
                    continue

                dt = reg.get('data_triagem', 'S/D')
                is_latest = dt not in dias_vistos
                dias_vistos.add(dt)

                stats = estatisticas_por_dia[dt]
                if "auto" in modo_reg:
                    self._criar_card_historico(scroll_auto, reg, key_id, "#28a745", win_hist, frame_lista, stats, is_latest)
                else:
                    self._criar_card_historico(scroll_manual, reg, key_id, "#ff9800", win_hist, frame_lista, stats, is_latest)

    def _criar_card_historico(self, container, reg, key_id, border_color, win_hist, frame_lista, stats_dia, is_latest):
        dt_triagem = reg.get('data_triagem', 'S/D')
        hora_exec = reg.get('hora_execucao', reg.get('data_execucao', 'Sem Horário'))
        staff = reg.get('staff', 'Desconhecido')
        reports = reg.get("reports", [])

        proc_sessao = int(reg.get('processados', len(reports)))
        enc_sessao = int(reg.get('encontrados', len(reports)))

        total_proc_dia = stats_dia['total_processados']
        max_enc_dia = stats_dia['max_encontrados']
        num_limpezas = stats_dia['execucoes']

        if not is_latest:
            cor_indicador = "#374151"
            cor_fundo_badge = "#4b5563"
            cor_hover = "#374151"
            txt_badge = "ANTIGO"
            cor_titulo = "#9ca3af"
        elif max_enc_dia > 0 and total_proc_dia >= max_enc_dia:
            cor_indicador = "#10b981"
            cor_fundo_badge = "#059669"
            cor_hover = "#047857"
            txt_badge = f"COMPLETO ({num_limpezas}x)" if num_limpezas > 1 else "COMPLETO"
            cor_titulo = "white"
        else:
            cor_indicador = "#f59e0b"
            cor_fundo_badge = "#d97706"
            cor_hover = "#b45309"
            txt_badge = "INCOMPLETO"
            cor_titulo = "white"

        card = ctk.CTkFrame(container, fg_color="#1e1e1e", corner_radius=4, height=32)
        card.pack(fill="x", pady=2, padx=5)
        card.pack_propagate(False)

        indicador = ctk.CTkFrame(card, fg_color=cor_indicador, width=3, corner_radius=0)
        indicador.pack(side="left", fill="y", pady=2, padx=(2, 6))

        ctk.CTkLabel(card, text=f"📅 {dt_triagem}", font=ctk.CTkFont(size=11, weight="bold"), text_color=cor_titulo).pack(side="left", padx=(0, 6))

        ctk.CTkLabel(
            card, text=txt_badge, font=ctk.CTkFont(size=9, weight="bold"),
            text_color="white", fg_color=cor_fundo_badge, corner_radius=4,
            height=16, padx=6
        ).pack(side="left", padx=(0, 15))

        info_txt = f"👤 {staff}   •   🕒 {hora_exec}   •   📦 Feitos: {proc_sessao}/{enc_sessao}"
        ctk.CTkLabel(card, text=info_txt, font=ctk.CTkFont(size=10), text_color="#9ca3af").pack(side="left")

        btn_ver = ctk.CTkButton(
            card, text="📂 Detalhes", width=70, height=20,
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color=cor_fundo_badge, hover_color=cor_hover,
            command=lambda r=reports, d=dt_triagem, k=key_id: self._abrir_detalhes_historico(d, r, k, win_hist, frame_lista)
        )
        btn_ver.pack(side="right", padx=6)

    def _toggle_pausa(self):
        if not self.worker:
            return
        if self.em_pausa:
            self.worker.retomar()
            self.em_pausa = False
            self.btn_pausar.configure(text="Pausar", fg_color="#3B82F6", hover_color="#2563EB")
            self._log("▶️ Execução retomada.")
        else:
            self.worker.pausar()
            self.em_pausa = True
            self.btn_pausar.configure(text="Retomar", fg_color="#EAB308", hover_color="#CA8A04")
            self._log("⏸️ Execução pausada.")

    def _montar_ui(self):
        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.pack(fill="x", padx=15, pady=(15, 5))
        
        caminho_logo = os.path.join(base_dir(), "gc_logo.png")
        if os.path.exists(caminho_logo):
            try:
                img_pil = Image.open(caminho_logo)
                self.img_gc = ctk.CTkImage(light_image=img_pil, dark_image=img_pil, size=(32, 32))
                lbl_logo = ctk.CTkLabel(header_frame, image=self.img_gc, text="")
                lbl_logo.pack(side="left", padx=(0, 10))
            except Exception as e:
                print(f"Erro ao carregar imagem: {e}")

        ctk.CTkLabel(header_frame, text="ToxiCleaner Dashboard", font=ctk.CTkFont(size=24, weight="bold")).pack(side="left")
        
        hdr_btn_frm = ctk.CTkFrame(header_frame, fg_color="transparent")
        hdr_btn_frm.pack(side="right")
        self.btn_massa = ctk.CTkButton(hdr_btn_frm, text="⚡ Invalidação", command=self._abrir_painel_massa, fg_color="#ff9800", hover_color="#f57c00", text_color="black", font=ctk.CTkFont(weight="bold"), width=100)
        self.btn_massa.pack(side="left", padx=5)
        self.btn_historico = ctk.CTkButton(hdr_btn_frm, text="📊 Histórico GC", command=self._abrir_historico, width=110, fg_color="#6366f1", hover_color="#4f46e5", text_color="white", font=ctk.CTkFont(weight="bold"))
        self.btn_historico.pack(side="left", padx=5)
        self.btn_config = ctk.CTkButton(hdr_btn_frm, text="⚙ Config", command=self._abrir_painel_config, width=80, fg_color="#6c757d", hover_color="#5a6268", text_color="white", font=ctk.CTkFont(weight="bold"))
        self.btn_config.pack(side="left", padx=5)

        settings_frame = ctk.CTkFrame(self, fg_color="transparent")
        settings_frame.pack(fill="x", padx=15, pady=10)
        settings_frame.columnconfigure(0, weight=1); settings_frame.columnconfigure(1, weight=1)

        frm_esq = ctk.CTkFrame(settings_frame, corner_radius=10)
        frm_esq.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        ctk.CTkLabel(frm_esq, text="👤 Identificação do Staff", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=15, pady=(15, 10))
        
        row1 = ctk.CTkFrame(frm_esq, fg_color="transparent"); row1.pack(fill="x", padx=15, pady=2)
        ctk.CTkLabel(row1, text="Nome:").pack(side="left")
        entry_nome = ctk.CTkEntry(row1, textvariable=self.var_nome, width=180, height=24)
        entry_nome.pack(side="right")
        entry_nome.bind("<KeyRelease>", self._salvar_dados_tempo_real)

        row2 = ctk.CTkFrame(frm_esq, fg_color="transparent"); row2.pack(fill="x", padx=15, pady=2)
        ctk.CTkLabel(row2, text="Inicial:").pack(side="left")
        entry_inicial = ctk.CTkEntry(row2, textvariable=self.var_inicial, width=180, height=24)
        entry_inicial.pack(side="right")
        entry_inicial.bind("<KeyRelease>", self._salvar_dados_tempo_real)

        row3 = ctk.CTkFrame(frm_esq, fg_color="transparent"); row3.pack(fill="x", padx=15, pady=(2, 15))
        ctk.CTkLabel(row3, text="Data a limpar:").pack(side="left")
        ctk.CTkEntry(row3, textvariable=self.var_data, width=180, height=24).pack(side="right")

        frm_dir = ctk.CTkFrame(settings_frame, corner_radius=10)
        frm_dir.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        ctk.CTkLabel(frm_dir, text="⚙️ Configurações do Bot", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=15, pady=(15, 10))

        row4 = ctk.CTkFrame(frm_dir, fg_color="transparent"); row4.pack(fill="x", padx=15, pady=2)
        ctk.CTkLabel(row4, text="Navegador:").pack(side="left")
        ctk.CTkComboBox(row4, variable=self.var_navegador, values=["edge", "chrome", "firefox"], state="readonly", width=180, height=24, command=self._salvar_dados_tempo_real).pack(side="right")

        row5 = ctk.CTkFrame(frm_dir, fg_color="transparent"); row5.pack(fill="x", padx=15, pady=2)
        ctk.CTkLabel(row5, text="Modo:").pack(side="left")
        
        def _mudou_modo(escolha):
            self._tratar_modo_fantasma()
            self._salvar_dados_tempo_real()
            
        ctk.CTkComboBox(
            row5, 
            variable=self.var_modo, 
            values=["manual (clico em Notificar)", "automatico (clica sozinho)"], 
            state="readonly", 
            width=180, 
            height=24,
            command=_mudou_modo
        ).pack(side="right")

        row6 = ctk.CTkFrame(frm_dir, fg_color="transparent"); row6.pack(fill="x", padx=15, pady=2)
        ctk.CTkLabel(row6, text="Qtde (vazio=todos):").pack(side="left")
        ctk.CTkEntry(row6, textvariable=self.var_quantidade, width=180, height=24).pack(side="right")

        row_ghost = ctk.CTkFrame(frm_dir, fg_color="transparent"); row_ghost.pack(fill="x", padx=15, pady=(2, 15))
        ctk.CTkLabel(row_ghost, text="Modo Fantasma:").pack(side="left")
        self.sw_fantasma = ctk.CTkSwitch(row_ghost, text="Requer 1º login", variable=self.cfg_modo_fantasma, switch_height=20, switch_width=40)
        self.sw_fantasma.pack(side="right", anchor="e")

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=15, pady=5)
        
        self.btn_iniciar = ctk.CTkButton(
            btn_frame, 
            text="Iniciar", 
            command=self._iniciar, 
            width=90, 
            fg_color="#2EA043", 
            hover_color="#238636", 
            text_color="white", 
            font=ctk.CTkFont(weight="bold")
        )
        self.btn_iniciar.pack(side="left", padx=(0, 6))
        
        self.btn_pausar = ctk.CTkButton(btn_frame, text="Pausar", command=self._toggle_pausa, state="disabled", width=80, fg_color="#3B82F6", hover_color="#2563EB", text_color="white", font=ctk.CTkFont(weight="bold"))
        self.btn_pausar.pack(side="left", padx=(0, 6))
        
        self.btn_parar = ctk.CTkButton(btn_frame, text="Parar", command=self._parar, state="disabled", width=80, fg_color="#DA3633", hover_color="#B62324", text_color="white", font=ctk.CTkFont(weight="bold"))
        self.btn_parar.pack(side="left", padx=(0, 6))

        self.progress_bar = ctk.CTkProgressBar(btn_frame, width=140, height=10)
        self.progress_bar.pack(side="right", padx=(10, 0), pady=5)
        self.progress_bar.set(0)

        info_frame = ctk.CTkFrame(self, fg_color="transparent")
        info_frame.pack(fill="x", padx=15, pady=(2, 8))
        
        self.lbl_contador = ctk.CTkLabel(info_frame, text="Reports processados: 0 / 0", font=ctk.CTkFont(weight="bold"))
        self.lbl_contador.pack(side="left")

        self.bottom_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.bottom_frame.pack(fill="both", expand=True, padx=15, pady=(0, 15))
        self.bottom_frame.columnconfigure(0, weight=5); self.bottom_frame.columnconfigure(1, weight=5); self.bottom_frame.rowconfigure(0, weight=1)

        self.txt_log = ctk.CTkTextbox(self.bottom_frame, state="disabled", wrap="word", font=ctk.CTkFont(family="Consolas", size=12))
        self.txt_log.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.txt_log.tag_config("erro", foreground="#ff5555"); self.txt_log.tag_config("aviso", foreground="#ffb86c"); self.txt_log.tag_config("sucesso", foreground="#50fa7b")
        self.txt_log.tag_config("destaque", foreground="#8be9fd"); self.txt_log.tag_config("normal", foreground="#cccccc")

        resumo_frame = ctk.CTkFrame(self.bottom_frame, fg_color="transparent")
        resumo_frame.grid(row=0, column=1, sticky="nsew")
        resumo_frame.rowconfigure(0, weight=0); resumo_frame.rowconfigure(1, weight=1); resumo_frame.rowconfigure(2, weight=0)
        resumo_frame.columnconfigure(0, weight=1)
        
        self.lbl_saida = ctk.CTkLabel(resumo_frame, text="Saída e Comentários", font=ctk.CTkFont(size=16, weight="bold"))
        self.lbl_saida.grid(row=0, column=0, sticky="w", pady=(0, 5), padx=5)

        self.scroll_resumo = ctk.CTkScrollableFrame(resumo_frame, fg_color="transparent")

        self.frame_colunas_resumo = ctk.CTkFrame(resumo_frame, fg_color="transparent")
        self.frame_colunas_resumo.columnconfigure(0, weight=1)
        self.frame_colunas_resumo.columnconfigure(1, weight=1)
        self.frame_colunas_resumo.columnconfigure(2, weight=1)
        self.frame_colunas_resumo.rowconfigure(0, weight=1)

        col_val = ctk.CTkFrame(self.frame_colunas_resumo, fg_color="#1e1e1e", corner_radius=8)
        col_val.grid(row=0, column=0, sticky="nsew", padx=3, pady=2)
        ctk.CTkLabel(col_val, text="🟢 Válidos", font=ctk.CTkFont(weight="bold"), text_color="#50fa7b").pack(pady=5)
        self.scroll_tab_validos = ctk.CTkScrollableFrame(col_val, fg_color="transparent")
        self.scroll_tab_validos.pack(fill="both", expand=True, padx=2, pady=2)

        col_inv = ctk.CTkFrame(self.frame_colunas_resumo, fg_color="#1e1e1e", corner_radius=8)
        col_inv.grid(row=0, column=1, sticky="nsew", padx=3, pady=2)
        ctk.CTkLabel(col_inv, text="🔴 Inválidos", font=ctk.CTkFont(weight="bold"), text_color="#ff5555").pack(pady=5)
        self.scroll_tab_invalidos = ctk.CTkScrollableFrame(col_inv, fg_color="transparent")
        self.scroll_tab_invalidos.pack(fill="both", expand=True, padx=2, pady=2)

        col_rev = ctk.CTkFrame(self.frame_colunas_resumo, fg_color="#1e1e1e", corner_radius=8)
        col_rev.grid(row=0, column=2, sticky="nsew", padx=3, pady=2)
        ctk.CTkLabel(col_rev, text="🟡 Avaliação Humana", font=ctk.CTkFont(weight="bold"), text_color="#ffb86c").pack(pady=5)
        self.scroll_tab_revisao = ctk.CTkScrollableFrame(col_rev, fg_color="transparent")
        self.scroll_tab_revisao.pack(fill="both", expand=True, padx=2, pady=2)

        self._atualizar_visibilidade_elementos()

    def _abrir_detalhes_historico(self, data_dia, lista_reports, key_firebase, win_hist, frame_lista):
        frame_lista.pack_forget()
        win_hist.geometry("700x600")

        frame_mestre = ctk.CTkFrame(win_hist, fg_color="transparent")
        frame_mestre.pack(fill="both", expand=True)

        frame_esquerda = ctk.CTkFrame(frame_mestre, fg_color="transparent")
        frame_esquerda.pack(side="left", fill="both", expand=True)

        frame_direita = ctk.CTkFrame(frame_mestre, fg_color="#1a1a1a", width=380, corner_radius=0)

        top_bar = ctk.CTkFrame(frame_esquerda, fg_color="transparent")
        top_bar.pack(fill="x", padx=10, pady=(10, 0))

        def _voltar():
            frame_mestre.destroy()
            win_hist.geometry("700x600")
            frame_lista.pack(fill="both", expand=True)

        ctk.CTkButton(
            top_bar, text="⬅️ Voltar", width=80, height=28,
            fg_color="#4b5563", hover_color="#374151", font=ctk.CTkFont(weight="bold"),
            command=_voltar
        ).pack(side="left")

        ctk.CTkLabel(top_bar, text=f"Detalhes da Triagem - {data_dia}", font=ctk.CTkFont(size=16, weight="bold")).pack(side="left", padx=15)

        scroll = ctk.CTkScrollableFrame(frame_esquerda, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=10, pady=10)

        for idx, item in enumerate(lista_reports):
            c = ctk.CTkFrame(scroll, fg_color="#2b2b2b", corner_radius=8)
            c.pack(fill="x", pady=5, padx=5)

            t = ctk.CTkFrame(c, fg_color="transparent")
            t.pack(fill="x", padx=10, pady=5)
            ctk.CTkLabel(t, text=f"Report #{item['id']}", font=ctk.CTkFont(weight="bold")).pack(side="left")
            
            status_texto = item.get('status', 'Pendente')
            status_lower = status_texto.lower()
            
            if "duplicado" in status_lower:
                cor_st = "#f59e0b"
            elif "hack" in status_lower or "xit" in status_lower:
                cor_st = "#ef4444"
            elif "troll" in status_lower or "toxico" in status_lower or "tóxico" in status_lower:
                cor_st = "#10b981"
            elif "válido" in status_lower:
                cor_st = "#50fa7b"
            elif "inválido" in status_lower or "insuficiente" in status_lower:
                cor_st = "#f87171"
            else:
                cor_st = "#9ca3af"
                
            ctk.CTkLabel(t, text=status_texto, text_color=cor_st, font=ctk.CTkFont(weight="bold")).pack(side="right")

            txt_provas = item.get('prova', item.get('texto_provas', 'Sem provas registradas'))
            txt_resumo = item.get('resumo_desc', '')

            motivo_real = txt_resumo if txt_resumo and txt_resumo.strip() not in ["", "Outros/Sem tags"] else "Sem motivo especificado"
            texto_exibicao = f"📌 {motivo_real}\n🔗 {txt_provas}"

            ctk.CTkLabel(
                c, text=texto_exibicao, 
                text_color="#60a5fa", 
                font=ctk.CTkFont(size=11), 
                justify="left", 
                wraplength=480
            ).pack(anchor="w", padx=10, pady=(0, 5))

            btn_add_coment = ctk.CTkButton(
                c, text="💬 Comentários", height=28, 
                fg_color="#3b82f6", hover_color="#1d4ed8", font=ctk.CTkFont(weight="bold"),
                command=lambda r_idx=idx, itm=item: self._abrir_painel_comentarios_lateral(key_firebase, r_idx, itm, win_hist, frame_direita)
            )
            btn_add_coment.pack(padx=10, pady=(5, 10))

    def _abrir_painel_comentarios_lateral(self, key_firebase, idx_report, item, win_hist, frame_direita):
        win_hist.geometry("1080x600")
        frame_direita.pack(side="right", fill="y", padx=(5, 0))
        
        for widget in frame_direita.winfo_children():
            widget.destroy()

        topo_dir = ctk.CTkFrame(frame_direita, fg_color="transparent")
        topo_dir.pack(fill="x", padx=15, pady=(15, 10))
        
        ctk.CTkLabel(topo_dir, text=f"💬 Report #{item['id']}", font=ctk.CTkFont(size=16, weight="bold")).pack(side="left")
        
        def _fechar_painel():
            frame_direita.pack_forget()
            win_hist.geometry("700x600")
            
        ctk.CTkButton(
            topo_dir, text="❌", width=30, height=24, 
            fg_color="transparent", hover_color="#ef4444", 
            command=_fechar_painel
        ).pack(side="right")

        scroll_com = ctk.CTkScrollableFrame(frame_direita, fg_color="#121212")
        scroll_com.pack(fill="both", expand=True, padx=15, pady=5)

        def _carregar_comentarios():
            for widget in scroll_com.winfo_children():
                widget.destroy()
                
            comentarios = item.get("historico_comentarios", [])
            if item.get('comentario') and not comentarios:
                comentarios.append(f"Staff: {item['comentario']}")
            
            if not comentarios:
                ctk.CTkLabel(scroll_com, text="Nenhum comentário ainda.", text_color="gray").pack(pady=20)
            else:
                for c in comentarios:
                    balao = ctk.CTkFrame(scroll_com, fg_color="#2b2b2b", corner_radius=8)
                    balao.pack(fill="x", pady=4, padx=5)
                    ctk.CTkLabel(balao, text=c, justify="left", wraplength=280, font=ctk.CTkFont(size=12)).pack(anchor="w", padx=10, pady=8)

        _carregar_comentarios()

        frm_novo = ctk.CTkFrame(frame_direita, fg_color="transparent")
        frm_novo.pack(fill="x", padx=15, pady=15)
        
        txt_novo = ctk.CTkTextbox(frm_novo, height=60, fg_color="#2b2b2b")
        txt_novo.pack(fill="x", pady=(0, 10))

        def _enviar_comentario():
            texto = txt_novo.get("1.0", "end").strip()
            if not texto: return
            
            autor = self.var_nome.get().strip() or "Staff"
            novo_comentario_fmt = f"[{datetime.now().strftime('%d/%m %H:%M')}] {autor}: {texto}"
            
            if "historico_comentarios" not in item:
                item["historico_comentarios"] = []
            item["historico_comentarios"].append(novo_comentario_fmt)
            
            threading.Thread(target=salvar_comentario_report_firebase, args=(key_firebase, idx_report, novo_comentario_fmt), daemon=True).start()
            
            self._log(f"💬 Comentário adicionado ao Report #{item['id']}!")
            txt_novo.delete("1.0", "end")
            _carregar_comentarios()

        ctk.CTkButton(frm_novo, text="Enviar Comentário", fg_color="#2EA043", hover_color="#238636", font=ctk.CTkFont(weight="bold"), command=_enviar_comentario).pack(anchor="e")

    def _iniciar_teste_simulado_auto(self):
        self.var_modo.set("automatico (teste)")
        self._iniciar()
        self._log("🧪 Teste do Modo Automático iniciado e direcionado para a aba de Testes!")

    def _modal_novo_comentario(self, key_firebase, idx_report, report_id, win_pai):
        dialog = ctk.CTkInputDialog(text=f"Digite o comentário para o Report #{report_id}:", title="Novo Comentário")
        texto = dialog.get_input()
        
        if texto:
            autor = f"{self.var_nome.get().strip()}" or "Staff"
            novo_comentario_fmt = f"[{datetime.now().strftime('%d/%m %H:%M')}] {autor}: {texto}"
            salvar_comentario_report_firebase(key_firebase, idx_report, novo_comentario_fmt)
            self._log(f"💬 Comentário salvo no Report #{report_id}!")
            win_pai.destroy()

    def _abrir_painel_config_sandbox(self, janela_pai, txt_log_sb, bottom_sb, scroll_sb_main, frame_colunas_sb, btn_pausa):
        win_cfg_sb = ctk.CTkToplevel(janela_pai)
        win_cfg_sb.title("Configurações - Zona de Teste")
        win_cfg_sb.geometry("380x260")
        win_cfg_sb.transient(janela_pai)
        win_cfg_sb.attributes("-topmost", True)
        win_cfg_sb.focus_force()

        ctk.CTkLabel(win_cfg_sb, text="⚙️ Preferências da Zona de Teste", font=ctk.CTkFont(size=15, weight="bold"), text_color="#38bdf8").pack(pady=(15, 10))

        if not hasattr(self, "sb_cfg_terminal"):
            self.sb_cfg_terminal = ctk.BooleanVar(value=False)
            self.sb_cfg_pausar = ctk.BooleanVar(value=True)

        def _toggle_log_sb():
            if self.sb_cfg_terminal.get():
                txt_log_sb.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
                bottom_sb.columnconfigure(0, weight=5)
                bottom_sb.columnconfigure(1, weight=5)
                
                frame_colunas_sb.grid_forget()
                scroll_sb_main.grid(row=1, column=0, sticky="nsew", pady=(0, 5))
            else:
                txt_log_sb.grid_remove()
                bottom_sb.columnconfigure(0, weight=0)
                bottom_sb.columnconfigure(1, weight=10)
                
                scroll_sb_main.grid_forget()
                frame_colunas_sb.grid(row=1, column=0, sticky="nsew", pady=(0, 5))

        def _toggle_pausa_sb():
            if self.sb_cfg_pausar.get():
                btn_pausa.pack(side="left", padx=(0, 6))
            else:
                btn_pausa.pack_forget()

        ctk.CTkSwitch(win_cfg_sb, text="Abrir Log", variable=self.sb_cfg_terminal, command=_toggle_log_sb).pack(pady=8, padx=30, anchor="w")
        ctk.CTkSwitch(win_cfg_sb, text="Exibir Botão Pausar / Retomar", variable=self.sb_cfg_pausar, command=_toggle_pausa_sb).pack(pady=8, padx=30, anchor="w")

        ctk.CTkLabel(win_cfg_sb, text="*(Alterações aplicadas instantaneamente)*", font=ctk.CTkFont(size=10), text_color="gray").pack(pady=(15, 0))

    def _renderizar_card_ui(self, container, report_id, status, provas, resumo_desc=""):
        card = ctk.CTkFrame(container, fg_color="#1e293b", corner_radius=8)
        card.pack(fill="x", pady=5, padx=6)
        
        status_lower = status.lower()
        if "duplicado" in status_lower:
            cor_status = "#f59e0b"
        elif "hack" in status_lower or "xit" in status_lower:
            cor_status = "#ef4444"
        elif "inválido" in status_lower or "insuficiente" in status_lower:
            cor_status = "#f87171"
        elif "válido" in status_lower:
            cor_status = "#50fa7b" 
        else:
            cor_status = "#ffb86c" 

        top = ctk.CTkFrame(card, fg_color="transparent")
        top.pack(fill="x", padx=10, pady=(8, 4))
        
        ctk.CTkLabel(top, text=f"📄 Report #{report_id}", font=ctk.CTkFont(size=12, weight="bold"), text_color="#f8fafc").pack(side="left")
        ctk.CTkLabel(top, text=status, text_color=cor_status, font=ctk.CTkFont(size=12, weight="bold")).pack(side="right")
        
        motivo_real = resumo_desc if resumo_desc and resumo_desc.strip() not in ["", "Outros/Sem tags"] else "Sem motivo especificado"
        
        conteudo_frame = ctk.CTkFrame(card, fg_color="#0f172a", corner_radius=6)
        conteudo_frame.pack(fill="x", padx=10, pady=(0, 6))

        ctk.CTkLabel(
            conteudo_frame, 
            text=f"📌 {motivo_real}", 
            font=ctk.CTkFont(size=11, weight="bold"), 
            text_color="#cbd5e1", 
            justify="left", 
            wraplength=270
        ).pack(anchor="w", padx=10, pady=(8, 2))
        
        lbl_link = ctk.CTkLabel(
            conteudo_frame, 
            text=f"🔗 {provas}", 
            font=ctk.CTkFont(size=11, underline=True), 
            text_color="#38bdf8", 
            justify="left", 
            wraplength=270, 
            cursor="hand2"
        )
        lbl_link.pack(anchor="w", padx=10, pady=(0, 8))

        def _abrir_link(event, texto):
            import webbrowser
            import re
            match = re.search(r'(https?://\S+|file:///\S+)', texto)
            url_final = match.group(1) if match else texto
            webbrowser.open(url_final)

        lbl_link.bind("<Button-1>", lambda e, t=provas: _abrir_link(e, t))
        
        bottom_frame = ctk.CTkFrame(card, fg_color="transparent", height=30)
        bottom_frame.pack(fill="x", padx=10, pady=(0, 8))

        btn_copiar = ctk.CTkButton(
            bottom_frame, text="📋 Copiar", width=70, height=24, 
            fg_color="#334155", hover_color="#475569", font=ctk.CTkFont(size=11, weight="bold"),
            command=lambda p=provas: self._copiar_para_area_transferencia(p)
        )
        btn_copiar.pack(side="left")

        btn_comentar = ctk.CTkButton(
            bottom_frame, text="💬 Comentar", width=85, height=24, 
            fg_color="#2563eb", hover_color="#1d4ed8", font=ctk.CTkFont(size=11, weight="bold"),
            command=lambda rid=report_id: self._abrir_popup_comentario(rid)
        )
        btn_comentar.pack(side="right", padx=(6, 0))

        def _abrir_report_gc(rid):
            import webbrowser
            url_base = self.config_data.get("url_analisar_template", "https://cx.gamersclub.com.br/admin/toxicidade/analisar/{id}")
            webbrowser.open(url_base.replace("{id}", str(rid)))
            
        btn_abrir_report = ctk.CTkButton(
            bottom_frame, text="👁️ Analisar", width=85, height=24, 
            fg_color="#7c3aed", hover_color="#6d28d9", font=ctk.CTkFont(size=11, weight="bold"),
            command=lambda rid=report_id: _abrir_report_gc(rid)
        )
        btn_abrir_report.pack(side="right")

    def _abrir_painel_config(self):
        win_cfg = ctk.CTkToplevel(self)
        win_cfg.title("Configurações do Sistema")
        win_cfg.geometry("400x480")
        win_cfg.attributes("-topmost", True)

        win_cfg.protocol("WM_DELETE_WINDOW", lambda: [self._salvar_e_aplicar_configs(), win_cfg.destroy()])

        ctk.CTkLabel(win_cfg, text="🎨 Tema", font=ctk.CTkFont(weight="bold")).pack(pady=(12, 2), anchor="w", padx=20)
        ctk.CTkSwitch(win_cfg, text="Modo Claro", variable=self.cfg_tema_claro, command=self._salvar_e_aplicar_configs).pack(padx=35, anchor="w")

        ctk.CTkLabel(win_cfg, text="📝 Histórico em Nuvem", font=ctk.CTkFont(weight="bold")).pack(pady=(12, 2), anchor="w", padx=20)
        ctk.CTkComboBox(win_cfg, variable=self.cfg_salvar_historico, values=["Perguntar sempre", "Sempre salvar", "Nunca salvar"], command=lambda _: self._salvar_e_aplicar_configs(), state="readonly").pack(padx=35, anchor="w")

        ctk.CTkLabel(win_cfg, text="👁️ Personalizar Interface", font=ctk.CTkFont(weight="bold")).pack(pady=(12, 2), anchor="w", padx=20)
        ctk.CTkSwitch(win_cfg, text="Abrir Log", variable=self.cfg_exibir_terminal, command=self._salvar_e_aplicar_configs).pack(pady=2, padx=35, anchor="w")
        ctk.CTkSwitch(win_cfg, text="Exibir Botão Pausar", variable=self.cfg_exibir_btn_pausar, command=self._salvar_e_aplicar_configs).pack(pady=2, padx=35, anchor="w")
        ctk.CTkSwitch(win_cfg, text="Exibir Barra de Progresso", variable=self.cfg_exibir_barra, command=self._salvar_e_aplicar_configs).pack(pady=2, padx=35, anchor="w")

        btn_gerenciar_hist = ctk.CTkButton(
            win_cfg, 
            text="🗑️ Gerenciar / Excluir Registros do Histórico", 
            fg_color="#dc2626", hover_color="#b91c1c",
            height=26, font=ctk.CTkFont(size=11, weight="bold"),
            command=self._abrir_gerenciador_exclusao_historico
        )
        btn_gerenciar_hist.pack(padx=35, pady=(15, 5), anchor="w")

        ctk.CTkFrame(win_cfg, height=2, fg_color="#334155").pack(fill="x", padx=15, pady=(10, 8))
        btn_abrir_sandbox = ctk.CTkButton(
            win_cfg, 
            text="🧪 Entrar na Zona de Teste (Ambiente Seguro)", 
            fg_color="#0284c7", hover_color="#0369a1",
            font=ctk.CTkFont(weight="bold"),
            command=lambda: [win_cfg.destroy(), self._abrir_janela_zona_teste()]
        )
        btn_abrir_sandbox.pack(fill="x", padx=20, pady=(0, 12), side="bottom")

    def _salvar_e_aplicar_configs(self):
        ctk.set_appearance_mode("Light" if self.cfg_tema_claro.get() else "Dark")
        self._atualizar_visibilidade_elementos()
        self._auto_salvar_config()

    def _abrir_painel_massa(self):
        win = ctk.CTkToplevel(self)
        win.title("Invalidação em Massa")
        win.geometry("450x550")
        win.attributes("-topmost", True)
        
        ctk.CTkLabel(win, text="Cole os IDs dos reports (um por linha):", font=ctk.CTkFont(weight="bold")).pack(pady=(15, 5))
        txt_ids = ctk.CTkTextbox(win, width=350, height=250); txt_ids.pack(pady=5)
        
        ctk.CTkLabel(win, text="Motivo:", font=ctk.CTkFont(weight="bold")).pack(pady=(15, 2))
        var_motivo = ctk.StringVar(value="Inválido (Padrão)")
        ctk.CTkComboBox(win, variable=var_motivo, values=["Inválido (Padrão)", "Duplicado", "Sem Provas"], state="readonly", width=350).pack(pady=5)

        def _confirmar():
            ids_limpos = [i.strip() for i in txt_ids.get("1.0", "end").strip().split('\n') if i.strip().isdigit()]
            if ids_limpos and messagebox.askyesno("Confirmação", "Deseja invalidar todos?"):
                win.destroy()
                self._iniciar(lista_massa=ids_limpos, motivo_massa=var_motivo.get())
        ctk.CTkButton(win, text="Invalidar Todos", fg_color="#dc3545", text_color="white", font=ctk.CTkFont(weight="bold"), command=_confirmar).pack(pady=20)

    def _log(self, msg):
        self.txt_log.configure(state="normal")
        tag = "erro" if "❌" in msg else "aviso" if "⚠" in msg else "sucesso" if "✅" in msg else "destaque" if "---" in msg or "===" in msg else "normal"
        self.txt_log.insert("end", f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n", tag)
        self.txt_log.see("end"); self.txt_log.configure(state="disabled")

    def _atualizar_resumo(self):
        nome = self.var_nome.get().strip(); inicial = self.var_inicial.get().strip(); data_str = self.var_data.get().strip()
        validos = sum(1 for r in self.resultados_reports if "válido ✅" in r[1])
        invalidos = sum(1 for r in self.resultados_reports if "inválido ❌" in r[1])
        
        self.texto_para_copiar = ""
        if self.cfg_mostrar_staff.get(): self.texto_para_copiar += f"Staff: {nome} - {inicial}      "
        if self.cfg_mostrar_data.get(): self.texto_para_copiar += f"data: {data_str} - {self.hora_inicio}\n\n"
        if self.cfg_mostrar_total.get(): self.texto_para_copiar += f"Reports: ⚠️ {self.total_encontrados} encontrados, ✅ {validos} válidos, ❌ {invalidos} inválidos\n\n"
        
        if self.resultados_reports and self.cfg_mostrar_id.get():
            self.texto_para_copiar += "Reports:\n"
            for r in self.resultados_reports:
                self.texto_para_copiar += f"° {r[0]} - {r[1]}\n"
                if self.cfg_mostrar_provas.get(): self.texto_para_copiar += f"Provas: {r[2]}\n"
                if r[3]: self.texto_para_copiar += f"Comentário {inicial}: {r[3]}\n"
                self.texto_para_copiar += "\n"

    def _abrir_popup_comentario(self, report_id):
        idx = next((i for i, r in enumerate(self.resultados_reports) if r[0] == report_id), None)
        if idx is None: return

        win = ctk.CTkToplevel(self); win.title(f"Comentário - #{report_id}"); win.geometry("400x200")
        win.attributes("-topmost", True); win.transient(self); win.grab_set()
        
        ctk.CTkLabel(win, text="Digite seu comentário (opcional):").pack(pady=10)
        txt = ctk.CTkTextbox(win, height=80); txt.pack(fill="x", padx=15)
        txt.insert("end", self.resultados_reports[idx][3])
        
        def _salvar(): 
            self.resultados_reports[idx][3] = txt.get("1.0", "end").strip()
            self._atualizar_resumo()
            win.destroy()
            
        ctk.CTkButton(win, text="Salvar Comentário", command=_salvar).pack(pady=10)

    def _mostrar_popup_manual(self, titulo, mensagem, evento, resposta):
        win = ctk.CTkToplevel(self)
        win.title(titulo)
        win.geometry("480x180")
        win.attributes("-topmost", True)
        win.transient(self)
        win.grab_set()

        ctk.CTkLabel(win, text=mensagem, font=ctk.CTkFont(size=14, weight="bold")).pack(pady=(20, 15))

        def _confirmar():
            resposta["ok"] = True
            evento.set()
            win.destroy()

        def _cancelar():
            resposta["ok"] = False
            evento.set()
            win.destroy()

        win.protocol("WM_DELETE_WINDOW", _cancelar)

        btn_frm = ctk.CTkFrame(win, fg_color="transparent")
        btn_frm.pack()
        ctk.CTkButton(btn_frm, text="✅ Confirmar", command=_confirmar, fg_color="#2EA043", hover_color="#238636").pack(side="left", padx=10)
        ctk.CTkButton(btn_frm, text="❌ Parar Bot", command=_cancelar, fg_color="#DA3633", hover_color="#B62324").pack(side="left", padx=10)

    def _copiar_resumo(self):
        if not hasattr(self, "resultados_reports") or not self.resultados_reports:
            self._log("⚠️ Nenhum report processado para copiar resumo.")
            return

        texto_final = f"📋 RESUMO DE TRIAGEM - GC\nStaff: {self.var_nome.get()} | Data: {self.var_data.get()}\n"
        texto_final += "-" * 40 + "\n"

        for r in self.resultados_reports:
            texto_final += f"• Report #{r['id']}: {r['status']}\n  Provas: {r['prova']}\n\n"

        self.clipboard_clear()
        self.clipboard_append(texto_final)
        self._log("📋 Resumo copiado para a área de transferência com sucesso!")

    def _salvar_resumo_txt(self):
        texto = getattr(self, 'texto_para_copiar', "").strip()
        if not texto: return
        nome = self.var_nome.get().strip() or "Staff"
        
        os.makedirs(os.path.join(pasta_do_exe(), "resumos"), exist_ok=True)
        caminho = os.path.join(pasta_do_exe(), "resumos", f"resumo_{nome}_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.txt")
        try:
            with open(caminho, "w", encoding="utf-8") as f: f.write(texto)
            self._log(f"💾 Resumo txt salvo em: {caminho}")
        except Exception: pass

    def _iniciar(self, lista_massa=None, motivo_massa="Inválido (Padrão)"):
        nome = self.var_nome.get().strip()
        inicial = self.var_inicial.get().strip()
        modo = self.var_modo.get()

        if not nome or not inicial:
            messagebox.showwarning("Aviso", "Por favor, preencha seu Nome e Inicial do Staff antes de iniciar!")
            return

        try:
            salvar_preferencias_usuario(
                nome,
                inicial,
                modo,
                exibir_terminal=self.cfg_exibir_terminal.get(),
                exibir_pausar=self.cfg_exibir_btn_pausar.get(),
                exibir_barra=self.cfg_exibir_barra.get(),
                tema_claro=self.cfg_tema_claro.get(),
                historico_nuvem=self.cfg_salvar_historico.get()
            )
        except Exception as e:
            print(f"Erro ao salvar preferências: {e}")

        self.btn_iniciar.configure(state="disabled")
        self.btn_pausar.configure(state="normal")
        self.btn_parar.configure(state="normal")

        qtd_val = int(self.var_quantidade.get().strip()) if self.var_quantidade.get().strip().isdigit() else None
        
        try:
            self.worker = BotWorker(
                self.config_data, nome, inicial,
                self.var_data.get().strip(), self.var_navegador.get(),
                "auto" in modo.lower(), qtd_val, self.fila,
                headless=self.cfg_modo_fantasma.get(), zona_teste=False,
                lista_massa=lista_massa, motivo_massa=motivo_massa
            )
            self.worker.start()
        except Exception as err:
            messagebox.showerror("Erro de Inicialização", f"Não foi possível iniciar o bot:\n{err}")
            self.btn_iniciar.configure(state="normal")
            self.btn_pausar.configure(state="disabled")
            self.btn_parar.configure(state="disabled")

    def _abrir_gerenciador_exclusao_historico(self):
        win_exc = ctk.CTkToplevel(self)
        win_exc.title("Excluir Histórico por Dia")
        win_exc.geometry("520x450")
        win_exc.attributes("-topmost", True)

        ctk.CTkLabel(win_exc, text="🗑️ Gerenciador do Histórico em Nuvem", font=ctk.CTkFont(size=16, weight="bold")).pack(pady=10)
        ctk.CTkLabel(win_exc, text="Clique no (❌) do dia para removê-lo permanentemente:", font=ctk.CTkFont(size=11), text_color="gray").pack(pady=(0, 10))

        scroll = ctk.CTkScrollableFrame(win_exc)
        scroll.pack(fill="both", expand=True, padx=15, pady=(0, 15))

        dados = ler_historico_firebase() or {}
        
        if not dados:
            ctk.CTkLabel(scroll, text="Nenhum histórico encontrado no Firebase.").pack(pady=20)
            return

        for key_id, reg in list(dados.items())[::-1]:
            card = ctk.CTkFrame(scroll, fg_color="#2b2b2b")
            card.pack(fill="x", pady=4, padx=5)

            total_reps = len(reg.get('reports', []))
            lbl_info = f"📅 Data: {reg.get('data_triagem', 'S/D')} | Staff: {reg.get('staff', 'S/N')} | {total_reps} reports"
            ctk.CTkLabel(card, text=lbl_info, font=ctk.CTkFont(size=12, weight="bold")).pack(side="left", padx=10, pady=8)

            btn_del = ctk.CTkButton(
                card, text="❌", width=35, height=26, 
                fg_color="#ef4444", hover_color="#991b1b",
                font=ctk.CTkFont(weight="bold"),
                command=lambda k=key_id, c=card: self._confirmar_exclusao_firebase(k, c)
            )
            btn_del.pack(side="right", padx=10)

    def _confirmar_exclusao_firebase(self, key_firebase, card_widget):
        if not FIREBASE_URL:
            return
        try:
            url = f"{FIREBASE_URL}/historico/{key_firebase}.json"
            requests.delete(url, timeout=5)
            card_widget.destroy()
            self._log("🗑️ Registro removido do Firebase com sucesso!")
        except Exception as e:
            self._log(f"❌ Erro ao excluir registro do Firebase: {e}")

    def _parar(self):
        if self.worker: self.worker.parar()
        self.btn_parar.configure(state="disabled"); self.btn_pausar.configure(state="disabled")

    def _finalizar_com_historico(self, processados, encontrados):
        if encontrados == 0: return

        modo_str = "Automático (Rápido) 🟢" if self.var_modo.get().startswith("auto") else "Teste (Manual) 🟠"
        
        detalhes_reports = []
        for r in self.resultados_reports:
            detalhes_reports.append({
                "id": r[0],
                "status": r[1],
                "prova": r[2],
                "comentario": r[3],
                "resumo_desc": r[4] if len(r) > 4 else ""
            })

        dados = {
            "data_execucao": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "data_triagem": self.var_data.get().strip(),
            "staff": f"{self.var_nome.get().strip()} ({self.var_inicial.get().strip()})",
            "encontrados": encontrados,
            "processados": processados,
            "modo": modo_str,
            "reports": detalhes_reports
        }
        
        pref = self.cfg_salvar_historico.get()
        if pref == "Nunca salvar": return
        if pref == "Perguntar sempre":
            self.lift(); self.attributes("-topmost", True); self.attributes("-topmost", False)
            if not messagebox.askyesno("Histórico", "Deseja salvar esta triagem no Histórico da Nuvem?", parent=self): return
            
        threading.Thread(target=salvar_historico_firebase, args=(dados,), daemon=True).start()
        self._log("☁️ Histórico completo enviado para a nuvem!")

    def _poll_fila(self):
        try:
            while True:
                ev = self.fila.get_nowait()
                if ev[0] == "log": self._log(ev[1])
                elif ev[0] == "contador":
                    self.lbl_contador.configure(text=f"Processados: {ev[1]} / {self.total_encontrados}")
                    if self.total_encontrados > 0: self.progress_bar.set(ev[1] / self.total_encontrados)
                elif ev[0] == "total_encontrado":
                    self.total_encontrados = ev[1]
                elif ev[0] == "resultado": 
                    report_id = ev[1]
                    status = ev[2]
                    provas = ev[3]
                    resumo_desc = ev[4] if len(ev) > 4 else ""
                    
                    self.resultados_reports.append([report_id, status, provas, "", resumo_desc])
                    self._atualizar_resumo()
                    
                    self._renderizar_card_ui(self.scroll_resumo, report_id, status, provas, resumo_desc)

                    st_lower = status.lower()
                    if "inválido" in st_lower or "hack" in st_lower or "duplicado" in st_lower:
                        self._renderizar_card_ui(self.scroll_tab_invalidos, report_id, status, provas, resumo_desc)
                    elif "válido" in st_lower:
                        self._renderizar_card_ui(self.scroll_tab_validos, report_id, status, provas, resumo_desc)
                    else:
                        self._renderizar_card_ui(self.scroll_tab_revisao, report_id, status, provas, resumo_desc)
                elif ev[0] == "notificar": disparar_notificacao(ev[1], ev[2])
                
                elif ev[0] == "pedir_login": 
                    self.lift(); self.attributes("-topmost", True); self.attributes("-topmost", False)
                    self._mostrar_popup_manual(
                        "Login Necessário", 
                        "Faça login no painel da GC no navegador.\nClique em Confirmar APENAS APÓS carregar inteiro.", 
                        ev[1], ev[2]
                    )
                elif ev[0] == "pedir_ok_manual": 
                    self.lift(); self.attributes("-topmost", True); self.attributes("-topmost", False)
                    self._mostrar_popup_manual(
                        "Ação Manual (Modo Teste)", 
                        f"1. Clique em 'Notificar' no navegador para o report #{ev[1]}.\n2. Aguarde a página parar de carregar.\n3. SÓ ENTÃO clique em Confirmar abaixo.", 
                        ev[2], ev[3]
                    )
                
                elif ev[0] == "fim":
                    self._log(f"--- Sessão encerrada ---")
                    self._finalizar_com_historico(ev[1], ev[2]) 
                    self._salvar_resumo_txt() 
                    self.btn_iniciar.configure(state="normal"); self.btn_parar.configure(state="disabled"); self.btn_pausar.configure(state="disabled")
        except queue.Empty: pass
        self.after(150, self._poll_fila)

if __name__ == "__main__":
    app = App()
    app.mainloop()