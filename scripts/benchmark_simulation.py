"""Benchmark reproducible de tiempo y memoria para Monte Carlo."""

import json
import time
import tracemalloc

import numpy as np
import pandas as pd

from config.simulation import MonteCarloConfig
from services.monte_carlo_service import MonteCarloService


def run_benchmark(simulation_count: int) -> dict[str, float | int]:
    rng = np.random.default_rng(20260730)
    matrix = pd.DataFrame(
        rng.normal(0.0004, 0.012, size=(252, 6)),
        columns=["A", "B", "C", "D", "E", "^MXX"],
    )
    config = MonteCarloConfig(
        simulation_count=simulation_count,
        horizons=[15],
        sample_path_count=0,
        regime_conditioning=True,
    )
    tracemalloc.start()
    started = time.perf_counter()
    cube, _, _ = MonteCarloService._simulate_cube(matrix, 15, config)
    asset_paths = cube[:, :, 0]
    benchmark_paths = cube[:, :, -1]
    terminal = MonteCarloService._terminal(asset_paths, config)
    benchmark_terminal = MonteCarloService._terminal(benchmark_paths, config)
    MonteCarloService._summarize(
        terminal,
        asset_paths,
        15,
        config,
        benchmark_terminal,
    )
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {
        "simulations": simulation_count,
        "seconds": round(elapsed, 6),
        "peak_memory_mb": round(peak / 1024 / 1024, 3),
        "cube_mb": round(cube.nbytes / 1024 / 1024, 3),
    }


if __name__ == "__main__":
    print(json.dumps([run_benchmark(item) for item in [2_000, 10_000, 50_000]], indent=2))
