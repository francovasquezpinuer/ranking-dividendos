#!/usr/bin/env python3
"""Ranking diario de dividendos — Bolsa de Santiago (proyecto "Acciones" de Franco).

Uso:
  python3 pipeline.py --page bolsa_actual.html --ipsa ipsa_actual.html --delta delta.json --out salida/
  python3 pipeline.py --page bolsa_actual.html --ipsa ipsa_actual.html --full base.json   --out salida/

  --page   HTML publicado hoy del artifact "Ranking Bolsa de Santiago" (fuente de la serie de precios mensuales).
  --ipsa   HTML publicado del artifact "Ranking IPSA" (solo se le reemplazan los datos).
  --delta  datos del día descargados con delta.js  {fecha, data:{tk:[mPrev,cPrev,mk,precio,dy5,ttm,payout,fd6,lq2]}}
  --full   datos completos descargados con fetch.js (formato compacto {fecha,yrs,data:{tk:[m0,c60,dy5,ttm,p,fd6,lq2,cur]}})

Salida en --out: ranking-bolsa.html, ranking-ipsa.html, informe.md, resumen.json
"""
import json, math, re, sys, argparse, os, datetime

N = 60
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
MESES_L = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
FINS = {"ILC", "QUINENCO"}
SECTOR_FIX = {"ENTEL": "Comunicación y tecnología", "ENAEX": "Industrial", "EDELPA": "Industrial", "FROWARD": "Industrial",
              "EISA": "Construcción e inmobiliaria", "MOLLER": "Construcción e inmobiliaria", "CENCOMALLS": "Construcción e inmobiliaria",
              "GASCO": "Utilities", "ILC": "Financiero", "HABITAT": "Financiero", "PROVIDA": "Financiero", "CUPRUM": "Financiero",
              "QUINENCO": "Holdings", "ANTARCHILE": "Holdings", "ALMENDRAL": "Holdings", "INDISA": "Salud", "LAS CONDES": "Salud"}


# ---------------------------------------------------------------- utilidades
def lin(x, y):
    n = len(x)
    if n < 2: return 0.0, (y[0] if y else 0.0), 0.0
    mx, my = sum(x) / n, sum(y) / n
    sxx = sum((a - mx) ** 2 for a in x); syy = sum((b - my) ** 2 for b in y)
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    m = sxy / sxx if sxx else 0.0
    b = my - m * mx
    r = sxy / math.sqrt(sxx * syy) if sxx and syy else 0.0
    return m, b, r


def clamp(v, lo, hi): return max(0.0, min(1.0, (v - lo) / (hi - lo)))
def nf(v, d): return f"{v:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def extract_js(html, name):
    i = html.index(f"const {name} = "); j = html.index("\n", i)
    return json.loads(html[i + len(f"const {name} = "):j].rstrip().rstrip(";"))


def replace_js(html, name, obj):
    i = html.index(f"const {name} = "); j = html.index("\n", i)
    return html[:i] + f"const {name} = " + json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + ";" + html[j:]


def page_m0(html):
    m = re.search(r"const label = i => \{ const t = (\d+) \+ i; return MES\[t % 12\] \+ \" \" \+ \((\d{4}) \+", html)
    return int(m.group(2)) * 12 + int(m.group(1))


# ---------------------------------------------------------------- datos base
def base_from_page(html):
    """Reconstruye la base (serie mensual, LIQ, DEBT, universo) desde la página publicada."""
    rows = extract_js(html, "ROWS"); liq = extract_js(html, "LIQ"); debt = extract_js(html, "DEBT")
    m0 = page_m0(html)
    base = {}
    for r in rows:
        base[r["tk"]] = {"sec": r["sec"], "name": r["name"], "ipsa": r["ipsa"], "m0": m0, "c": list(r["v"]), "dy": list(r["d"]),
                         "t": r["t"], "p": r["po"], "fd": debt.get(r["tk"]), "lq": liq.get(r["tk"], [0, 0])}
    return base


def apply_delta(base, delta):
    """Actualiza la serie mensual con el precio del día y reemplaza dividendos, payout, deuda y liquidez."""
    sin = []
    for tk, b in base.items():
        d = delta["data"].get(tk)
        if not d or d[3] is None: sin.append(tk); continue
        mprev, cprev, mk, px, dy, t, p, fd, lq = d
        last = b["m0"] + N - 1
        c = b["c"]
        if mk > last:  # cambió el mes: fija el cierre del mes anterior y agrega meses nuevos
            if mprev == last and cprev is not None: c[-1] = cprev
            for _ in range(mk - last): c.append(c[-1])
            c = c[-N:]; b["m0"] = mk - N + 1
        c[-1] = px; b["c"] = c
        if dy is not None: b["dy"] = dy
        if t is not None: b["t"] = t
        if p != "keep": b["p"] = p
        if fd is not None: b["fd"] = fd
        if lq is not None: b["lq"] = lq
    return sin


def base_from_full(full, universo):
    base = {}
    for tk, sec, name, ipsa in universo:
        d = full["data"][tk]
        base[tk] = {"sec": sec, "name": name, "ipsa": bool(ipsa), "m0": d[0], "c": d[1], "dy": d[2], "t": d[3], "p": d[4], "fd": d[5], "lq": d[6] or [0, 0]}
    return base


def fixes(base, yrs):
    """Correcciones manuales conocidas de Yahoo (los datos verificados de datos/verificados.json se aplican después)."""
    if "SOQUICOM" in base:
        if (base["SOQUICOM"]["t"] or 0) > 1000: base["SOQUICOM"]["t"] = 25.23
        if base["SOQUICOM"]["p"] is not None and base["SOQUICOM"]["p"] > 2: base["SOQUICOM"]["p"] = None
    if "PAMPA" in base:  # Yahoo informa sus dividendos en otra moneda
        base["PAMPA"]["dy"] = [0, 0, 0, 0, 0]; base["PAMPA"]["t"] = 0
    for b in base.values():
        if b["p"] is not None and (b["p"] > 2): b["p"] = None


def aplicar_verificados(base, verif, yrs):
    """Reemplaza datos de Yahoo por datos verificados con fuentes primarias (dividendos regulares por año y payout)."""
    for tk, ov in (verif or {}).items():
        if tk.startswith("_") or tk not in base: continue
        b = base[tk]
        for y, val in (ov.get("div") or {}).items():
            if int(y) in yrs: b["dy"][yrs.index(int(y))] = val
        if "po" in ov: b["p"] = ov["po"]


# ---------------------------------------------------------------- deuda: escalas por sector (según clasificadoras de riesgo)
# (umbral con puntaje completo, umbral con puntaje cero) para deuda neta / EBITDA
ESCALAS = {
    "agua y eléctricas reguladas": (3.5, 6.0, {"AGUAS-A", "IAM", "ESVAL-C", "ESSBIO-C", "CGE", "ENELDXCH", "EDELMAG"}),
    "generación eléctrica": (2.0, 3.5, {"ENELGXCH", "ENELCHILE", "COLBUN", "ECL", "ENELAM"}),
    "malls": (4.5, 8.0, {"MALLPLAZA", "PARAUCO", "CENCOMALLS"}),
    "retail": (2.0, 3.5, {"FALABELLA", "CENCOSUD", "RIPLEY", "SMU", "FORUS", "HITES", "TRICOT"}),
    "bebidas y consumo": (1.5, 3.0, {"ANDINA-A", "ANDINA-B", "CCU", "EMBONOR-A", "EMBONOR-B", "CONCHATORO", "CAROZZI", "WATTS", "IANSA", "VSPT", "SANTA RITA", "EMILIANA"}),
}
ESCALA_GENERAL = (2.0, 5.0)
HOLDINGS = {"QUINENCO", "ANTARCHILE", "ALMENDRAL", "BANVIDA", "INVERCAP", "MARINSA", "POTASIOS-A", "CIC", "MINERA"}


def escala(tk):
    for nombre, (lo, hi, tks) in ESCALAS.items():
        if tk in tks: return nombre, lo, hi
    return "general", ESCALA_GENERAL[0], ESCALA_GENERAL[1]


def debt_info(r):
    """Devuelve {t, x, lo, hi, dir, lbl}: dir 'down' = menos es mejor; 'up' = más es mejor; 'mid' = neutro."""
    ov = r.get("_ovd")
    nombre, lo, hi = escala(r["tk"])
    if ov and ov.get("t") == "ltv":
        x = ov["x"]; return {"t": "ltv", "x": x, "lo": .20, "hi": .45, "dir": "down", "lbl": f"Holding: deuda neta = {nf(x * 100, 0)}% del valor (dato verificado; ≤20% = máximo)"}
    if ov and ov.get("t") == "nd":
        x = ov["x"]; return {"t": "nd", "x": x, "lo": lo, "hi": hi, "dir": "down", "lbl": f"Deuda neta = {nf(x, 1)} veces el EBITDA (dato verificado; escala {nombre}: ≤{nf(lo, 1)}x máximo, ≥{nf(hi, 1)}x cero)"}
    d = r["_fd"]
    if r["_sec2"] == "Banca" or r["sec"] == "Banca":
        if d and d[3] and d[4] and d[3] > 0 and d[4] > 0:
            x = d[3] / d[4]; return {"t": "cap", "x": x, "lo": .06, "hi": .10, "dir": "up", "lbl": f"Patrimonio = {nf(x * 100, 1)}% de los activos (≥10% máximo, ≤6% cero)"}
        return {"t": "na", "lbl": "Sin dato"}
    if r["tk"] in HOLDINGS or r["tk"] in FINS:
        return {"t": "hold", "dir": "mid", "lbl": "Holding: la deuda consolidada no es comparable (puntaje neutro)"}
    if not d: return {"t": "na", "lbl": "Sin dato"}
    cash, debt, eb, roa, roe, de = d
    if debt is not None and cash is not None and debt <= cash:
        return {"t": "nd", "x": -1, "lo": lo, "hi": hi, "dir": "down", "lbl": "Tiene más caja que deuda"}
    if eb is None:
        if de is not None: return {"t": "de", "x": de / 100, "lo": .5, "hi": 1.5, "dir": "down", "lbl": f"Deuda = {nf(de, 0)}% del patrimonio (≤50% máximo, ≥150% cero)"}
        return {"t": "nd", "x": -1, "lo": lo, "hi": hi, "dir": "down", "lbl": "Sin deuda"} if debt == 0 else {"t": "na", "lbl": "Sin dato"}
    if eb <= 0: return {"t": "neg", "lbl": "EBITDA negativo"}
    x = (debt - cash) / eb
    return {"t": "nd", "x": x, "lo": lo, "hi": hi, "dir": "down", "lbl": f"Deuda neta = {nf(x, 1)} veces el EBITDA (escala {nombre}: ≤{nf(lo, 1)}x máximo, ≥{nf(hi, 1)}x cero)"}


def debt_pts(r, mx=11):
    i = r.get("dx") or debt_info(r)
    if i.get("dir") == "down": return mx * (1 - clamp(i["x"], i["lo"], i["hi"]))
    if i.get("dir") == "up": return mx * clamp(i["x"], i["lo"], i["hi"])
    if i.get("dir") == "mid": return mx / 2
    return 0


# ---------------------------------------------------------------- cálculos
def fund_metrics(tk, f, fd, sec, po, ov=None):
    """Crecimiento de utilidades (pendiente ÷ promedio), cobertura del dividendo con caja y ROE."""
    eg = cov = None
    ni = [v for _, v in (f or {}).get("ni", [])]
    if ov and "ni" in ov: ni = [v for _, v in (ov["ni"] or [])]
    if len(ni) >= 3:
        m, b, _ = lin(list(range(len(ni))), ni); av = sum(ni) / len(ni)
        eg = round(max(-1.0, min(1.0, m / av)), 4) if av > 0 else -1.0
    fin = sec == "Banca" or tk in FINS
    if fin:  # en bancos y financieras el flujo de caja no sirve: se usa utilidad ÷ dividendo (1 / payout)
        cov = round(1 / po, 4) if po and po > 0 else None
    else:
        fcf = [v for _, v in (f or {}).get("fcf", [])][-2:]; dp = [abs(v) for _, v in (f or {}).get("dp", [])][-2:]
        if fcf and dp and sum(dp) > 0: cov = round((sum(fcf) / len(fcf)) / (sum(dp) / len(dp)), 4)
    roe = fd[4] if fd and len(fd) > 4 else None
    if ov and "roe" in ov: roe = ov["roe"]
    return eg, cov, roe


def compute(base, fund=None, verif=None):
    rows = []
    for tk, b in base.items():
        ov = (verif or {}).get(tk) or {}
        v = [float(x) for x in b["c"]]
        s = max(0, 2022 * 12 + 10 - b["m0"]) if tk == "LTM" else 0  # LATAM desde nov-2022 (reestructuración)
        xs = list(range(s, len(v))); ys = [v[i] for i in xs]
        pm, pb, pr = lin(xs, ys)
        if min(ys) > 0:
            k, a, _ = lin(xs, [math.log(y) for y in ys]); g = math.exp(12 * k) - 1; tend = math.exp(a + k * (len(v) - 1))
        else:
            k = a = 0; g = 0; tend = v[-1]
        d = [float(x) for x in b["dy"]]
        dm, db, dr = lin([1, 2, 3, 4, 5], d); dav = sum(d) / 5
        if dav > 0:
            res = [d[i] - (dm * (i + 1) + db) for i in range(5)]; rcv = math.sqrt(sum(e * e for e in res) / 5) / dav
        else: rcv = 9
        last = v[-1]; yt = (b["t"] or 0) / last if last else 0
        sv = v[s:]; flat = sum(1 for i in range(1, len(sv)) if sv[i] == sv[i - 1]) / (len(sv) - 1)
        po = b["p"]
        sec = SECTOR_FIX.get(tk, b["sec"])
        r = dict(tk=tk, sec=b["sec"], name=b["name"], ipsa=b["ipsa"], pm=round(pm, 4), pb=round(pb, 4), pr=round(pr, 4), g=round(g, 4),
                 dm=round(dm, 4), db=round(db, 4), dr=round(dr, 4), dav=round(dav, 4), rcv=round(rcv, 4), yt=round(yt, 4),
                 po=None if po is None else round(po, 4), last=last, v=b["c"], d=b["dy"], t=b["t"], s=s, flat=round(flat, 4), liq=flat <= 0.4)
        r["eg"], r["cov"], r["roe"] = fund_metrics(tk, (fund or {}).get(tk), b["fd"], b["sec"], po, ov)
        r["_sec2"] = sec; r["_mv"] = (b["lq"] or [0, 0])[1]; r["_fd"] = b["fd"]; r["_tend"] = tend; r["_k"] = k; r["_ovd"] = ov.get("deuda")
        r["dx"] = debt_info(r)
        if ov.get("nota"):
            r["vf"] = ov["nota"]
            if ov.get("fuente"): r["vfu"] = ov["fuente"]
        rows.append(r)
    return rows


# --- puntaje (idéntico al de la página)
def pay_high(p): return 11 * (0 if p is None or p <= 0 or p > 1 else .4 if p > .90 else .75 if p > .75 else 1 if p >= .40 else .5 if p >= .30 else .15 if p >= .20 else 0)


def chw(r): return (r["yt"] or 0) + (max(-0.1, min(0.10, r["dm"] / r["dav"])) if r["dav"] > 0 else 0)


def score_crec(r):
    S = [16 * clamp(r["g"], 0, .25) * max(0.0, r["pr"]),                       # crecimiento firme del precio (tendencia × crecimiento)
         8 * (r["dr"] + 1) / 2 if r["dav"] > 0 else 0,                            # tendencia dividendo
         8 * clamp(r["dm"] / r["dav"], 0, .20) if r["dav"] > 0 else 0,            # crecimiento dividendo
         pay_high(r["po"]),                                                     # % de pago sano (11)
         8 * clamp(0.6 - r["rcv"], 0, 0.6),                                     # constancia
         11 * clamp(chw(r), .05, .17),                                          # rendimiento + crecimiento
         debt_pts(r),                                                           # deuda (11)
         11 * clamp(r["eg"], 0, .15) if r.get("eg") is not None else 0,         # crecimiento de utilidades
         8 * clamp(r["roe"], .05, .20) if r.get("roe") is not None else 0,      # ROE
         4 * clamp(r["cov"], .8, 1.5) if r.get("cov") is not None else 0,       # cobertura del dividendo con caja
         4 * clamp(math.log10(max(r["_mv"], 1)), math.log10(5e6), 9)]           # liquidez
    return S, sum(S)


CRIT = ["Crecimiento firme del precio", "Tendencia dividendo", "Crecimiento dividendo", "% de pago sano", "Constancia",
        "Rendimiento + crecimiento", "Deuda", "Crecimiento de utilidades", "ROE", "Cobertura con caja", "Liquidez"]


def rank(rows):
    ok = [r for r in rows if r["liq"] and r["_mv"] >= 5e6]
    for r in rows: r["_S"], r["_T"] = score_crec(r); r["_rk"] = None
    for i, r in enumerate(sorted(ok, key=lambda r: -r["_T"])): r["_rk"] = i + 1
    return sorted(ok, key=lambda r: r["_rk"])


# ---------------------------------------------------------------- páginas
def label(m): return f"{MESES[m % 12]} {m // 12}"


WEB_HEAD = '<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">'


def patch_page(html, rows, liq, debt, m0, yrs, fecha_txt, informe_block=None, nav=None, vivo=""):
    html = replace_js(html, "ROWS", rows)
    if "const LIQ = " in html: html = replace_js(html, "LIQ", liq)
    if "const DEBT = " in html: html = replace_js(html, "DEBT", debt)
    html = re.sub(r"const label = i => \{ const t = \d+ \+ i; return MES\[t % 12\] \+ \" \" \+ \(\d{4} \+",
                  f'const label = i => {{ const t = {m0 % 12} + i; return MES[t % 12] + " " + ({m0 // 12} +', html)
    html = re.sub(r"String\(\d{4}\+i\)", f"String({yrs[0]}+i)", html)
    html = re.sub(r"(dividendo anual \(|dividendo )20\d\d–20\d\d", lambda m: f"{m.group(1)}{yrs[0]}–{yrs[-1]}", html)
    html = re.sub(r"[a-z]{3} 20\d\d – [a-z]{3} 20\d\d", f"{label(m0)} – {label(m0 + N - 1)}", html)
    html = re.sub(r"consultados el [0-9]{1,2} de [a-z]+ de 20\d\d( a las \d{1,2}:\d\d)?", f"consultados el {fecha_txt}", html)
    if informe_block is not None:  # versión web: documento completo + informe + navegación
        if not html.lstrip().lower().startswith("<!doctype"): html = WEB_HEAD + html + "</html>"
        html = re.sub(r"<!--NAV-->.*?<!--/NAV-->", "", html, flags=re.S)
        html = re.sub(r"<!--INFORME-->.*?<!--/INFORME-->", "", html, flags=re.S)
        html = re.sub(r"<!--VIVO-->.*?<!--/VIVO-->", "", html, flags=re.S)
        html = html.replace('<div class="wrap">', '<div class="wrap">' + (nav or ""), 1)
        html = html.replace("</header>", "</header>" + vivo + informe_block, 1)
    return html


def clean(r): return {k: v for k, v in r.items() if not k.startswith("_")}


# ---------------------------------------------------------------- orden de compra entre las candidatas
SMAX = [16, 8, 8, 11, 8, 11, 11, 11, 8, 4, 4]
FUERTE = ["el precio crece firme", "el dividendo tiene tendencia al alza", "el dividendo viene creciendo", "reparte un % sano de sus utilidades",
          "paga dividendos con constancia", "buen rendimiento más crecimiento", "deuda acotada para su sector", "utilidades creciendo",
          "ROE alto", "el dividendo está cubierto con caja", "se transa mucho"]
DEBIL = ["el precio no crece firme", "el dividendo no muestra tendencia clara", "el dividendo crece poco", "reparte un % de utilidades fuera del rango sano",
         "dividendo irregular", "rendimiento bajo", "deuda alta para su sector", "utilidades que no crecen",
         "ROE bajo", "la caja no cubre bien el dividendo", "se transa poco"]


def prioridad(T, dev, mv):
    """Orden de compra: puntaje + premio por estar bajo su tendencia (hasta +10 pts con 20% de descuento) − 3 si se transa poco."""
    return T + 50 * min(max(-dev, 0), 0.20) - (3 if mv < 1e8 else 0)


def ordenar_cand(cand):
    return sorted(cand, key=lambda r: -prioridad(r["_T"], r["_dev"], r["_mv"]))


def razones(r):
    """(por qué comprarla, ojo) a partir de los criterios del puntaje."""
    S = r["_S"]; frac = [S[i] / SMAX[i] for i in range(11)]
    pq = []
    if r["_dev"] <= -0.05: pq.append(f"está {nf(abs(r['_dev']) * 100, 0)}% bajo su tendencia de 5 años (precio con descuento)")
    else: pq.append("cotiza en línea con su tendencia de 5 años (precio justo, sin sobreprecio)")
    fuertes = sorted([i for i in range(10) if frac[i] >= 0.85], key=lambda i: -SMAX[i])[:3]
    if fuertes: pq.append(", ".join(FUERTE[i] for i in fuertes))
    pq.append(f"rinde {nf(r['yt'] * 100, 1)}% en 12 meses")
    debiles = sorted([i for i in range(11) if frac[i] < 0.4], key=lambda i: frac[i] * SMAX[i] - SMAX[i])[:2]
    ojo = [DEBIL[i] for i in debiles]
    if r["_mv"] < 1e8 and DEBIL[10] not in ojo: ojo.append(DEBIL[10])
    return "; ".join(pq), ", ".join(ojo)


# ---------------------------------------------------------------- informe
def tramo(dev):
    if dev <= -0.05: return "bajo su tendencia"
    if dev <= 0.10: return "cerca de su tendencia"
    if dev <= 0.25: return "sobre su tendencia"
    return "muy sobre su tendencia"


def set_dev(ok):
    for r in ok: r["_dev"] = r["last"] / r["_tend"] - 1 if r["_tend"] else 0


def picks(ok):
    top = ok[:12]
    return [r for r in top if r["_dev"] <= 0.05][:5], [r for r in top if r["_dev"] > 0.10]


def cambio(prev_rank, r, pos):
    p = prev_rank.get(r["tk"])
    return "nueva" if p is None else ("=" if p == pos else (f"▲{p - pos}" if p > pos else f"▼{pos - p}"))


def tier(mv): return "alta" if mv >= 1e9 else "media" if mv >= 1e8 else "baja"
def sgn_pct(x): return ("+" if x >= 0 else "−") + nf(abs(x) * 100, 0) + "%"


def informe(ok, prev_rank, fecha_txt, sin_datos):
    set_dev(ok)
    cand, caras = picks(ok)
    L = [f"## Ranking de dividendos — {fecha_txt}", ""]
    L.append("**Top 10 (modo Crecimiento, con requisito de liquidez)**")
    L.append("")
    L.append("| # | Acción | Puntaje | Cambio | Precio vs tendencia | Liquidez |")
    L.append("|---|---|---|---|---|---|")
    for r in ok[:10]:
        L.append(f"| {r['_rk']} | {r['tk']}{' (IPSA)' if r['ipsa'] else ''} | {nf(r['_T'], 1)} | {cambio(prev_rank, r, r['_rk'])} | {sgn_pct(r['_dev'])} ({tramo(r['_dev'])}) | {tier(r['_mv'])} |")
    L.append("")
    L.append("**Candidatas para comprar hoy, en orden de compra** (entre las 12 mejores del ranking, las 5 de mayor puntaje cuyo precio está a no más de 5% sobre su tendencia de 5 años; "
             "el orden suma al puntaje un premio por estar bajo su tendencia y resta 3 pts si se transa poco):")
    if cand:
        for i, r in enumerate(ordenar_cand(cand)):
            pq, ojo = razones(r)
            L.append(f"{i + 1}. **{r['tk']}** ({nf(r['_T'], 1)} pts, puesto {r['_rk']}). Por qué: {pq}."
                     + (f" Ojo: {ojo}." if ojo else ""))
    else:
        L.append("- Ninguna hoy: las mejor rankeadas están sobre su tendencia de precio.")
    if caras:
        L.append("")
        L.append("**Buenas, pero caras hoy (mejor esperar una baja):** " + ", ".join(f"{r['tk']} ({sgn_pct(r['_dev'])})" for r in caras))
    entran = [r["tk"] for r in ok[:10] if prev_rank.get(r["tk"], 99) > 10]
    salen = [tk for tk, p in prev_rank.items() if p <= 10 and tk not in {r["tk"] for r in ok[:10]}]
    if prev_rank and (entran or salen):
        L.append("")
        L.append("**Cambios en el top 10:** " + ("entran " + ", ".join(entran) if entran else "") + ("; " if entran and salen else "") + ("salen " + ", ".join(salen) if salen else ""))
    if sin_datos:
        L.append("")
        L.append("Sin datos nuevos hoy (se mantuvo el dato anterior): " + ", ".join(sin_datos) + ".")
    L.append("")
    L.append("_Análisis de datos pasados con tus criterios; no es una recomendación de un asesor financiero._")
    return "\n".join(L)


INF_CSS = """<style>
#informe{display:grid;gap:14px;border:1px solid var(--rule);background:var(--surface);border-radius:12px;padding:18px 20px}
#informe h2{margin:0;font-family:var(--display);font-weight:600;font-size:1.5rem}
#informe .sub{color:var(--fg2);font-size:13px;margin:0}
#informe .cands{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px}
#informe .cand{border:1px solid var(--rule);border-radius:10px;padding:10px 12px;background:var(--bg)}
#informe .cand b{font-size:15px}
#informe .cand .ord{display:block;font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);font-weight:600;margin-bottom:2px}
#informe .cand:first-child{border-color:var(--fg2)}
#informe .cand:first-child .ord{color:var(--fit)}
#informe .cand .pq b{font-size:12.5px;color:var(--fg)}
#informe .cand p.pq{text-align:justify;hyphens:auto;-webkit-hyphens:auto}
#informe .cand .pts{display:block;font-family:var(--mono);font-size:12.5px;color:var(--fg2);margin-top:2px}
#informe .cand p{margin:6px 0 0;font-size:12.5px;color:var(--fg2);line-height:1.45}
#informe table{border-collapse:collapse;width:100%;font-size:13px}
#informe th,#informe td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--grid);white-space:nowrap}
#informe td.n{font-family:var(--mono);text-align:right}
#informe .tw{overflow-x:auto}
#informe .up{color:var(--up)} #informe .down{color:var(--down)}
#informe .warn{color:var(--fit)}
#informe small{color:var(--muted)}
.topnav{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:6px}
.topnav a{font-size:13px;padding:5px 12px;border:1px solid var(--rule);border-radius:999px;color:var(--fg);text-decoration:none}
.topnav a.on{background:var(--fg);color:var(--bg);border-color:var(--fg)}
</style>"""


def esc(s): return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def informe_html(ok, prev_rank, fecha_txt, sin_datos, titulo):
    """Bloque HTML del informe; ok ya ordenado (posición = índice+1 dentro de esta lista)."""
    set_dev(ok)
    pos = {r["tk"]: i + 1 for i, r in enumerate(ok)}
    top = ok[:12]
    cand = [r for r in top if r["_dev"] <= 0.05][:5]
    caras = [r for r in top if r["_dev"] > 0.10]
    H = ["<!--INFORME-->", INF_CSS, '<section id="informe">',
         f'<div><h2>{esc(titulo)}</h2><p class="sub">Actualizado el {esc(fecha_txt)} (hora de Chile) · se actualiza solo varias veces al día hábil</p></div>',
         '<div><b>Candidatas para comprar hoy, en orden de compra</b><p class="sub">Entre las 12 mejores del ranking, las 5 de mayor puntaje cuyo precio está a no más de 5% sobre su tendencia de 5 años. '
         'El orden parte del puntaje, suma un premio por estar bajo su tendencia (hasta +10 pts con 20% de descuento) y resta 3 pts si se transa poco.</p></div>']
    if cand:
        H.append('<div class="cands">')
        for i, r in enumerate(ordenar_cand(cand)):
            pq, ojo = razones(r)
            H.append(f'<div class="cand"><span class="ord">{i + 1}ª opción</span><b>{esc(r["tk"])}</b><span class="pts">{nf(r["_T"], 1)} pts · #{pos[r["tk"]]} del ranking</span>'
                     f'<p>Precio {sgn_pct(r["_dev"])} vs. su tendencia · rinde {nf(r["yt"] * 100, 1)}%<br>'
                     f'Payout {"s/d" if r["po"] is None else nf(r["po"] * 100, 0) + "%"} · liquidez {tier(r["_mv"])}</p>'
                     f'<p class="pq"><b>Por qué:</b> {esc(pq[0].upper() + pq[1:])}.</p>'
                     + (f'<p class="pq"><span class="warn">Ojo:</span> {esc(ojo)}.</p>' if ojo else "") + "</div>")
        H.append("</div>")
    else:
        H.append('<p class="sub">Ninguna hoy: las mejor rankeadas están más de 5% sobre su tendencia de precio.</p>')
    if caras:
        H.append('<p style="margin:0"><b>Buenas, pero caras hoy (mejor esperar una baja):</b> ' + ", ".join(f"{esc(r['tk'])} ({sgn_pct(r['_dev'])})" for r in caras) + "</p>")
    H.append('<div class="tw"><table><thead><tr><th>#</th><th>Acción</th><th>Puntaje</th><th>Cambio vs. día hábil anterior</th><th>Precio vs. tendencia</th><th>Liquidez</th></tr></thead><tbody>')
    for r in ok[:10]:
        ch = cambio(prev_rank, r, pos[r["tk"]])
        cls = "up" if ch.startswith("▲") else "down" if ch.startswith("▼") else ""
        H.append(f'<tr><td class="n">{pos[r["tk"]]}</td><td>{esc(r["tk"])}{" <small>IPSA</small>" if r["ipsa"] else ""}</td><td class="n">{nf(r["_T"], 1)}</td>'
                 f'<td class="{cls}">{ch}</td><td>{sgn_pct(r["_dev"])} <small>{tramo(r["_dev"])}</small></td><td>{tier(r["_mv"])}</td></tr>')
    H.append("</tbody></table></div>")
    ids = {r["tk"] for r in ok[:10]}
    entran = [r["tk"] for r in ok[:10] if prev_rank.get(r["tk"], 99) > 10]
    salen = [tk for tk, p in prev_rank.items() if p <= 10 and tk not in ids]
    if prev_rank and (entran or salen):
        H.append("<p style='margin:0'><b>Cambios en el top 10:</b> " + ("entran " + ", ".join(entran) if entran else "") + ("; " if entran and salen else "") + ("salen " + ", ".join(salen) if salen else "") + "</p>")
    if sin_datos:
        H.append(f"<small>Sin datos nuevos en esta actualización (se mantuvo el dato anterior): {esc(', '.join(sin_datos))}.</small>")
    H.append("<small>“Precio vs. tendencia” compara el precio de hoy con la curva de crecimiento de los últimos 5 años. "
             "Es un análisis de datos pasados con tus criterios, no una recomendación de un asesor financiero.</small>")
    H.append("</section><!--/INFORME-->")
    return "".join(H)


# ---------------------------------------------------------------- panel "Mercado en vivo"
VIVO_CSS = """<style>
#vivo{display:grid;gap:12px;border:1px solid var(--rule);background:var(--surface);border-radius:12px;padding:16px 20px;min-width:0}
#vivo[hidden]{display:none}
#vivo .vh{display:flex;flex-wrap:wrap;align-items:baseline;justify-content:space-between;gap:6px 16px}
#vivo h2{margin:0;font-family:var(--display);font-weight:600;font-size:1.5rem}
#vivo .st{font-size:13px;color:var(--fg2);display:flex;align-items:center;gap:8px;flex-wrap:wrap}
#vivo .dot{width:8px;height:8px;border-radius:50%;background:var(--muted);display:inline-block}
#vivo .dot.on{background:var(--up);animation:vpulse 2s infinite}
@keyframes vpulse{50%{opacity:.35}}
#vivo .idx{font-family:var(--mono);font-size:13px;color:var(--fg)}
#vivo .tabs{display:flex;gap:4px;overflow-x:auto;scrollbar-width:none;border-bottom:1px solid var(--rule)}
#vivo .tabs button{font:inherit;font-size:13px;background:none;border:0;border-bottom:2px solid transparent;padding:6px 8px;color:var(--fg2);cursor:pointer;margin-bottom:-1px;white-space:nowrap}
#vivo .tabs button[aria-selected="true"]{color:var(--fg);border-bottom-color:var(--fit);font-weight:600}
#vivo .strip{display:grid;grid-auto-flow:column;grid-auto-columns:minmax(168px,1fr);gap:8px;overflow-x:auto;padding-bottom:4px;scrollbar-width:thin}
#vivo .q{border:1px solid var(--rule);border-radius:10px;padding:9px 11px;background:var(--bg);display:grid;gap:2px;font-size:12.5px;min-width:0}
#vivo .q .t{display:flex;justify-content:space-between;gap:6px;align-items:baseline}
#vivo .q b{font-size:14px}
#vivo .q .vk{font-family:var(--mono);font-size:11px;color:var(--muted);white-space:nowrap}
#vivo .q .px{font-family:var(--mono);font-size:15px;color:var(--fg)}
#vivo .q .r{display:flex;justify-content:space-between;gap:6px;color:var(--fg2);white-space:nowrap}
#vivo .q .r span:last-child{font-family:var(--mono)}
#vivo .up{color:var(--up)} #vivo .down{color:var(--down)}
#vivo svg{width:100%;height:30px;display:block}
#vivo small{color:var(--muted)}
@media (min-width:1100px){
  .wrap:has(#vivo:not([hidden])){grid-template-columns:minmax(0,1fr) minmax(0,1fr);column-gap:32px}
  .wrap:has(#vivo:not([hidden]))>*{grid-column:1/-1}
  .wrap:has(#vivo:not([hidden]))>header{grid-column:1;align-self:center}
  .wrap:has(#vivo:not([hidden]))>#vivo{grid-column:2;align-self:start;padding:14px 16px}
  #vivo .strip{grid-auto-columns:176px}
}
header p,.method div,#informe p,#informe small,#vivo>small{text-align:justify;hyphens:auto;-webkit-hyphens:auto}
#informe .cand p:not(.pq){text-align:left}
</style>"""

VIVO_JS = r"""<script>
(function(){
  const box = document.getElementById("vivo"); if (!box) return;
  const META = JSON.parse(box.dataset.meta);  // [ticker, puesto, puntaje, valor de tendencia]
  const byTk = Object.fromEntries(META.map(m => [m[0], m]));
  let Q = null, tab = "cand";
  const nf = (v, d) => v.toLocaleString("es-CL", {minimumFractionDigits: d, maximumFractionDigits: d});
  const pct = x => (x >= 0 ? "+" : "−") + nf(Math.abs(x) * 100, 2) + "%";
  const pxf = v => nf(v, v >= 1000 ? 0 : v >= 10 ? 1 : 2);
  const mm = v => v == null ? "s/d" : v >= 1e9 ? "$" + nf(v / 1e9, 1) + " mil mill." : v >= 1e6 ? "$" + nf(v / 1e6, 0) + " mill." : "$" + nf(v / 1e3, 0) + " mil";
  const chg = q => q[1] ? q[0] / q[1] - 1 : 0;
  function abierta(){
    const p = Object.fromEntries(new Intl.DateTimeFormat("en-US", {timeZone: "America/Santiago", weekday: "short", hour: "numeric", minute: "numeric", hourCycle: "h23"}).formatToParts(new Date()).map(x => [x.type, x.value]));
    const m = +p.hour * 60 + +p.minute;
    return !["Sat", "Sun"].includes(p.weekday) && m >= 570 && m < 960;
  }
  function spark(s, prev, up){
    if (!s || s.length < 2) return "";
    const lo = Math.min(...s, prev || Infinity), hi = Math.max(...s, prev || -Infinity), r = hi - lo || 1;
    const y = v => (28 - (v - lo) / r * 26).toFixed(1);
    const pts = s.map((v, i) => (i / (s.length - 1) * 100).toFixed(1) + "," + y(v)).join(" ");
    const base = prev ? `<line x1="0" x2="100" y1="${y(prev)}" y2="${y(prev)}" stroke="var(--muted)" stroke-dasharray="2 2" stroke-width="1" vector-effect="non-scaling-stroke"/>` : "";
    return `<svg viewBox="0 0 100 30" preserveAspectRatio="none" aria-hidden="true">${base}<polyline points="${pts}" fill="none" stroke="var(${up ? "--up" : "--down"})" stroke-width="1.5" vector-effect="non-scaling-stroke"/></svg>`;
  }
  function lista(){
    const con = META.filter(m => Q.q[m[0]]);
    const rk = con.filter(m => m[1]).sort((a, b) => a[1] - b[1]);
    const dev = m => m[3] ? Q.q[m[0]][0] / m[3] - 1 : null;
    if (tab === "top") return rk.slice(0, 12);
    if (tab === "cand") { const pr = m => m[2] + 50 * Math.min(Math.max(-dev(m), 0), 0.2) - (m[4] ? 3 : 0); return rk.slice(0, 12).filter(m => dev(m) != null && dev(m) <= 0.05).slice(0, 5).sort((a, b) => pr(b) - pr(a)); }
    if (tab === "alzas") return con.slice().sort((a, b) => chg(Q.q[b[0]]) - chg(Q.q[a[0]])).slice(0, 12);
    if (tab === "bajas") return con.slice().sort((a, b) => chg(Q.q[a[0]]) - chg(Q.q[b[0]])).slice(0, 12);
    return con.slice().sort((a, b) => (Q.q[b[0]][2] || 0) - (Q.q[a[0]][2] || 0)).slice(0, 12);
  }
  function pinta(){
    if (!Q) return;
    const ix = Q.q["^IPSA"], on = abierta();
    const t = new Date(Math.max(...Object.values(Q.q).map(q => q[3] || 0)) * 1000);
    const hora = t.toLocaleString("es-CL", {timeZone: "America/Santiago", weekday: "short", hour: "2-digit", minute: "2-digit"});
    box.querySelector(".st").innerHTML = `<span><span class="dot${on ? " on" : ""}"></span> ${on ? "Bolsa abierta" : "Bolsa cerrada"} · último dato ${hora}</span>` +
      (ix ? ` · <span class="idx">IPSA ${nf(ix[0], 2)} <span class="${chg(ix) >= 0 ? "up" : "down"}">${pct(chg(ix))}</span></span>` : "");
    const L = lista();
    box.querySelector(".strip").innerHTML = L.length ? L.map((m, i) => {
      const q = Q.q[m[0]], c = chg(q), d = m[3] ? q[0] / m[3] - 1 : null;
      return `<div class="q"><div class="t"><b>${m[0]}</b><span class="vk">${tab === "cand" ? (i + 1) + "ª" : m[1] ? "#" + m[1] : ""}</span></div><small>${m[1] ? nf(m[2], 1) + " pts" + (tab === "cand" ? " · #" + m[1] + " del ranking" : "") : "sin puesto en el ranking"}</small>` +
        `<div class="t"><span class="px">$${pxf(q[0])}</span><span class="${c >= 0 ? "up" : "down"}">${pct(c)}</span></div>` +
        spark(q[4], q[1], c >= 0) +
        `<div class="r"><span>Monto</span><span>${mm(q[2])}</span></div>` +
        (d != null ? `<div class="r"><span>vs. tendencia</span><span class="${d <= 0.05 ? "up" : d > 0.10 ? "down" : ""}">${Math.round(d * 100) === 0 ? "0%" : (d > 0 ? "+" : "−") + Math.abs(Math.round(d * 100)) + "%"}</span></div>` : "") + `</div>`;
    }).join("") : `<p class="sub" style="margin:0">Ninguna en este momento.</p>`;
  }
  box.querySelectorAll(".tabs button").forEach(b => b.onclick = () => {
    tab = b.dataset.k; box.querySelectorAll(".tabs button").forEach(x => x.setAttribute("aria-selected", x === b)); pinta();
  });
  async function carga(){
    try {
      const r = await fetch("precios.json?" + Date.now(), {cache: "no-store"});
      if (!r.ok) throw 0;
      Q = await r.json(); box.hidden = false; pinta();
    } catch (e) {}
  }
  carga(); setInterval(carga, 60000);
})();
</script>"""


def vivo_html(rows, ok):
    """Panel con precios del día (lee precios.json en el navegador). rows: todas las filas de la página; ok: su ranking."""
    pos = {r["tk"]: i + 1 for i, r in enumerate(ok)}
    meta = [[r["tk"], pos.get(r["tk"]), round(r["_T"], 1), (round(r["_tend"], 4) if r.get("_tend") else None), 1 if r["_mv"] < 1e8 else 0] for r in rows]
    tabs = [("cand", "Candidatas ahora"), ("top", "Top del ranking"), ("alzas", "Mayores alzas"), ("bajas", "Mayores bajas"), ("mont", "Más transadas")]
    return ("<!--VIVO-->" + VIVO_CSS +
            f"<section id=\"vivo\" hidden data-meta='{esc(json.dumps(meta, ensure_ascii=False))}'>"
            '<div class="vh"><h2>Mercado en vivo</h2><div class="st"></div></div>'
            '<div class="tabs" role="tablist">' + "".join(f'<button role="tab" data-k="{k}" aria-selected="{"true" if k == "cand" else "false"}">{t}</button>' for k, t in tabs) + "</div>"
            '<div class="strip"></div>'
            "<small>Precios del día desde Yahoo Finance (pueden venir con ~15–30 min de retraso). "
            "“vs. tendencia” recalcula con el precio de este momento cuánto está sobre o bajo su tendencia de 5 años; "
            "“Candidatas ahora” aplica la misma regla y el mismo orden de compra del informe con ese precio.</small>"
            "</section>" + VIVO_JS + "<!--/VIVO-->")


def nav_html(active):
    a = lambda href, txt, k: f'<a href="{href}" class="{"on" if k == active else ""}">{txt}</a>'
    return '<!--NAV--><nav class="topnav">' + a("index.html", "Bolsa de Santiago", "bolsa") + a("ipsa.html", "Solo IPSA", "ipsa") + "</nav><!--/NAV-->"


def ahora_cl(iso):
    d = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    try:
        from zoneinfo import ZoneInfo
        return d.astimezone(ZoneInfo("America/Santiago"))
    except Exception:
        return d - datetime.timedelta(hours=3)


def fecha_es(iso, hora=False):
    d = ahora_cl(iso)
    return f"{d.day} de {MESES_L[d.month - 1]} de {d.year}" + (f" a las {d.hour}:{d.minute:02d}" if hora else "")


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--page", required=True); ap.add_argument("--ipsa", required=True)
    ap.add_argument("--delta"); ap.add_argument("--full"); ap.add_argument("--universo")
    ap.add_argument("--out", required=True)
    ap.add_argument("--total", type=float, help="suma de control que devolvió delta.js (campo total)")
    ap.add_argument("--web", action="store_true", help="genera index.html/ipsa.html completos con informe y navegación")
    ap.add_argument("--verif", help="datos/verificados.json: datos confirmados con fuentes primarias (prioridad sobre Yahoo)")
    ap.add_argument("--fund", help="fund.json con utilidades, flujo de caja y dividendos pagados")
    ap.add_argument("--hist", help="historial.json con el ranking de cada día (para comparar con el día hábil anterior)")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    html = open(a.page, encoding="utf-8").read(); hip = open(a.ipsa, encoding="utf-8").read()
    prev_base = base_from_page(html)
    fund = json.load(open(a.fund)) if a.fund and os.path.exists(a.fund) else {}
    verif = json.load(open(a.verif)) if a.verif and os.path.exists(a.verif) else {}
    prev_rows = compute({k: dict(v) for k, v in prev_base.items()}, fund, verif)
    prev_ok = rank(prev_rows); prev_rank = {r["tk"]: r["_rk"] for r in prev_ok}
    sin = []
    if a.full:
        full = json.load(open(a.full)); uni = json.load(open(a.universo))
        base = base_from_full(full, uni); fecha = full["fecha"]
    else:
        delta = json.load(open(a.delta)); base = prev_base; fecha = delta["fecha"]
        if a.total is not None:
            def flat(x): return sum(flat(y) for y in x) if isinstance(x, list) else (x if isinstance(x, (int, float)) and not isinstance(x, bool) else 0)
            tot = round(sum(flat(v) for v in delta["data"].values()))
            if abs(tot - a.total) > max(2, 1e-9 * abs(a.total)):
                sys.exit(f"ERROR: la suma de control no coincide ({tot} vs {a.total}). Revisa la copia de los datos.")
            print(f"Suma de control OK ({tot})", file=sys.stderr)
        sin = apply_delta(base, delta)
    now = ahora_cl(fecha)
    yrs = [now.year - 5 + i for i in range(5)]
    fixes(base, yrs)
    aplicar_verificados(base, verif, yrs)
    rows = compute(base, fund, verif); ok = rank(rows)
    hoy = now.strftime("%Y-%m-%d")
    hist = {}
    if a.hist and os.path.exists(a.hist):
        hist = json.load(open(a.hist))
        antes = sorted(d for d in hist if d < hoy)
        if antes: prev_rank = hist[antes[-1]]
    m0 = next(iter(base.values()))["m0"]
    liq = {tk: b["lq"] for tk, b in base.items()}
    debt = {tk: b["fd"] for tk, b in base.items() if b["fd"]}
    ftxt = fecha_es(fecha, hora=a.web)
    out_rows = [clean(r) for r in sorted(rows, key=lambda r: (r["_rk"] is None, r["_rk"] or 0, -r["_T"]))]
    ip_rows = [r for r in out_rows if r["ipsa"]]
    rep = informe(ok, prev_rank, fecha_es(fecha, hora=True), sin)
    if a.web:
        ok_ip = [r for r in ok if r["ipsa"]]
        prev_ip = {}
        for tk, p in sorted(prev_rank.items(), key=lambda x: x[1]):
            if prev_base.get(tk, {}).get("ipsa"): prev_ip[tk] = len(prev_ip) + 1
        b1 = informe_html(ok, prev_rank, ftxt, sin, "Informe del día — Bolsa de Santiago")
        b2 = informe_html(ok_ip, prev_ip, ftxt, sin, "Informe del día — IPSA")
        open(os.path.join(a.out, "index.html"), "w", encoding="utf-8").write(patch_page(html, out_rows, liq, debt, m0, yrs, ftxt, b1, nav_html("bolsa"), vivo_html(rows, ok)))
        open(os.path.join(a.out, "ipsa.html"), "w", encoding="utf-8").write(patch_page(hip, ip_rows, liq, debt, m0, yrs, ftxt, b2, nav_html("ipsa"), vivo_html([r for r in rows if r["ipsa"]], ok_ip)))
    else:
        open(os.path.join(a.out, "ranking-bolsa.html"), "w", encoding="utf-8").write(patch_page(html, out_rows, liq, debt, m0, yrs, ftxt))
        open(os.path.join(a.out, "ranking-ipsa.html"), "w", encoding="utf-8").write(patch_page(hip, ip_rows, liq, debt, m0, yrs, ftxt))
    open(os.path.join(a.out, "informe.md"), "w", encoding="utf-8").write(rep)
    res = [{"tk": r["tk"], "rk": r["_rk"], "T": round(r["_T"], 1), "S": [round(x, 1) for x in r["_S"]], "dev": round(r["_dev"], 3)} for r in ok]
    json.dump({"fecha": fecha, "ranking": res}, open(os.path.join(a.out, "resumen.json"), "w"), ensure_ascii=False)
    if a.hist:
        hist[hoy] = {r["tk"]: r["_rk"] for r in ok}
        for d in sorted(hist)[:-40]: del hist[d]
        json.dump(hist, open(a.hist, "w"), ensure_ascii=False, separators=(",", ":"))
    print(rep)


if __name__ == "__main__":
    main()
