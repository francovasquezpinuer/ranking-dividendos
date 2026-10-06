#!/usr/bin/env python3
"""Precios del día (casi en vivo) para el panel "Mercado en vivo": escribe site/precios.json.

Lo ejecuta .github/workflows/precios.yml cada ~10 minutos en horario de bolsa, y también
actualizar.yml en cada actualización del ranking. Solo usa la biblioteca estándar.
Formato: {"t": iso_utc, "q": {ticker: [precio, cierre_anterior, monto_transado, hora_unix, [serie intradía]]}}
"""
import json, os, sys, time, datetime, urllib.parse
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from update import get_json, crumb, RAIZ, SITE  # noqa: E402

INDICE = "^IPSA"


def p5(x): return None if x is None else float(f"{x:.5g}")


def cotiza(tk):
    sym = urllib.parse.quote(tk if tk.startswith("^") else tk.replace(" ", "-") + ".SN")
    j = get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=1d&interval=5m")
    res = (((j or {}).get("chart") or {}).get("result") or [None])[0]
    if not res: return tk, None
    m = res.get("meta") or {}
    px, prev = m.get("regularMarketPrice"), m.get("chartPreviousClose") or m.get("previousClose")
    if not px: return tk, None
    cl = [c for c in (((res.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []) if c is not None]
    if len(cl) > 40:  # se reduce la serie a ~40 puntos para que el archivo sea liviano
        paso = len(cl) / 40
        cl = [cl[int(i * paso)] for i in range(40)] + [cl[-1]]
    vol = m.get("regularMarketVolume") or 0
    return tk, [p5(px), p5(prev), round(px * vol) if vol else None, m.get("regularMarketTime"), [p5(c) for c in cl]]


def main():
    uni = [u[0] for u in json.load(open(os.path.join(RAIZ, "universo.json")))] + [INDICE]
    crumb()  # deja la cookie de Yahoo
    with ThreadPoolExecutor(8) as ex:
        q = {tk: o for tk, o in ex.map(cotiza, uni) if o}
    print(f"precios en vivo: {len(q)}/{len(uni)}")
    if len(q) < len(uni) * 0.5:
        sys.exit("Muy pocas cotizaciones; se conserva el archivo anterior.")
    out = {"t": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"), "q": q}
    json.dump(out, open(os.path.join(SITE, "precios.json"), "w"), ensure_ascii=False, separators=(",", ":"))


if __name__ == "__main__":
    main()
