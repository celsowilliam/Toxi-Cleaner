"""
Decide se o campo "Provas" de um report é:
  - "invalido"  -> sem link nenhum, ou só link(s) da blacklist (ex: só link
                   da partida/perfil da própria GamersClub, ou google.com)
  - "valido"    -> tem pelo menos um link de domínio conhecido de vídeo/print/áudio
  - "ambiguo"   -> tem link(s), mas nenhum bate com whitelist nem blacklist
                   (nesse caso o bot NUNCA decide sozinho, sempre pula o report
                   e marca para revisão manual)

Importante: a regra é sobre o texto do campo "Provas", não sobre o campo
"Link da Partida" (que é outro campo, separado, e nunca conta como prova).
"""
import re

URL_REGEX = re.compile(r"https?://[^\s)\]\"'>]+", re.IGNORECASE)


def extrair_links(texto_provas: str):
    if not texto_provas:
        return []
    return URL_REGEX.findall(texto_provas)


def classificar_provas(texto_provas: str, whitelist_dominios, blacklist_padroes):
    links = extrair_links(texto_provas)

    if not links:
        return {"status": "invalido", "motivo": "Nenhum link encontrado no campo Provas.", "links": []}

    tem_link_whitelist = False
    tem_link_desconhecido = False
    detalhes = []

    for link in links:
        link_lower = link.lower()

        eh_blacklist = any(padrao.lower() in link_lower for padrao in blacklist_padroes)
        eh_whitelist = any(dominio.lower() in link_lower for dominio in whitelist_dominios)

        if eh_whitelist:
            tem_link_whitelist = True
            detalhes.append(f"{link} -> reconhecido como prova válida")
        elif eh_blacklist:
            detalhes.append(f"{link} -> reconhecido como não-prova (blacklist)")
        else:
            tem_link_desconhecido = True
            detalhes.append(f"{link} -> domínio desconhecido, precisa revisão manual")

    if tem_link_whitelist:
        return {
            "status": "valido",
            "motivo": "Contém link de evidência reconhecido.",
            "links": links,
            "detalhes": detalhes,
        }

    if tem_link_desconhecido:
        return {
            "status": "ambiguo",
            "motivo": "Contém link(s) em domínio não configurado. Revisão manual necessária.",
            "links": links,
            "detalhes": detalhes,
        }

    # todos os links encontrados batem com a blacklist
    return {
        "status": "invalido",
        "motivo": "Todos os links encontrados são apenas link de partida/perfil/busca, não prova real.",
        "links": links,
        "detalhes": detalhes,
    }
