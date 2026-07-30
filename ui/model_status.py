"""Pantalla de salud, reproducibilidad y CI del modelo."""

import json
from urllib.error import URLError
from urllib.request import Request, urlopen

import streamlit as st
from sqlalchemy.orm import Session

from config.model_status import GITHUB_REPOSITORY
from services.model_status_service import ModelStatusService


@st.cache_data(ttl=60)
def github_actions_status() -> tuple[str, str]:
    url = (
        f"https://api.github.com/repos/{GITHUB_REPOSITORY}/"
        "actions/workflows/quality.yml/runs?per_page=1"
    )
    request = Request(url, headers={"User-Agent": "simulador-inversiones-1mdp"})
    try:
        with urlopen(request, timeout=3) as response:  # noqa: S310
            payload = json.loads(response.read())
        run = payload["workflow_runs"][0]
        status = run.get("conclusion") or run.get("status", "unknown")
        return str(status).upper(), str(run["html_url"])
    except (OSError, URLError, KeyError, IndexError, json.JSONDecodeError):
        return "NO DISPONIBLE", (
            f"https://github.com/{GITHUB_REPOSITORY}/actions/workflows/quality.yml"
        )


def render(session: Session, benchmark_symbol: str) -> None:
    st.header("Estado del Modelo")
    state = ModelStatusService(session).snapshot(benchmark_symbol)
    actions, actions_url = github_actions_status()
    columns = st.columns(4)
    cards = [
        ("Versión", state["version"]),
        ("Cobertura", f"{state['coverage']:.2f}%"),
        ("Pruebas", state["tests"]),
        ("GitHub Actions", actions),
        ("Fecha de datos", state["data_date"] or "Sin datos"),
        ("Benchmark", state["benchmark"]),
        ("Régimen", state["regime"]),
        ("Método Monte Carlo", state["monte_carlo_method"]),
        ("Horizonte", state["horizon"]),
        ("Semilla", state["seed"]),
    ]
    for index, (label, value) in enumerate(cards):
        columns[index % 4].metric(label, value)
    st.caption(f"Firma de datos de la última ejecución: {state['data_signature']}")
    st.link_button("Abrir GitHub Actions", actions_url)
