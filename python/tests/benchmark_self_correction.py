import asyncio
import json
import logging
import os
import sys

# Add python dir to path
sys.path.append(os.path.join(os.getcwd(), "python"))

from seahorse_ai.rag import get_pipeline
from seahorse_ai.tools.memory import memory_feedback

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("benchmark")

CONFIG_PATH = "python/tests/benchmark_config.json"


async def run_scenario(scenario: dict, feedback_mode: str):
    """
    Run a single benchmark scenario.
    feedback_mode: "baseline", "single", "quorum"
    """
    pipeline = get_pipeline()
    pipeline._use_rust = True  # Ensure Rust mode is tested (Metadata Atomic Update Support)
    await pipeline.clear()  # Reset for clean run

    # 1. Inject Facts
    await pipeline.store(scenario["true_fact"], importance=1, metadata={"source": "truth"})
    await pipeline.store(scenario["noisy_fact"], importance=5, metadata={"source": "noise"})

    # Get IDs (in simple HNSW/Qdrant these will likely be 0 and 1)
    # 2. Find IDs for Feedback
    # Search for the exact text to find IDs
    true_search = await pipeline.search(scenario["true_fact"], k=1)
    noise_search = await pipeline.search(scenario["noisy_fact"], k=1)

    true_id = true_search[0]["id"] if true_search else None
    noise_id = noise_search[0]["id"] if noise_search else None
    if noise_id is None:
        logger.error(
            f"Failed to find noise_id for {scenario['id']}. True search: {true_search}, Noise search: {noise_search}"
        )
        return {
            "scenario_id": scenario["id"],
            "mode": feedback_mode,
            "p_at_1": 0.0,
            "mrr": 0.0,
            "noise_rank": 99,
            "top_source": "ERROR",
        }

    # 2. Apply Feedback
    if feedback_mode == "single":
        await memory_feedback(noise_id, penalty=1.0, reason="Inaccurate", role="WORKER")
    elif feedback_mode == "quorum":
        await memory_feedback(noise_id, penalty=1.0, reason="Inaccurate", role="WORKER")
        await memory_feedback(noise_id, penalty=1.0, reason="Confirmed", role="COMMANDER")
        await memory_feedback(noise_id, penalty=1.0, reason="Verified", role="SCOUT")

    # 3. Final Retrieval with Reranking
    final_results = await pipeline.search(scenario["query"], k=5)
    logger.info(f"[{feedback_mode}] Final results for '{scenario['query']}':")
    for i, res in enumerate(final_results):
        logger.info(
            f"  {i + 1}. ID={res['id']} Score={res.get('score', 'N/A')} Source={res['metadata'].get('source')} Text={res['text'][:30]}..."
        )

    # Metrics
    if not final_results:
        logger.warning(f"[{feedback_mode}] No results returned!")
        return {
            "scenario_id": scenario["id"],
            "mode": feedback_mode,
            "p_at_1": 0.0,
            "mrr": 0.0,
            "noise_rank": 99,
            "top_source": "NONE",
        }

    top_result = final_results[0]
    p_at_1 = 1.0 if top_result["metadata"].get("source") == "truth" else 0.0

    noise_rank = 99
    for i, res in enumerate(final_results):
        if res["metadata"].get("source") == "noise":
            noise_rank = i + 1
            break

    mrr = 1.0 / noise_rank if noise_rank <= 5 else 0.0

    return {
        "scenario_id": scenario["id"],
        "mode": feedback_mode,
        "p_at_1": p_at_1,
        "mrr": mrr,
        "noise_rank": noise_rank,
        "top_source": top_result["metadata"].get("source"),
    }


async def run_benchmark():
    with open(CONFIG_PATH) as f:
        config = json.load(f)

    all_results = []
    modes = ["baseline", "single", "quorum"]

    print(f"{'Scenario':<25} | {'Mode':<10} | {'P@1':<5} | {'Noise Rank':<10}")
    print("-" * 60)

    for scenario in config["scenarios"]:
        for mode in modes:
            res = await run_scenario(scenario, mode)
            all_results.append(res)
            print(
                f"{res['scenario_id']:<25} | {res['mode']:<10} | {res['p_at_1']:<5} | {res['noise_rank']:<10}"
            )

    # Summary
    summary = {}
    for mode in modes:
        mode_res = [r for r in all_results if r["mode"] == mode]
        avg_p1 = sum(r["p_at_1"] for r in mode_res) / len(mode_res)
        avg_mrr = sum(r["mrr"] for r in mode_res) / len(mode_res)
        summary[mode] = {"avg_p1": avg_p1, "avg_mrr": avg_mrr}

    print("\n--- SUMMARY ---")
    for mode, metrics in summary.items():
        print(
            f"Mode: {mode:<10} | Avg P@1: {metrics['avg_p1']:.2f} | Avg MRR: {metrics['avg_mrr']:.2f}"
        )

    with open("python/tests/benchmark_results.json", "w") as f:
        json.dump({"results": all_results, "summary": summary}, f, indent=2)


if __name__ == "__main__":
    asyncio.run(run_benchmark())
