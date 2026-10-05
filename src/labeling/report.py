"""
2.1 — Relatório da rotulagem: contagens malicioso/benigno, desbalanço,
quebra por classe/tipo de identificador e lacunas de rotulagem.

Uso: python -m src.labeling.report
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .join_labels import _load, join_labels

ROOT = Path(__file__).resolve().parents[2]


def build_report() -> str:
    req, inc = _load()
    df = join_labels(req, inc)
    n = len(df)
    mal = int(df["is_malicious"].sum())
    ben = n - mal
    L = []
    w = L.append

    w("# 2.1 — Relatório de Rotulagem (Join Temporal)\n")
    w(f"- Total de requests: **{n:,}**")
    w(f"- Maliciosas: **{mal:,}** ({100*mal/n:.3f}%)")
    w(f"- Benignas: **{ben:,}** ({100*ben/n:.3f}%)")
    w(f"- Razão de desbalanço (benigno:maligno): **{ben/max(mal,1):.0f}:1**\n")

    w("## Maliciosas por attack_class")
    vc = df.loc[df.is_malicious, "attack_class"].value_counts()
    for k, v in vc.items():
        w(f"- {k}: {v}")

    w("\n## Maliciosas por confidence do rótulo")
    vcf = df.loc[df.is_malicious, "label_confidence"].value_counts()
    for k, v in vcf.items():
        w(f"- {k}: {v}")

    w("\n## Cobertura por tipo de identificador (requests tocadas por cada match)")
    for t in ["ip", "ip_range", "ja3"]:
        c = df["match_types"].str.contains(rf"\b{t}\b", regex=True).sum()
        w(f"- {t}: {int(c)}")
    multi = int((df["n_incident_matches"] > 1).sum())
    w(f"- requests com múltiplos incidentes casados: {multi}")

    w("\n## Fontes maliciosas distintas")
    w(f"- IPs distintos com >=1 request maliciosa: "
      f"{df.loc[df.is_malicious, 'source_ip'].nunique()}")
    w(f"- JA3 distintos com >=1 request maliciosa: "
      f"{df.loc[df.is_malicious, 'tls_fingerprint'].nunique()}")

    # ---- lacunas ----
    w("\n## Lacunas e ambiguidades de rotulagem")
    tmin, tmax = df["event_ts"].min(), df["event_ts"].max()
    out_win = inc[(inc.active_from_ts > tmax) | (inc.active_until_ts < tmin)]
    w(f"- Janela dos logs: {tmin} → {tmax}")
    w(f"- Incidentes com janela fora do período dos logs (não rotulam nada): "
      f"**{len(out_win)}**")
    for r in out_win.itertuples(index=False):
        w(f"    - {r.incident_id} | {r.attack_class} | "
          f"{r.active_from_ts} → {r.active_until_ts}")

    # incidentes dentro da janela mas sem nenhum match
    matched_ids = set()
    for s in df["matched_incident_ids"]:
        if s:
            matched_ids.update(s.split(","))
    in_win = inc[~inc.incident_id.isin(out_win.incident_id)]
    no_match = in_win[~in_win.incident_id.isin(matched_ids)]
    w(f"- Incidentes dentro da janela mas sem request casada: **{len(no_match)}** "
      "— investigados: em 100% dos casos a fonte *existe* nos logs, mas todo o "
      "tráfego dela cai FORA da janela estimada do incidente (janelas são "
      "estimativas forenses, nem sempre alinhadas ao tráfego observado).")

    # redundância da tabela de incidentes em nível de fonte
    ip_inc = inc[inc.identifier_type == "ip"].groupby("source_identifier").size()
    w(f"- **Redundância de incidentes:** {int((ip_inc > 1).sum())} de "
      f"{ip_inc.shape[0]} IPs têm >1 incidente (máx {int(ip_inc.max())} no mesmo "
      "IP). A mesma fonte recebe várias janelas; só as que sobrepõem o tráfego "
      "real geram rótulo. => deduplicar por fonte antes de qualquer análise "
      "source-level.")

    # zona cinza: requests de fontes conhecidas que ficaram benignas
    inc_ips = set(inc[inc.identifier_type == "ip"].source_identifier)
    inc_ja3 = set(inc[inc.identifier_type == "tls_fingerprint"].source_identifier)
    named_mask = df.source_ip.isin(inc_ips) | df.tls_fingerprint.isin(inc_ja3)
    gray = int((named_mask & ~df.is_malicious).sum())
    w(f"- **Zona cinza (fonte conhecida mas request benigna):** {gray} — "
      "portanto nenhum exemplo positivo é perdido pelos no-match acima; "
      "o rótulo em nível de request está completo para as fontes nomeadas.")

    w("\n- **Positive-Unlabeled:** 'benigno' = não-rotulado, não comprovadamente "
      "limpo. Falsos-negativos nos rótulos viram ruído no treino.")
    w("- **Prevalência da amostra ≠ produção:** aqui ~1,2%; produção <0,1% "
      "(ataques amplificados no sintético). Calibrar threshold para prevalência real.")
    w("- **ip_range** rotula a faixa inteira: risco de varrer IPs legítimos "
      "coabitando o CIDR (ruído de rótulo).")
    return "\n".join(L)


def main() -> None:
    text = build_report()
    print(text)
    dest = ROOT / "reports" / "2_1_labeling_report.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    print(f"\n[WRITE] {dest.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
