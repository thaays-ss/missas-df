"""
Robô do "Onde tem missa? · DF".

Roda no GitHub Actions (de hora em hora) e também na sua máquina:
    python pipeline/atualiza.py                 # baixa a planilha do Google Sheets
    python pipeline/atualiza.py --planilha x.xlsx   # usa um arquivo local
    python pipeline/atualiza.py --forcar         # regera o site mesmo sem mudança

Passos:
  1. baixa a planilha dos fiéis (export .xlsx público do Google Sheets)
  2. limpa e junta com o cadastro da Arquidiocese (build_base.py)
  3. busca no mapa (OpenStreetMap/Nominatim) as igrejas ainda sem coordenada
  4. confere se nada quebrou (trava de segurança)
  5. grava dados/*.csv e gera public/index.html

A planilha baixada NUNCA é salva no repositório: ela tem a coluna "Quem atualizou?"
com nomes de pessoas. O robô só lê as colunas de horário.
"""
import argparse, base64, json, os, sys, tempfile, time, urllib.parse, urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parent
sys.path.insert(0, str(AQUI))
from build_base import main as monta_base, faixa, DIA_NOME  # noqa: E402
import curadoria  # noqa: E402

PLANILHA_ID = os.environ.get("PLANILHA_ID", "154ru-gzOx4rKf2jpgQmIRokFDx5b9_h7ZMFqRAs7RME")
CURADORIA_ID = os.environ.get("CURADORIA_ID", "1GNIsgfB31KY2Ij4MmEcIjxJ2BQITxuvY2Q8B9P24Juo")
URL_XLSX = f"https://docs.google.com/spreadsheets/d/{PLANILHA_ID}/export?format=xlsx"
DADOS, PUBLIC, SITE = RAIZ / "dados", RAIZ / "public", RAIZ / "site"
TIPOS = ["Missa", "Confissão", "Adoração"]
FONTES = ["Planilha do grupo de WhatsApp", "Site da Arquidiocese (página da paróquia)",
          "Site da Arquidiocese (tabela Horários de Missas, 2023)", curadoria.FONTE]
WD = dict(Dom=0, Seg=1, Ter=2, Qua=3, Qui=4, Sex=5, Sab=6)
BRT = timezone(timedelta(hours=-3))
TRAVA = 0.85  # se o total de horários cair mais de 15% de uma vez, não publica


def baixa(pid, nome):
    """Baixa uma planilha pública do Google como .xlsx.
    Serve para planilha do Google (export) e para .xlsx guardado no Drive (download direto)."""
    destino = Path(tempfile.gettempdir()) / f"{nome}.xlsx"
    urls = [f"https://docs.google.com/spreadsheets/d/{pid}/export?format=xlsx",
            f"https://drive.google.com/uc?export=download&id={pid}"]
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "missas-df-bot"})
            with urllib.request.urlopen(req, timeout=60) as r:
                dados = r.read()
            if dados[:2] == b"PK" and len(dados) > 5000:  # .xlsx é um zip
                destino.write_bytes(dados)
                return destino
        except Exception as e:
            print(f"  {nome}: {url[:60]}… falhou ({e})")
    raise SystemExit(f"Não consegui baixar a planilha '{nome}'. Ela continua compartilhada como 'qualquer pessoa com o link'?")


def baixa_planilha():
    return baixa(PLANILHA_ID, "planilha_grupo")


# ---------- coordenadas das igrejas sem pino ----------
def geocodifica(p):
    """Procura no OpenStreetMap (Nominatim) as igrejas sem lat/lng.
    Guarda tudo em dados/geocache.json (inclusive quando não acha), para
    consultar cada igreja uma vez só, respeitando o limite de 1 pedido/segundo."""
    cache_f = DADOS / "geocache.json"
    cache = json.loads(cache_f.read_text()) if cache_f.exists() else {}
    novos = 0
    for i, r in p[p.lat.isna()].iterrows():
        chave = f"{r.paroquia} | {r.bairro}" + (f" | {r.endereco}" if isinstance(r.endereco, str) and r.endereco else "")
        if chave not in cache and novos < 25:
            consultas = [f"{r.paroquia}, {r.bairro}, Distrito Federal", f"{r.paroquia}, Brasília"]
            if isinstance(r.endereco, str) and r.endereco:
                consultas.insert(0, r.endereco)
            achou = None
            for q in consultas:
                url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
                    dict(q=q, format="json", limit=1, countrycodes="br", viewbox="-48.30,-15.45,-47.30,-16.06", bounded=1))
                try:
                    req = urllib.request.Request(url, headers={"User-Agent": "missas-df-bot (github.com/thaays-ss/missas-df)"})
                    res = json.load(urllib.request.urlopen(req, timeout=30))
                except Exception as e:  # rede fora: tenta na próxima rodada
                    print("  nominatim falhou:", e)
                    res = None
                    break
                time.sleep(1.1)
                if res:
                    achou = [round(float(res[0]["lat"]), 6), round(float(res[0]["lon"]), 6)]
                    break
            else:
                cache[chave] = achou
            if achou:
                cache[chave] = achou
            novos += 1
            print(f"  mapa: {chave} -> {cache.get(chave)}")
        if cache.get(chave):
            p.loc[i, ["lat", "lng"]] = cache[chave]
    cache_f.write_text(json.dumps(cache, ensure_ascii=False, indent=1, sort_keys=True))
    return p


def para_site(h, p, esp, gerado):
    """Formato compacto que o index.html lê."""
    h = h[h.inicio.notna()]
    usados = set(h.paroquia_id) | set(esp.paroquia_id)
    par = {}
    for r in p[p.paroquia_id.isin(usados)].itertuples():
        lat = None if pd.isna(r.lat) else round(float(r.lat), 5)
        lng = None if pd.isna(r.lng) else round(float(r.lng), 5)
        rota = r.como_chegar
        if lat is not None and "google.com/maps/dir" not in rota and "goo.gl" not in rota and "maps.app" not in rota:
            rota = f"https://www.google.com/maps/dir/?api=1&destination={lat},{lng}"
        s = lambda v: v if isinstance(v, str) else ""
        par[str(r.paroquia_id)] = [r.paroquia, s(r.bairro), s(r.regiao) or "Não informado", lat, lng, rota, s(r.contato), s(r.pagina_arquidiocese)]
    rows = []
    for r in h.itertuples():
        rows.append([int(r.paroquia_id), TIPOS.index(r.tipo), WD[r.dia], r.inicio, r.fim if isinstance(r.fim, str) else "",
                     round(float(r.hora_num), 4), int(bool(r.aproximado)), str(r.atualizado_em), FONTES.index(r.fonte), r.local])
    E = [[r.data, r.inicio, r.fim, int(r.paroquia_id), r.celebracao, curadoria.TIPOS_ESP.index(r.tipo), r.obs] for r in esp.itertuples()]
    return dict(tipos=TIPOS, fontes=FONTES, par=par, rows=rows, esp=E, nParoquias=len(p), gerado=gerado)


def gera_html(data):
    t = (SITE / "template.html").read_text()
    js = (SITE / "vendor" / "leaflet.js").read_text().replace("//# sourceMappingURL=leaflet.js.map", "")
    t = t.replace("/*LEAFLETCSS*/", (SITE / "vendor" / "leaflet.css").read_text()).replace("/*LEAFLETJS*/", js)
    t = t.replace("/*ICON*/", base64.b64encode((SITE / "icone.png").read_bytes()).decode())
    t = t.replace("/*DATA*/", json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    PUBLIC.mkdir(exist_ok=True)
    (PUBLIC / "index.html").write_text(t)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--planilha", help="arquivo .xlsx local (senão baixa do Google Sheets)")
    ap.add_argument("--curadoria", help="planilha de curadoria local (senão baixa do Google)")
    ap.add_argument("--forcar", action="store_true", help="regera o site mesmo se nada mudou")
    a = ap.parse_args()

    arq = Path(a.planilha) if a.planilha else baixa_planilha()
    print("1. planilha:", arq)
    h, p, qual, sem_cad = monta_base(arq)
    if not a.planilha:
        arq.unlink(missing_ok=True)  # não deixa a planilha (com nomes) no disco
    print(f"2. base: {len(h)} horários, {h.paroquia_id.nunique()} igrejas")

    # curadoria (planilha da Thays): vale por cima das outras fontes
    avisos = []
    cur = Path(a.curadoria) if a.curadoria else baixa(CURADORIA_ID, "curadoria")
    h["dia"] = h.dia_semana.map({v: k for k, v in DIA_NOME.items()})
    h, p, esp = curadoria.aplica(cur, h, p, avisos)
    for x in avisos:
        print("  aviso:", x)
    print(f"2b. curadoria: {(h.fonte == curadoria.FONTE).sum()} horários, {len(esp)} datas especiais")

    p = geocodifica(p)
    p["latlng"] = p.apply(lambda r: f"{r.lat:.6f},{r.lng:.6f}" if pd.notna(r.lat) else "", axis=1)
    # recalcula as colunas derivadas (linhas da curadoria chegam só com o essencial)
    nucleo = ["paroquia_id", "tipo", "dia", "inicio", "fim", "local", "aproximado", "obs", "fonte", "atualizado_em"]
    h = h.reindex(columns=nucleo).merge(p[["paroquia_id", "paroquia", "regiao", "bairro", "endereco", "latlng", "como_chegar"]], on="paroquia_id")
    h["dia_semana"] = h.dia.map(DIA_NOME)
    h["hora_num"] = h.inicio.map(lambda x: int(x[:2]) + int(x[3:]) / 60 if isinstance(x, str) else None)
    h["faixa_horario"] = h.hora_num.map(lambda x: faixa(x) if pd.notna(x) else "Horário a confirmar")
    h["horario"] = h.apply(lambda r: (r.inicio or "") + (f"–{r.fim}" if isinstance(r.fim, str) and r.fim else "") + (" (aprox.)" if r.aproximado else "") if isinstance(r.inicio, str) else (r.obs or "a confirmar"), axis=1)
    h = h.sort_values(["dia", "hora_num", "paroquia"], key=lambda s: s.map({d: i for i, d in enumerate(["Seg", "Ter", "Qua", "Qui", "Sex", "Sab", "Dom"])}) if s.name == "dia" else s)

    # 4. trava de segurança
    ant_f = DADOS / "horarios.csv"
    if ant_f.exists():
        n_ant = len(pd.read_csv(ant_f))
        if len(h) < TRAVA * n_ant:
            raise SystemExit(f"TRAVA: caiu de {n_ant} para {len(h)} horários de uma vez. "
                             "Provável problema na planilha (coluna apagada?). Site NÃO foi atualizado.")

    cols_h = ["paroquia_id", "paroquia", "tipo", "dia_semana", "horario", "inicio", "fim", "hora_num", "faixa_horario",
              "local", "aproximado", "regiao", "bairro", "endereco", "latlng", "como_chegar", "fonte", "atualizado_em"]
    novo_csv = h.reindex(columns=cols_h).to_csv(index=False)
    esp_f = DADOS / "especiais.csv"
    esp_out = esp.merge(p[["paroquia_id", "paroquia", "bairro"]], on="paroquia_id", how="left")
    novo_esp = esp_out.to_csv(index=False)
    mudou = (not ant_f.exists() or ant_f.read_text() != novo_csv or not esp_f.exists() or esp_f.read_text() != novo_esp)
    if not mudou and not a.forcar:
        print("3. nada mudou na planilha. Fim.")
        return

    ant_f.write_text(novo_csv)
    esp_f.write_text(novo_esp)
    p.drop(columns=["obs_grupo"]).to_csv(DADOS / "paroquias.csv", index=False)
    conferir = qual[qual.fonte_escolhida.eq("sem horário estruturado")][["paroquia_id", "paroquia", "regiao", "tipo"]]
    conferir = pd.concat([conferir.assign(motivo="texto sem horário que o robô entenda"),
                          pd.DataFrame(dict(paroquia=p[p.lat.isna()].paroquia, regiao=p[p.lat.isna()].regiao,
                                            motivo="sem localização no mapa")),
                          pd.DataFrame(dict(motivo=[f"planilha de curadoria: {x}" for x in avisos]))])
    conferir["paroquia_id"] = conferir.paroquia_id.astype("Int64")
    conferir.to_csv(DADOS / "conferir.csv", index=False)

    gerado = datetime.now(BRT).strftime("%Y-%m-%d %H:%M")
    gera_html(para_site(h, p, esp, gerado))
    print(f"3. site gerado: {len(h)} horários · {len(conferir)} itens para conferir · {gerado}")


if __name__ == "__main__":
    main()
