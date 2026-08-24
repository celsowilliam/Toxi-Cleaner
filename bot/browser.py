"""
Abre o navegador escolhido pelo usuário usando um PERFIL PRÓPRIO do bot.
Isso é o que faz o login "ficar salvo": na primeira vez você loga manualmente
na tela que abrir, e nas próximas execuções os cookies já estão lá.

Não usamos o perfil "normal" do seu navegador do dia a dia de propósito -
assim o bot não mexe nas suas outras abas/senhas, e a equipe toda pode ter
seu próprio browser_profile local sem conflito.
"""
import os
import sys
from selenium import webdriver
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.firefox.options import Options as FirefoxOptions


def _base_dir():
    """Funciona tanto rodando o .py quanto rodando o .exe empacotado (PyInstaller)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _profile_path(config):
    path = os.path.join(_base_dir(), config["pasta_perfil_navegador"])
    os.makedirs(path, exist_ok=True)
    return path


def abrir_navegador(navegador: str, config: dict):
    """
    navegador: "edge", "chrome" ou "firefox"
    Retorna um driver Selenium já aberto, com perfil persistente configurado.

    Selenium Manager (embutido no Selenium >= 4.6) baixa sozinho o driver
    certo (msedgedriver / chromedriver / geckodriver) na primeira vez que
    for preciso - por isso ninguém da equipe precisa instalar nada manualmente,
    só precisa ter o navegador em si já instalado no Windows (Edge já vem).
    """
    navegador = navegador.lower().strip()
    perfil = _profile_path(config)

    if navegador == "edge":
        opts = EdgeOptions()
        opts.add_argument(f"--user-data-dir={perfil}")
        opts.add_argument("--profile-directory=Default")
        driver = webdriver.Edge(options=opts)

    elif navegador == "chrome":
        opts = ChromeOptions()
        opts.add_argument(f"--user-data-dir={perfil}")
        opts.add_argument("--profile-directory=Default")
        driver = webdriver.Chrome(options=opts)

    elif navegador == "firefox":
        opts = FirefoxOptions()
        opts.add_argument("-profile")
        opts.add_argument(perfil)
        driver = webdriver.Firefox(options=opts)

    else:
        raise ValueError(f"Navegador não suportado: {navegador}")

    driver.maximize_window()
    return driver
