# Ranking de acciones dividenderas — Bolsa de Santiago

Página que se actualiza sola con datos de Yahoo Finance: ranking de 110 acciones de la Bolsa de Santiago
(y vista solo IPSA) según los criterios de Franco, con un informe diario de candidatas para comprar.

- `site/` — la página publicada (GitHub Pages): `index.html` (Bolsa), `ipsa.html` (IPSA), `informe.md`, `historial.json`.
- `scripts/update.py` — descarga los datos del día y llama a `pipeline.py`.
- `scripts/pipeline.py` — calcula regresiones, puntajes y el informe; regenera las páginas.
- `.github/workflows/actualizar.yml` — corre `update.py` los días hábiles cada ~2 horas y publica.

Para actualizar a mano: pestaña **Actions** → **Actualizar ranking** → **Run workflow**.

Análisis de datos pasados con criterios propios; no es una recomendación de un asesor financiero.
