"""
2.4 — Export do modelo para o edge (código sem dependências).

Gera JavaScript puro (Cloudflare Workers / WASM-friendly) a partir do LightGBM
sem country, cujo pré-processamento é passthrough (o classificador consome
diretamente as 35 features numéricas, em ordem conhecida). Sem runtime de ML no
edge: só comparações de árvore compiladas.

Uso: python -m src.deploy.export_edge
"""
from __future__ import annotations

import json
from pathlib import Path

import joblib
import m2cgen as m2c

from ..modeling.split import feature_columns, load_features

ROOT = Path(__file__).resolve().parents[2]
MODELS = ROOT / "models"
OUT = ROOT / "models" / "edge"


def main():
    pipe = joblib.load(MODELS / "lgbm_nocountry.joblib")
    clf = pipe.named_steps["clf"]
    # ordem das features que o classificador espera (pré-proc = passthrough)
    feat_order = list(pipe.named_steps["pre"].get_feature_names_out())
    feat_order = [f.split("__")[-1] for f in feat_order]

    OUT.mkdir(parents=True, exist_ok=True)
    js = m2c.export_to_javascript(clf, function_name="scoreRequest")
    (OUT / "edge_model.js").write_text(js, encoding="utf-8")
    (OUT / "feature_order.json").write_text(
        json.dumps(feat_order, indent=2), encoding="utf-8")

    size_kb = round((OUT / "edge_model.js").stat().st_size / 1024, 1)
    print(f"[WRITE] models/edge/edge_model.js  ({size_kb} KB)")
    print(f"[WRITE] models/edge/feature_order.json  ({len(feat_order)} features)")
    print(f"Ordem esperada das features: {feat_order}")


if __name__ == "__main__":
    main()
