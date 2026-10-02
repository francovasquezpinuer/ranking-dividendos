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
    """Correcciones manuales conocidas de Yahoo."""
    if "CHILE" in base and 2024 in yrs:
        i = yrs.index(2024)
        if base["CHILE"]["dy"][i] < 1: base["CHILE"]["dy"][i] = 8.08  # faltaba en Yahoo (verificado)
    if "SOQUICOM" in base:
        if (base["SOQUICOM"]["t"] or 0) > 1000: base["SOQUICOM"]["t"] = 25.23
        if base["SOQUICOM"]["p"] is not None and base["SOQUICOM"]["p"] > 2: base["SOQUICOM"]["p"] = None
    if "PAMPA" in base:  # Yahoo informa sus dividendos en otra moneda
        base["PAMPA"]["dy"] = [0, 0, 0, 0, 0]; base["PAMPA"]["t"] = 0
    for b in base.values():
        if b["p"] is not None and (b["p"] > 2): b["p"] = None


# ---------------------------------------------------------------- cálculos
def compute(base):
    rows = []
    for tk, b in base.items():
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
        s3 = 30 * (dr + 1) / 2 if dav > 0 else 0
        s4 = 25 * (pr + 1) / 2
        s7 = 15 * clamp(0.6 - rcv, 0, 0.6)
        s1 = 15 * min(max(yt, 0) / 0.07, 1)
        s8 = 0 if po is None or po <= 0 else 10 if .40 <= po <= .75 else 7 if (.30 <= po < .40 or .75 < po <= .90) else 4 if (.20 <= po < .30 or .90 < po <= 1) else 0
        sec = SECTOR_FIX.get(tk, b["sec"])
        r = dict(tk=tk, sec=b["sec"], name=b["name"], ipsa=b["ipsa"], pm=round(pm, 4), pb=round(pb, 4), pr=round(pr, 4), g=round(g, 4),
                 dm=round(dm, 4), db=round(db, 4), dr=round(dr, 4), dav=round(dav, 4), rcv=round(rcv, 4), yt=round(yt, 4),
                 po=None if po is None else round(po, 4), last=last, s3=round(s3, 4), s4=round(s4, 4), s7=round(s7, 4), s1=round(s1, 4),
                 s8=s8, s6=0, v=b["c"], d=b["dy"], t=b["t"], s=s, flat=round(flat, 4), liq=flat <= 0.4)
        r["why"] = why_ing(r)
        r["_sec2"] = sec; r["_mv"] = (b["lq"] or [0, 0])[1]; r["_fd"] = b["fd"]; r["_tend"] = tend; r["_k"] = k
        rows.append(r)
    return rows


def why_ing(r):
    f, c = [], []
    if r["pr"] >= .9: f.append(f"precio muy firme al alza (r {nf(r['pr'], 2)})")
    elif r["pr"] >= .6: f.append(f"precio al alza (r {nf(r['pr'], 2)})")
    elif r["pr"] < 0: c.append(f"precio a la baja (r {nf(r['pr'], 2)})")
    else: c.append(f"precio sin tendencia clara (r {nf(r['pr'], 2)})")
    if r["dav"] <= 0: c.append("no pagó dividendos")
    else:
        if r["dr"] >= .8: f.append(f"dividendo que sube de forma firme (r {nf(r['dr'], 2)})")
        elif r["dr"] >= .4: f.append(f"dividendo al alza (r {nf(r['dr'], 2)})")
        elif r["dr"] < -.2: c.append(f"dividendo a la baja (r {nf(r['dr'], 2)})")
        else: c.append(f"dividendo sin tendencia (r {nf(r['dr'], 2)})")
        if r["rcv"] < .2: f.append("pagos muy parejos")
        elif r["rcv"] > .5: c.append("dividendo con saltos grandes entre años")
    if r["yt"] >= .06: f.append(f"rinde alto ({nf(r['yt'] * 100, 1)}%)")
    elif r["dav"] > 0 and r["yt"] < .02: c.append(f"rinde poco ({nf(r['yt'] * 100, 1)}%)")
    if r["po"] is not None and r["po"] > 1: c.append(f"paga más de lo que gana ({nf(r['po'] * 100, 0)}%)")
    return (("A favor: " + ", ".join(f[:3]) + ".") if f else "") + ((" " if f else "") + "En contra: " + ", ".join(c[:3]) + "." if c else "")


# --- puntaje modo Crecimiento (idéntico al de la página)
def pay_high(p): return 11 * (0 if p is None or p <= 0 or p > 1 else .4 if p >= .90 else .75 if p > .75 else 1 if p >= .50 else .75 if p >= .40 else .4 if p >= .30 else .15 if p >= .20 else 0)


def debt_info(r):
    d = r["_fd"]
    if not d: return ("na", None)
    cash, debt, eb, roa, roe, de = d
    if r["_sec2"] == "Banca" or r["sec"] == "Banca" or r["tk"] in FINS:
        return ("cap", roa / roe) if roa and roe and roa > 0 and roe > 0 else ("na", None)
    if debt is not None and cash is not None and debt <= cash: return ("nd", -1)
    if eb is None: return ("de", de / 100) if de is not None else (("nd", -1) if debt == 0 else ("na", None))
    if eb <= 0: return ("neg", None)
    return ("nd", (debt - cash) / eb)


def debt_pts(r, mx=11):
    t, x = debt_info(r)
    return mx * clamp(x, .06, .10) if t == "cap" else mx * (1 - clamp(x, 1, 5)) if t == "nd" else mx * (1 - clamp(x, .5, 1.5)) if t == "de" else 0


def chw(r): return (r["yt"] or 0) + (max(-0.1, min(0.10, r["dm"] / r["dav"])) if r["dav"] > 0 else 0)


def score_crec(r):
    S = [16 * (r["pr"] + 1) / 2,
         11 * clamp(r["g"], 0, .30),
         11 * (r["dr"] + 1) / 2 if r["dav"] > 0 else 0,
         11 * clamp(r["dm"] / r["dav"], 0, .20) if r["dav"] > 0 else 0,
         pay_high(r["po"]),
         11 * clamp(0.6 - r["rcv"], 0, 0.6),
         11 * clamp(chw(r), .05, .17),
         debt_pts(r),
         7 * clamp(math.log10(max(r["_mv"], 1)), math.log10(5e6), 9)]
    return S, sum(S)


CRIT = ["Tendencia precio", "Crecimiento precio", "Tendencia dividendo", "Crecimiento dividendo", "% de pago sano", "Constancia",
        "Rendimiento + crecimiento", "Deuda", "Liquidez"]


def rank(rows):
    ok = [r for r in rows if r["liq"] and r["_mv"] >= 5e6]
    for r in rows: r["_S"], r["_T"] = score_crec(r); r["_rk"] = None
    for i, r in enumerate(sorted(ok, key=lambda r: -r["_T"])): r["_rk"] = i + 1
    return sorted(ok, key=lambda r: r["_rk"])


# ---------------------------------------------------------------- páginas
def label(m): return f"{MESES[m % 12]} {m // 12}"


WEB_HEAD = '<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">'


def patch_page(html, rows, liq, debt, m0, yrs, fecha_txt, informe_block=None, nav=None):
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
        html = html.replace('<div class="wrap">', '<div class="wrap">' + (nav or ""), 1)
        html = html.replace("</header>", "</header>" + informe_block, 1)
    return html


def clean(r): return {k: v for k, v in r.items() if not k.startswith("_")}


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
    L.append("**Candidatas para comprar hoy según tus criterios** (entre las 12 mejores del ranking, las 5 de mayor puntaje cuyo precio está a no más de 5% sobre su tendencia de 5 años):")
    if cand:
        for r in cand:
            L.append(f"- **{r['tk']}** ({nf(r['_T'], 1)} pts, puesto {r['_rk']}): precio {sgn_pct(r['_dev'])} vs. su tendencia; "
                     f"rinde {nf(r['yt'] * 100, 1)}% en 12 meses; payout {('s/d' if r['po'] is None else nf(r['po'] * 100, 0) + '%')}"
                     + ("; ojo: liquidez baja" if r["_mv"] < 1e8 else "") + ".")
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
#informe .cands{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px}
#informe .cand{border:1px solid var(--rule);border-radius:10px;padding:10px 12px;background:var(--bg)}
#informe .cand b{font-size:15px}
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
         '<div><b>Candidatas para comprar hoy según tus criterios</b><p class="sub">Entre las 12 mejores del ranking, las 5 de mayor puntaje cuyo precio está a no más de 5% sobre su tendencia de 5 años.</p></div>']
    if cand:
        H.append('<div class="cands">')
        for r in cand:
            H.append(f'<div class="cand"><b>{esc(r["tk"])}</b><span class="pts">{nf(r["_T"], 1)} pts · #{pos[r["tk"]]}</span>'
                     f'<p>Precio {sgn_pct(r["_dev"])} vs. su tendencia<br>Rinde {nf(r["yt"] * 100, 1)}% en 12 meses<br>'
                     f'Payout {"s/d" if r["po"] is None else nf(r["po"] * 100, 0) + "%"} · liquidez {tier(r["_mv"])}'
                     + ('<br><span class="warn">Ojo: se transa poco</span>' if r["_mv"] < 1e8 else "") + "</p></div>")
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
    ap.add_argument("--hist", help="historial.json con el ranking de cada día (para comparar con el día hábil anterior)")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    html = open(a.page, encoding="utf-8").read(); hip = open(a.ipsa, encoding="utf-8").read()
    prev_base = base_from_page(html)
    prev_rows = compute({k: dict(v) for k, v in prev_base.items()})
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
    rows = compute(base); ok = rank(rows)
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
        open(os.path.join(a.out, "index.html"), "w", encoding="utf-8").write(patch_page(html, out_rows, liq, debt, m0, yrs, ftxt, b1, nav_html("bolsa")))
        open(os.path.join(a.out, "ipsa.html"), "w", encoding="utf-8").write(patch_page(hip, ip_rows, liq, debt, m0, yrs, ftxt, b2, nav_html("ipsa")))
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
