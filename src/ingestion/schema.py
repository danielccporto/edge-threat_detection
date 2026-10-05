"""
Contratos de schema e mapeamentos de padronização das 3 tabelas brutas.

Padronização LEVE: preservamos os nomes originais do enunciado, exceto as
colunas de tempo, que recebem sufixo de tipo (`_ts` p/ datetime UTC, `_date`
p/ data). Todo o de/para fica documentado aqui — fonte única de verdade.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# De/para de nomes (padronização leve — apenas colunas temporais)
# ---------------------------------------------------------------------------
REQUESTS_RENAME: dict[str, str] = {
    "timestamp": "event_ts",
}
HEADERS_RENAME: dict[str, str] = {}  # já consistente
INCIDENTS_RENAME: dict[str, str] = {
    "active_from": "active_from_ts",
    "active_until": "active_until_ts",
    "labeled_at": "labeled_at_date",
}

# ---------------------------------------------------------------------------
# Colunas por tipo-alvo (aplicadas APÓS o rename)
# ---------------------------------------------------------------------------
DATETIME_UTC_COLS = {
    "http_requests": ["event_ts"],
    "request_headers": [],
    "incident_labels": ["active_from_ts", "active_until_ts"],
}
DATE_COLS = {
    "incident_labels": ["labeled_at_date"],
}
INT_COLS = {
    "http_requests": ["status_code", "response_time_ms", "body_size_bytes"],
}
CATEGORICAL_COLS = {
    "http_requests": ["method", "country", "tls_fingerprint"],
    "request_headers": ["header_name"],
    "incident_labels": ["identifier_type", "attack_class"],
}

# confidence é categórico ORDENADO (vira peso de amostra no treino)
CONFIDENCE_ORDER = ["low", "medium", "high"]

# ---------------------------------------------------------------------------
# Chaves primárias (unicidade validada no contrato)
# ---------------------------------------------------------------------------
PRIMARY_KEYS = {
    "http_requests": ["request_id"],
    "request_headers": ["request_id", "header_name"],
    "incident_labels": ["incident_id"],
}

# Colunas que não podem ter nulos (integridade mínima)
NON_NULL_COLS = {
    "http_requests": [
        "request_id", "event_ts", "source_ip", "method", "path",
        "status_code", "tls_fingerprint",
    ],
    "request_headers": ["request_id", "header_name"],
    "incident_labels": [
        "incident_id", "source_identifier", "identifier_type",
        "attack_class", "active_from_ts", "active_until_ts",
    ],
}

# Domínios esperados (valida que não surgiram categorias inesperadas)
EXPECTED_DOMAINS = {
    "incident_labels.identifier_type": {"ip", "ip_range", "tls_fingerprint"},
    "incident_labels.confidence": set(CONFIDENCE_ORDER),
}
