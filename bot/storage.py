"""
Guarda, dentro da pasta do próprio projeto (logs/processed_reports.csv), cada
report que o bot processou: número do report (o # que aparece na listagem
de pendentes), data, resultado, staff responsável e horário.

Isso serve tanto de histórico/auditoria quanto de contador (basta contar as
linhas do CSV, ou filtrar por staff/data).
"""
import os
import sys
import csv
from datetime import datetime


def _base_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _log_path(config):
    path = os.path.join(_base_dir(), config["arquivo_log_csv"])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


CAMPOS = ["timestamp", "report_numero", "data_report", "staff", "resultado", "motivo", "links_encontrados"]


def garantir_arquivo(config):
    path = _log_path(config)
    if not os.path.exists(path):
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=CAMPOS)
            writer.writeheader()
    return path


def registrar(config, report_numero, data_report, staff, resultado, motivo, links_encontrados):
    path = garantir_arquivo(config)
    with open(path, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CAMPOS)
        writer.writerow({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "report_numero": report_numero,
            "data_report": data_report,
            "staff": staff,
            "resultado": resultado,
            "motivo": motivo,
            "links_encontrados": " | ".join(links_encontrados) if links_encontrados else "",
        })


def contar_processados(config, staff=None):
    path = garantir_arquivo(config)
    total = 0
    with open(path, "r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if staff is None or row.get("staff") == staff:
                total += 1
    return total
