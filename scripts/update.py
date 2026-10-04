#!/usr/bin/env python3
"""Descarga los datos del día desde Yahoo Finance y regenera el sitio (site/index.html y site/ipsa.html).

Lo ejecuta GitHub Actions (.github/workflows/actualizar.yml). Solo usa la biblioteca estándar de Python.
También se puede correr a mano:  python3 scripts/update.py
"""
import json, os, sys, time, datetime, subprocess, statistics, http.cookiejar, urllib.request, urllib.parse
from concurrent.futures import ThreadPoolExecutor
from zoneinfo import ZoneInfo

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(RAIZ, "site")
TZ = ZoneInfo("America/Santiago")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"

jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
opener.addheaders = [("User-Agent", UA), ("Accept", "application/json,text/plain,*/*"), ("Accept-Language", "en-US,en;q=0.9")]


def get(url, tries=3):
    for k in range(tries):
        try:
            with opener.open(url, timeout=25) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (404, 400): return None
            time.sleep(1.5 * (k + 1))
        except Exception:
            time.sleep(1.5 * (k + 1))
    return None


def get_json(url):
    b = get(url)
    try: return json.loads(b) if b else None
    except Exception: return None


def crumb():
    try: opener.open("https://fc.yahoo.com", timeout=20)
    except Exception: pass  # responde 404 pero deja la cookie
    for host in ("query1", "query2"):
        b = get(f"https://{host}.finance.yahoo.com/v1/test/getcrumb")
        if b and len(b) < 50 and b"<" not in b: return b.decode()
    return None


def mes(ts): d = datetime.datetime.fromtimestamp(ts, TZ); return d.year * 12 + d.month - 1


def p5(x): return None if x is None else float(f"{x:.5g}")


def raw(x): return x.get("raw") if isinstance(x, dict) else None


def uno(tk, cr, ahora):
    sym = urllib.parse.quote(tk.replace(" ", "-") + ".SN")
    o = [None] * 9
    Y = ahora.year; yrs = [Y - 5 + i for i in range(5)]; mk = Y * 12 + ahora.month - 1; now_s = ahora.timestamp()
    j = get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=6y&interval=1mo&events=div")
    res = (((j or {}).get("chart") or {}).get("result") or [None])[0]
    if res and res.get("timestamp"):
        cl = res["indicators"]["quote"][0].get("close") or []; by = {}
        for t, c in zip(res["timestamp"], cl):
            if c is not None: by[mes(t + 12 * 3600)] = c  # +12 h: evita errores de huso horario en el día 1
        px = (res.get("meta") or {}).get("regularMarketPrice")
        if px: by[mk] = px
        o[0], o[1], o[2], o[3] = mk - 1, p5(by.get(mk - 1)), mk, p5(by.get(mk))
        dv = list(((res.get("events") or {}).get("dividends") or {}).values())
        o[4] = [p5(sum(e["amount"] for e in dv if datetime.datetime.fromtimestamp(e["date"], TZ).year == y)) for y in yrs]
        o[5] = p5(sum(e["amount"] for e in dv if e["date"] > now_s - 365 * 86400))
    if cr:
        q = get_json(f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{sym}?modules=summaryDetail,financialData&crumb={urllib.parse.quote(cr)}")
        qr = (((q or {}).get("quoteSummary") or {}).get("result") or [None])[0]
        if qr:
            sd, f = qr.get("summaryDetail") or {}, qr.get("financialData") or {}
            o[6] = None if raw(sd.get("payoutRatio")) is None else round(raw(sd.get("payoutRatio")), 4)
            o[7] = [p5(raw(f.get(k))) for k in ("totalCash", "totalDebt", "ebitda", "returnOnAssets", "returnOnEquity", "debtToEquity")]
    lj = get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=1y&interval=1d")
    lr = (((lj or {}).get("chart") or {}).get("result") or [None])[0]
    if lr and lr.get("indicators"):
        qq = lr["indicators"]["quote"][0]
        m = [c * v for c, v in zip(qq.get("close") or [], qq.get("volume") or []) if c is not None and v is not None]
        if m: o[8] = [round(sum(m) / len(m)), round(statistics.median(m))]
    return tk, o


TS_TYPES = ["annualNetIncomeCommonStockholders", "annualFreeCashFlow", "annualCashDividendsPaid"]
TS_KEYS = {"annualNetIncomeCommonStockholders": "ni", "annualFreeCashFlow": "fcf", "annualCashDividendsPaid": "dp"}


def fundamentos(tk):
    """Utilidad neta, flujo de caja libre y dividendos pagados anuales (últimos ~5 años) desde Yahoo."""
    sym = urllib.parse.quote(tk.replace(" ", "-") + ".SN")
    p2 = int(time.time()); p1 = p2 - 7 * 365 * 86400
    j = get_json(f"https://query1.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/{sym}"
                 f"?symbol={sym}&type={','.join(TS_TYPES)}&period1={p1}&period2={p2}&merge=false&padTimeSeries=true")
    out = {}
    for res in (((j or {}).get("timeseries") or {}).get("result") or []):
        t = ((res.get("meta") or {}).get("type") or [None])[0]
        if t not in TS_KEYS: continue
        pts = [[x["asOfDate"], (x.get("reportedValue") or {}).get("raw")] for x in (res.get(t) or []) if x and x.get("asOfDate")]
        pts = [p for p in pts if p[1] is not None]
        if pts: out[TS_KEYS[t]] = sorted(pts)[-5:]
    return tk, out


def actualizar_fundamentos(uni, ahora):
    """Una vez al día: refresca site/fund.json (si Yahoo no responde para una acción, se conserva lo anterior)."""
    ruta = os.path.join(SITE, "fund.json")
    fund = json.load(open(ruta)) if os.path.exists(ruta) else {}
    hoy = ahora.strftime("%Y-%m-%d")
    if fund.get("_fecha") == hoy: return
    with ThreadPoolExecutor(6) as ex:
        res = dict(ex.map(lambda u: fundamentos(u[0]), uni))
    n = 0
    for tk, o in res.items():
        if o: fund[tk] = o; n += 1
    fund["_fecha"] = hoy
    json.dump(fund, open(ruta, "w"), ensure_ascii=False, separators=(",", ":"))
    print(f"fundamentos (utilidades, flujo de caja, dividendos pagados): {n}/{len(uni)}")


def main():
    uni = json.load(open(os.path.join(RAIZ, "universo.json")))
    ahora = datetime.datetime.now(TZ)
    cr = crumb()
    print("crumb:", "ok" if cr else "NO (se mantienen payout y deuda anteriores)")
    with ThreadPoolExecutor(6) as ex:
        data = dict(ex.map(lambda u: uno(u[0], cr, ahora), uni))
    con_precio = sum(1 for v in data.values() if v[3] is not None)
    print(f"acciones con precio: {con_precio}/{len(data)}")
    if con_precio < len(data) * 0.5:
        sys.exit("Muy pocas acciones con datos; no se actualiza el sitio (Yahoo puede estar bloqueando).")
    for v in data.values():  # si no llegó payout/deuda, se conserva el dato anterior
        if v[7] is None: v[6] = "keep"
    actualizar_fundamentos(uni, ahora)
    delta = {"fecha": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"), "data": data}
    tmp = os.path.join(RAIZ, ".delta.json")
    json.dump(delta, open(tmp, "w"))
    r = subprocess.run([sys.executable, os.path.join(RAIZ, "scripts", "pipeline.py"), "--web",
                        "--page", os.path.join(SITE, "index.html"), "--ipsa", os.path.join(SITE, "ipsa.html"),
                        "--delta", tmp, "--fund", os.path.join(SITE, "fund.json"), "--verif", os.path.join(RAIZ, "datos", "verificados.json"), "--hist", os.path.join(SITE, "historial.json"), "--out", SITE])
    os.remove(tmp)
    sys.exit(r.returncode)


if __name__ == "__main__":
    main()
