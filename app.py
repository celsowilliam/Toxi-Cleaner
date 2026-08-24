"""
GC - ToxiCleaner (Bot de Triagem de Toxicidade)
Painel gráfico moderno (CustomTkinter) para configurar e rodar o bot.
"""
import os
import sys
import json
import queue
import threading
from datetime import datetime

import customtkinter as ctk
from tkinter import messagebox

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bot import browser, scraper, evidence, actions, storage

# --- FUNÇÕES DE CONFIGURAÇÃO ---

def base_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def carregar_config():
    with open(os.path.join(base_dir(), "config.json"), "r", encoding="utf-8") as f:
        return json.load(f)

# --- WORKER DO BOT (LÓGICA) ---

class BotWorker(threading.Thread):
    def __init__(self, config, staff_nome, staff_inicial, data_str, navegador,
                 modo_automatico, quantidade_maxima, fila_eventos, lista_ids_forcados=None, motivo_massa="Inválido"):
        super().__init__(daemon=True)
        self.config = config
        self.staff_nome = staff_nome
        self.staff_inicial = staff_inicial
        self.data_str = data_str
        self.navegador = navegador
        self.modo_automatico = modo_automatico
        self.quantidade_maxima = quantidade_maxima
        self.fila = fila_eventos
        self.lista_ids_forcados = lista_ids_forcados
        self.motivo_massa = motivo_massa
        self._parar = threading.Event()

    def parar(self):
        self._parar.set()

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
        try:
            self.log(f"Abrindo {self.navegador}... (se for a 1ª vez, faça login manualmente na aba que abrir)")
            driver = browser.abrir_navegador(self.navegador, self.config)

            self.log("Verificando se já está logado...")
            if not scraper.esta_logado(driver, self.config, timeout=6):
                self.log("⚠ Ainda não está logado (ou a página está lenta). Aguardando confirmação...")
                ok = self.pedir_login_manual()
                if not ok:
                    self.log("Login não confirmado pelo usuário. Encerrando.")
                    self.fila.put(("fim", 0))
                    return

            # --- LÓGICA DE INVALÍDAÇÃO EM MASSA ---
            if self.lista_ids_forcados:
                self.log(f"Modo Invalidação em Massa ativado: {len(self.lista_ids_forcados)} reports fornecidos.")
                reports = self.lista_ids_forcados
            # --- LÓGICA PADRÃO DE TRIAGEM ---
            else:
                self.log("Indo para a lista de reports pendentes...")
                scraper.ir_para_pendentes(driver, self.config)

                self.log(f"Procurando reports do dia {self.data_str}...")
                reports, diagnostico = scraper.listar_reports_do_dia(driver, self.data_str)

                if not reports:
                    self.log(f"⚠ Nenhum report encontrado para a data {self.data_str}. Confira se a data está correta ou se já foi tudo limpo.")
                    self.fila.put(("fim", 0))
                    return

                self.log(f"Encontrados {len(reports)} report(s) no dia {self.data_str}.")
                
                if self.quantidade_maxima:
                    if len(reports) > self.quantidade_maxima:
                        self.log(f"🔒 Limitando a {self.quantidade_maxima} report(s), como configurado (teste seguro) - existem {len(reports)} no total desse dia.")
                    reports = reports[: self.quantidade_maxima]

            self.fila.put(("total_encontrado", len(reports)))
            total_processados = 0

            for numero in reports:
                if self._parar.is_set():
                    self.log("Parado pelo usuário.")
                    break

                self.log(f"--- Abrindo report #{numero} ---")

                try:
                    scraper.abrir_report_por_id(driver, self.config, numero)
                    
                    if self.lista_ids_forcados:
                        # Se for em massa, nem perdemos tempo lendo provas
                        dados = {"texto_provas": f"Invalidação forçada - Motivo: {self.motivo_massa}"}
                        resultado = {"status": "invalido", "motivo": f"Invalidação em massa"}
                    else:
                        dados = scraper.ler_report_atual(driver, report_id=numero)
                        resultado = evidence.classificar_provas(
                            dados["texto_provas"],
                            self.config["whitelist_dominios"],
                            self.config["blacklist_padroes"],
                        )
                except Exception as e:
                    self.log(f"❌ Erro ao abrir/ler report #{numero}: {e}")
                    if not self.lista_ids_forcados:
                        scraper.ir_para_pendentes(driver, self.config)
                    continue

                texto_provas_bruto = dados.get('texto_provas', "Nenhuma prova informada")
                if not self.lista_ids_forcados:
                    self.log(f"🔎 Provas (bruto): {texto_provas_bruto!r}")

                if resultado["status"] == "invalido":
                    self.log(f"Report #{numero}: SEM PROVA VÁLIDA -> vou marcar como Inválido.")
                    try:
                        # Adapta a inicial se for massa com motivo específico
                        inicial_usada = self.staff_inicial
                        if self.lista_ids_forcados and self.motivo_massa != "Inválido (Padrão)":
                            inicial_usada = f"{self.staff_inicial} - {self.motivo_massa}"

                        estado = actions.marcar_como_invalido(
                            driver, self.config, inicial_usada, self.modo_automatico,
                            callback_aguardar_manual=lambda rid=numero: self.pedir_ok_manual(rid),
                        )
                        self.log(f"Report #{numero}: {estado}")
                        storage.registrar(self.config, numero, self.data_str, self.staff_nome, "invalido", resultado["motivo"], resultado.get("links", []))
                        total_processados += 1
                    except Exception as e:
                        self.log(f"❌ Erro ao aplicar ações no report #{numero}: {e}")
                    
                    self.fila.put(("resultado", numero, "inválido ❌", texto_provas_bruto))

                elif resultado["status"] == "valido":
                    self.log(f"Report #{numero}: possui link de prova reconhecido -> PULANDO (revisão humana).")
                    storage.registrar(self.config, numero, self.data_str, self.staff_nome, "revisao_manual_valido", resultado["motivo"], resultado.get("links", []))
                    self.fila.put(("resultado", numero, "válido ✅", texto_provas_bruto))

                else:
                    self.log(f"Report #{numero}: link não reconhecido -> PULANDO (revisão manual).")
                    storage.registrar(self.config, numero, self.data_str, self.staff_nome, "revisao_manual_ambiguo", resultado["motivo"], resultado.get("links", []))
                    self.fila.put(("resultado", numero, "revisão manual ⚠️", texto_provas_bruto))

                self.fila.put(("contador", total_processados))
                
                if not self.lista_ids_forcados:
                    scraper.ir_para_pendentes(driver, self.config)

            self.log(f"✅ Finalizado. Total processado nesta execução: {total_processados}")
            self.fila.put(("fim", total_processados))

        except Exception as e:
            self.log(f"❌ Erro inesperado: {e}")
            self.fila.put(("fim", 0))
        finally:
            if driver is not None:
                try:
                    self.log("Fechando o navegador...")
                    driver.quit()
                except Exception:
                    pass


# --- INTERFACE GRÁFICA (UI) ---

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("GC - ToxiCleaner (Bot de Triagem de Toxicidade)")
        self.geometry("1150x700")
        self.config_data = carregar_config()
        self.fila = queue.Queue()
        self.worker = None

        self.resultados_reports = []
        self.total_encontrados = 0
        self.hora_inicio = ""

        self._montar_ui()
        self.after(150, self._poll_fila)

    def _montar_ui(self):
        # 1. CABEÇALHO MODERNO
        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.pack(fill="x", padx=15, pady=(15, 5))
        
        lbl_titulo = ctk.CTkLabel(header_frame, text="ToxiCleaner Dashboard", font=ctk.CTkFont(size=24, weight="bold"))
        lbl_titulo.pack(side="left")

        # Botão na direita superior!
        self.btn_massa = ctk.CTkButton(header_frame, text="💣 Invalidação em Massa", command=self._abrir_painel_massa, fg_color="#ff9800", hover_color="#f57c00", font=ctk.CTkFont(weight="bold"))
        self.btn_massa.pack(side="right")

        # 2. ÁREA DE CONFIGURAÇÕES (Duas Colunas)
        settings_frame = ctk.CTkFrame(self)
        settings_frame.pack(fill="x", padx=15, pady=10)
        settings_frame.columnconfigure(0, weight=1)
        settings_frame.columnconfigure(1, weight=1)

        # Coluna Esquerda: Identificação
        frm_esq = ctk.CTkFrame(settings_frame, fg_color="transparent")
        frm_esq.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        
        ctk.CTkLabel(frm_esq, text="👤 Identificação do Staff", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", pady=(0, 10))
        
        row1 = ctk.CTkFrame(frm_esq, fg_color="transparent")
        row1.pack(fill="x", pady=2)
        ctk.CTkLabel(row1, text="Nome:").pack(side="left")
        self.var_nome = ctk.StringVar()
        ctk.CTkEntry(row1, textvariable=self.var_nome, width=200).pack(side="right")

        row2 = ctk.CTkFrame(frm_esq, fg_color="transparent")
        row2.pack(fill="x", pady=2)
        ctk.CTkLabel(row2, text="Inicial:").pack(side="left")
        self.var_inicial = ctk.StringVar()
        ctk.CTkEntry(row2, textvariable=self.var_inicial, width=200).pack(side="right")

        row3 = ctk.CTkFrame(frm_esq, fg_color="transparent")
        row3.pack(fill="x", pady=2)
        ctk.CTkLabel(row3, text="Data a limpar:").pack(side="left")
        self.var_data = ctk.StringVar(value=datetime.now().strftime("%d/%m/%Y"))
        ctk.CTkEntry(row3, textvariable=self.var_data, width=200).pack(side="right")

        # Coluna Direita: Configurações do Bot
        frm_dir = ctk.CTkFrame(settings_frame, fg_color="transparent")
        frm_dir.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)

        ctk.CTkLabel(frm_dir, text="⚙️ Configurações do Bot", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", pady=(0, 10))

        row4 = ctk.CTkFrame(frm_dir, fg_color="transparent")
        row4.pack(fill="x", pady=2)
        ctk.CTkLabel(row4, text="Navegador:").pack(side="left")
        self.var_navegador = ctk.StringVar(value="edge")
        ctk.CTkComboBox(row4, variable=self.var_navegador, values=["edge", "chrome", "firefox"], state="readonly", width=200).pack(side="right")

        row5 = ctk.CTkFrame(frm_dir, fg_color="transparent")
        row5.pack(fill="x", pady=2)
        ctk.CTkLabel(row5, text="Modo:").pack(side="left")
        self.var_modo = ctk.StringVar(value="teste")
        ctk.CTkComboBox(row5, variable=self.var_modo, values=["teste (clico em Notificar)", "automatico (clica sozinho)"], state="readonly", width=200).pack(side="right")

        row6 = ctk.CTkFrame(frm_dir, fg_color="transparent")
        row6.pack(fill="x", pady=2)
        ctk.CTkLabel(row6, text="Qtde (vazio=todos):").pack(side="left")
        self.var_quantidade = ctk.StringVar(value="")
        ctk.CTkEntry(row6, textvariable=self.var_quantidade, width=200).pack(side="right")

        # 3. BOTÕES DE AÇÃO PRINCIPAIS
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=15, pady=0)
        self.btn_iniciar = ctk.CTkButton(btn_frame, text="▶ Iniciar Triagem", command=self._iniciar, fg_color="#28a745", hover_color="#218838", font=ctk.CTkFont(weight="bold"))
        self.btn_iniciar.pack(side="left", padx=(0, 10))
        
        self.btn_parar = ctk.CTkButton(btn_frame, text="■ Parar", command=self._parar, state="disabled", fg_color="#dc3545", hover_color="#c82333", font=ctk.CTkFont(weight="bold"))
        self.btn_parar.pack(side="left")

        self.lbl_contador = ctk.CTkLabel(self, text="Reports processados nesta sessão: 0", font=ctk.CTkFont(weight="bold"))
        self.lbl_contador.pack(anchor="w", padx=15, pady=(15,5))

        # 4. ÁREA DE LOGS E RESUMO
        bottom_frame = ctk.CTkFrame(self, fg_color="transparent")
        bottom_frame.pack(fill="both", expand=True, padx=15, pady=(0, 15))
        bottom_frame.columnconfigure(0, weight=6)
        bottom_frame.columnconfigure(1, weight=4)
        bottom_frame.rowconfigure(0, weight=1)

        self.txt_log = ctk.CTkTextbox(bottom_frame, state="disabled", wrap="word", font=ctk.CTkFont(family="Consolas", size=12))
        self.txt_log.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        
        self.txt_log.tag_config("erro", foreground="#ff5555")
        self.txt_log.tag_config("aviso", foreground="#ffb86c")
        self.txt_log.tag_config("sucesso", foreground="#50fa7b")
        self.txt_log.tag_config("destaque", foreground="#8be9fd")
        self.txt_log.tag_config("normal", foreground="#cccccc")

        resumo_frame = ctk.CTkFrame(bottom_frame, fg_color="transparent")
        resumo_frame.grid(row=0, column=1, sticky="nsew")
        resumo_frame.rowconfigure(0, weight=1)
        resumo_frame.columnconfigure(0, weight=1)

        self.txt_resumo = ctk.CTkTextbox(resumo_frame, state="disabled", wrap="word", font=ctk.CTkFont(family="Consolas", size=13))
        self.txt_resumo.grid(row=0, column=0, sticky="nsew", pady=(0, 10))

        self.btn_copiar = ctk.CTkButton(resumo_frame, text="📋 Copiar Resumo", command=self._copiar_resumo, fg_color="#0078D7", hover_color="#005A9E", font=ctk.CTkFont(weight="bold"))
        self.btn_copiar.grid(row=1, column=0, sticky="ew")

    # --- PAINEL DE INVALÍDAÇÃO EM MASSA ATUALIZADO ---
    def _abrir_painel_massa(self):
        nome = self.var_nome.get().strip()
        inicial = self.var_inicial.get().strip()
        
        if not nome or not inicial:
            messagebox.showwarning("Falta informação", "Preencha o seu nome e inicial no painel principal primeiro para usar essa função.")
            return

        win = ctk.CTkToplevel(self)
        win.title("Invalidação em Massa")
        win.geometry("450x550")
        win.attributes("-topmost", True)
        
        ctk.CTkLabel(win, text="Cole os IDs dos reports (um por linha):", font=ctk.CTkFont(weight="bold")).pack(pady=(15, 5))
        
        txt_ids = ctk.CTkTextbox(win, width=350, height=250)
        txt_ids.pack(pady=5)
        
        # --- NOVO: Motivo da Invalidação ---
        ctk.CTkLabel(win, text="Motivo da Invalidação:", font=ctk.CTkFont(weight="bold")).pack(pady=(15, 2))
        var_motivo = ctk.StringVar(value="Inválido (Padrão)")
        cb_motivo = ctk.CTkComboBox(win, variable=var_motivo, values=["Inválido (Padrão)", "Duplicado", "Sem Provas"], state="readonly", width=350)
        cb_motivo.pack(pady=5)

        def _confirmar():
            texto = txt_ids.get("1.0", "end").strip()
            if not texto:
                return
                
            ids_brutos = texto.split('\n')
            ids_limpos = [i.strip() for i in ids_brutos if i.strip().isdigit()]
            
            if not ids_limpos:
                messagebox.showwarning("Aviso", "Nenhum ID numérico válido foi encontrado no texto.")
                return
            
            motivo_escolhido = var_motivo.get()
            
            # --- NOVO: Confirmação só aparece depois de checar os dados ---
            resposta = messagebox.askyesno("Confirmação", "Tem certeza que deseja invalidar todos esses reports pae?")
            
            if resposta:
                win.destroy()
                self._iniciar_massa(ids_limpos, motivo_escolhido)
            else:
                win.destroy()

        btn_confirmar = ctk.CTkButton(win, text="Invalidar Todos", fg_color="#dc3545", hover_color="#c82333", font=ctk.CTkFont(weight="bold"), command=_confirmar)
        btn_confirmar.pack(pady=20)

    def _iniciar_massa(self, lista_ids, motivo):
        nome = self.var_nome.get().strip()
        inicial = self.var_inicial.get().strip()
        navegador = self.var_navegador.get()
        data_str = self.var_data.get().strip()

        self.btn_iniciar.configure(state="disabled")
        self.btn_massa.configure(state="disabled")
        self.btn_parar.configure(state="normal")
        
        self.resultados_reports = []
        self.total_encontrados = len(lista_ids)
        self.hora_inicio = datetime.now().strftime("%H:%M")
        self._atualizar_resumo()

        self._log(f"=== Iniciando INVALÍDAÇÃO EM MASSA: staff={nome} ({inicial}) | motivo={motivo} ===")
        self._log(f"📋 IDs carregados: {', '.join(lista_ids)}")

        self.worker = BotWorker(self.config_data, nome, inicial, data_str, navegador, True, None, self.fila, lista_ids_forcados=lista_ids, motivo_massa=motivo)
        self.worker.start()

    def _log(self, msg):
        self.txt_log.configure(state="normal")
        hora = datetime.now().strftime("%H:%M:%S")
        linha_completa = f"[{hora}] {msg}\n"
        
        tag = "normal"
        if "❌" in msg or "Erro" in msg:
            tag = "erro"
        elif "⚠" in msg or "Atenção" in msg:
            tag = "aviso"
        elif "✅" in msg or "Finalizado" in msg:
            tag = "sucesso"
        elif "--- Abrindo report" in msg or "===" in msg:
            tag = "destaque"

        self.txt_log.insert("end", linha_completa, tag)
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    def _atualizar_resumo(self):
        nome = self.var_nome.get().strip()
        inicial = self.var_inicial.get().strip()
        data_str = self.var_data.get().strip()

        validos = sum(1 for r in self.resultados_reports if "válido ✅" in r[1])
        invalidos = sum(1 for r in self.resultados_reports if "inválido ❌" in r[1])
        
        texto = f"Staff: {nome} - {inicial}      data: {data_str} - {self.hora_inicio}\n\n"
        texto += f"Reports: ⚠️ {self.total_encontrados} reports, ✅ {validos} válidos e ❌ {invalidos} inválidos\n\n"
        texto += "Reports:\n"

        for r_id, status, provas in self.resultados_reports:
            texto += f"° {r_id} - {status}\nProvas: {provas}\n\n"

        self.txt_resumo.configure(state="normal")
        self.txt_resumo.delete("1.0", "end")
        self.txt_resumo.insert("end", texto)
        self.txt_resumo.see("end")
        self.txt_resumo.configure(state="disabled")

    def _copiar_resumo(self):
        texto = self.txt_resumo.get("1.0", "end-1c")
        if texto.strip():
            self.clipboard_clear()
            self.clipboard_append(texto)
            self.btn_copiar.configure(text="✅ Copiado!")
            self.after(2000, lambda: self.btn_copiar.configure(text="📋 Copiar Resumo"))

    def _salvar_resumo_txt(self):
        texto = self.txt_resumo.get("1.0", "end-1c").strip()
        if not texto:
            return
        
        nome = self.var_nome.get().strip() or "Staff"
        data_arquivo = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        pasta_resumos = os.path.join(base_dir(), "resumos")
        
        os.makedirs(pasta_resumos, exist_ok=True)
        caminho = os.path.join(pasta_resumos, f"resumo_{nome}_{data_arquivo}.txt")
        
        try:
            with open(caminho, "w", encoding="utf-8") as f:
                f.write(texto)
            self._log(f"💾 Resumo salvo automaticamente em: {caminho}")
        except Exception as e:
            self._log(f"❌ Erro ao salvar o txt: {e}")

    def _validar_data(self, data_str):
        try:
            datetime.strptime(data_str, "%d/%m/%Y")
            return True
        except ValueError:
            return False

    def _iniciar(self):
        nome = self.var_nome.get().strip()
        inicial = self.var_inicial.get().strip()
        data_str = self.var_data.get().strip()
        navegador = self.var_navegador.get()
        modo_automatico = self.var_modo.get().startswith("automatico")
        quantidade_texto = self.var_quantidade.get().strip()

        if not nome or not inicial or not self._validar_data(data_str):
            messagebox.showwarning("Falta informação", "Preencha o nome, inicial e data corretamente.")
            return

        quantidade_maxima = None
        if quantidade_texto:
            if not quantidade_texto.isdigit() or int(quantidade_texto) <= 0:
                messagebox.showerror("Quantidade inválida", "Digite um número inteiro.")
                return
            quantidade_maxima = int(quantidade_texto)

        self.btn_iniciar.configure(state="disabled")
        self.btn_massa.configure(state="disabled")
        self.btn_parar.configure(state="normal")
        
        self.resultados_reports = []
        self.total_encontrados = 0
        self.hora_inicio = datetime.now().strftime("%H:%M")
        self._atualizar_resumo()

        self._log(f"=== Iniciando: staff={nome} ({inicial}) | data={data_str} | navegador={navegador} ===")

        self.worker = BotWorker(self.config_data, nome, inicial, data_str, navegador, modo_automatico, quantidade_maxima, self.fila)
        self.worker.start()

    def _parar(self):
        if self.worker:
            self.worker.parar()
        self.btn_parar.configure(state="disabled")

    def _poll_fila(self):
        try:
            while True:
                evento = self.fila.get_nowait()
                tipo = evento[0]

                if tipo == "log":
                    self._log(evento[1])
                elif tipo == "contador":
                    self.lbl_contador.configure(text=f"Reports processados nesta sessão: {evento[1]}")
                elif tipo == "total_encontrado":
                    self.total_encontrados = evento[1]
                    self._atualizar_resumo()
                elif tipo == "resultado":
                    self.resultados_reports.append((evento[1], evento[2], evento[3]))
                    self._atualizar_resumo()
                elif tipo == "pedir_login":
                    _, ev, resposta = evento
                    resposta["ok"] = messagebox.askokcancel("Login necessário", "Faça login no painel e clique em OK para continuar.")
                    ev.set()
                elif tipo == "pedir_ok_manual":
                    _, report_id, ev, resposta = evento
                    resposta["ok"] = messagebox.askokcancel("Confirmação", f"Notifique o report #{report_id} no navegador e clique OK.")
                    ev.set()
                elif tipo == "fim":
                    self._log(f"--- Sessão encerrada. Total processado: {evento[1]} ---")
                    self._salvar_resumo_txt()
                    self.btn_iniciar.configure(state="normal")
                    self.btn_massa.configure(state="normal")
                    self.btn_parar.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(150, self._poll_fila)

if __name__ == "__main__":
    app = App()
    app.mainloop()