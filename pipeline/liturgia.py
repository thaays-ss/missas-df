"""Evangelho do dia e folheto "O Povo de Deus" para o site.

- Liturgia: API pública liturgia.up.railway.app (só a referência do Evangelho e o nome
  do dia; o texto não é copiado, o site manda ler no site da CNBB).
- Folheto: PDFs que a Arquidiocese de Brasília publica no WordPress dela
  (arqbrasilia.com.br), com títulos como "61 Povo Deus 61 15_11_33o Domingo TC Versao celular".

Se alguma fonte falhar, fica valendo o que já estava em dados/liturgia.json.
"""
import json
import re
import urllib.request
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo

API = "https://liturgia.up.railway.app/v2/?dia={d}&mes={m}&ano={a}"
WP = ("https://arqbrasilia.com.br/wp-json/wp/v2/media?mime_type=application/pdf"
      "&per_page=60&orderby=date&_fields=date,title,source_url")
UA = {"User-Agent": "Mozilla/5.0 (missanodf.com.br robo)"}
FOLHETO = re.compile(r"^\s*\d+[-_.\d]*\s+Povo\s+Deus\s+\d+\s+(\d{1,2})_(\d{1,2})_(.+?)\s*$", re.I)


def _get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return json.load(r)


def _liturgia(d):
    j = _get(API.format(d=d.day, m=d.month, a=d.year))
    ev = (j.get("leituras", {}).get("evangelho") or [{}])[0]
    return [j.get("liturgia", ""), ev.get("referencia", "")]


def _nome_folheto(resto):
    """'33o Domingo TC Versao celular' → '33º Domingo do Tempo Comum'"""
    s = re.sub(r"\s*(prova\s+final|vers[aã]o\s+celular|\(\d+\))\s*", " ", resto, flags=re.I)
    s = re.sub(r"(\d+)o\b", r"\1º", s)
    s = re.sub(r"\bTC\b", "do Tempo Comum", s)
    s = re.sub(r"\bNSra\b", "Nossa Senhora", s, flags=re.I)
    s = re.sub(r"\b(paroquias|esplanada)\b", " ", s, flags=re.I)
    s = s.replace("_", " ").strip(" -")
    return " ".join(w.capitalize() if w.isupper() and len(w) > 1 else w for w in s.split())


def _folhetos(hoje):
    por_data = {}
    for x in _get(WP):
        tit = re.sub(r"&#\d+;", "-", x["title"]["rendered"])
        m = FOLHETO.match(tit)
        if not m:
            continue
        up = datetime.fromisoformat(x["date"]).date()
        dia, mes = int(m.group(1)), int(m.group(2))
        ano = up.year + (1 if mes < up.month - 6 else 0)  # folheto de janeiro publicado em dezembro
        try:
            dt = date(ano, mes, dia)
        except ValueError:
            continue
        if dt < hoje - timedelta(days=7):
            continue
        cel = bool(re.search(r"celular", tit, re.I))
        par = bool(re.search(r"paroquias", tit, re.I))
        nota = (2 if cel else 0) + (1 if par else 0)
        atual = por_data.get(dt)
        if atual is None or nota > atual[0]:
            por_data[dt] = (nota, _nome_folheto(m.group(3)), x["source_url"])
    return [[d.isoformat(), n, u] for d, (_, n, u) in sorted(por_data.items())]


def busca(cache_path):
    try:
        cache = json.loads(cache_path.read_text())
    except Exception:
        cache = {"lit": {}, "folh": []}
    hoje = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
    lit = {}
    for i in range(0, 8):
        d = hoje + timedelta(days=i)
        k = d.isoformat()
        if cache["lit"].get(k, [""])[0]:
            lit[k] = cache["lit"][k]
            continue
        try:
            lit[k] = _liturgia(d)
        except Exception as e:
            print(f"  liturgia {k}: {e}")
    try:
        folh = _folhetos(hoje)
    except Exception as e:
        print(f"  folhetos: {e}")
        folh = [f for f in cache.get("folh", []) if f[0] >= (hoje - timedelta(days=7)).isoformat()]
    # nome oficial do dia, quando a API tem aquela data
    folh = [[d, (lit.get(d) or [n])[0] or n, u] for d, n, u in folh]
    out = {"lit": lit, "folh": folh}
    cache_path.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    return out
