import json
import subprocess
import threading
import time
import uuid
from pathlib import Path

import docker
from carbon_estimator import estimate_carbon


# ============================================================
# Paths
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"
RESULTS_DIR = BASE_DIR / "results"

TARGET_FILE = "benchmark_target.py"


# ============================================================
# Benchmark settings
# ============================================================

TIMEOUT_SECONDS = 30

# Run every version several times.
BENCHMARK_RUNS = 5

# Estimated CPU power used by our existing energy model.
CPU_POWER_WATTS = 15.0


# ============================================================
# Docker resource monitor
# ============================================================

def _monitor_docker_stats(container, stop_event, samples):
    """
    Collect Docker CPU and memory samples.

    These values are kept as supplementary information.
    Energy itself is calculated from measured CPU process time.
    """

    try:
        for stats in container.stats(
            stream=True,
            decode=True,
        ):

            if stop_event.is_set():
                break

            cpu_stats = stats.get(
                "cpu_stats",
                {},
            )

            precpu_stats = stats.get(
                "precpu_stats",
                {},
            )

            cpu_usage = (
                cpu_stats
                .get("cpu_usage", {})
                .get("total_usage", 0)
            )

            precpu_usage = (
                precpu_stats
                .get("cpu_usage", {})
                .get("total_usage", 0)
            )

            system_usage = cpu_stats.get(
                "system_cpu_usage",
                0,
            )

            presystem_usage = precpu_stats.get(
                "system_cpu_usage",
                0,
            )

            cpu_delta = (
                cpu_usage - precpu_usage
            )

            system_delta = (
                system_usage - presystem_usage
            )

            online_cpus = cpu_stats.get(
                "online_cpus",
                1,
            )

            cpu_percent = 0.0

            if (
                cpu_delta > 0
                and system_delta > 0
            ):
                cpu_percent = (
                    cpu_delta
                    / system_delta
                    * online_cpus
                    * 100.0
                )

            memory_bytes = (
                stats
                .get("memory_stats", {})
                .get("usage", 0)
            )

            memory_mib = (
                memory_bytes
                / (1024 * 1024)
            )

            samples.append(
                {
                    "cpu": cpu_percent,
                    "memory_mib": memory_mib,
                }
            )

    except Exception:
        # Docker stats are supplementary.
        # Never allow monitoring failure to break the benchmark.
        pass


# ============================================================
# Main benchmark
# ============================================================

def run_benchmark(result_filename="benchmark.json"):
    """
    Run benchmark_target.py inside Docker.

    Energy is calculated from measured CPU process time,
    not from Docker's instantaneous CPU percentage.
    """

    INPUT_DIR.mkdir(
        exist_ok=True
    )

    OUTPUT_DIR.mkdir(
        exist_ok=True
    )

    RESULTS_DIR.mkdir(
        exist_ok=True
    )

    input_path = (
        INPUT_DIR / TARGET_FILE
    )

    if not input_path.exists():
        raise FileNotFoundError(
            f"Target file not found: {input_path}"
        )

    client = docker.from_env()

    container_name = (
        "green-code-benchmark-"
        + uuid.uuid4().hex[:8]
    )

    print(
        "Starting sandboxed benchmark...",
        flush=True,
    )

    print(
        f"Target: {input_path}",
        flush=True,
    )

    print(
        f"Benchmark runs: {BENCHMARK_RUNS}",
        flush=True,
    )

    # --------------------------------------------------------
    # Create a wrapper script inside the mounted output folder.
    #
    # The wrapper:
    #   1. Runs the target several times.
    #   2. Measures actual child CPU time.
    #   3. Captures the target output.
    # --------------------------------------------------------

    wrapper_path = (
        OUTPUT_DIR
        / "benchmark_wrapper.py"
    )

    wrapper_code = f"""
import json
import resource
import subprocess
import sys
import time

runs = {BENCHMARK_RUNS}
target = "/app/input/{TARGET_FILE}"

outputs = []
return_codes = []

start_wall = time.perf_counter()

before_user = resource.getrusage(
    resource.RUSAGE_CHILDREN
).ru_utime

before_system = resource.getrusage(
    resource.RUSAGE_CHILDREN
).ru_stime

for _ in range(runs):

    completed = subprocess.run(
        [sys.executable, target],
        capture_output=True,
        text=True,
        timeout={TIMEOUT_SECONDS},
    )

    outputs.append(
        completed.stdout
    )

    return_codes.append(
        completed.returncode
    )

after_user = resource.getrusage(
    resource.RUSAGE_CHILDREN
).ru_utime

after_system = resource.getrusage(
    resource.RUSAGE_CHILDREN
).ru_stime

end_wall = time.perf_counter()

child_cpu_time = (
    (after_user - before_user)
    + (after_system - before_system)
)

total_wall_time = (
    end_wall - start_wall
)

result = {{
    "runs": runs,
    "child_cpu_time_seconds": child_cpu_time,
    "total_wall_time_seconds": total_wall_time,
    "return_codes": return_codes,
    "outputs": outputs,
}}

print(
    "_GREEN_CODE_BENCHMARK_RESULT_"
)

print(
    json.dumps(result)
)
"""

    wrapper_path.write_text(
        wrapper_code,
        encoding="utf-8",
    )

    # --------------------------------------------------------
    # Start Docker container
    # --------------------------------------------------------

    command = [
        "python",
        "/app/output/benchmark_wrapper.py",
    ]

    container = client.containers.run(
        image="python:3.12-slim",
        command=command,
        name=container_name,
        detach=True,
        network_mode="none",
        nano_cpus=1_000_000_000,
        mem_limit="256m",
        pids_limit=128,
        volumes={
            str(INPUT_DIR.resolve()): {
                "bind": "/app/input",
                "mode": "ro",
            },
            str(OUTPUT_DIR.resolve()): {
                "bind": "/app/output",
                "mode": "rw",
            },
        },
    )

    # --------------------------------------------------------
    # Monitor Docker statistics
    # --------------------------------------------------------

    stats_samples = []

    stop_event = threading.Event()

    monitor_thread = threading.Thread(
        target=_monitor_docker_stats,
        args=(
            container,
            stop_event,
            stats_samples,
        ),
        daemon=True,
    )

    monitor_thread.start()

    benchmark_start = time.perf_counter()

    timed_out = False

    # --------------------------------------------------------
    # Wait for container
    # --------------------------------------------------------

    while True:

        container.reload()

        if container.status != "running":
            break

        elapsed = (
            time.perf_counter()
            - benchmark_start
        )

        if elapsed >= TIMEOUT_SECONDS:

            timed_out = True

            print(
                "TIMEOUT: killing container...",
                flush=True,
            )

            try:
                container.kill()
            except Exception:
                pass

            break

        time.sleep(0.05)

    # Stop monitor
    stop_event.set()

    monitor_thread.join(
        timeout=2
    )

    # --------------------------------------------------------
    # Collect container output
    # --------------------------------------------------------

    stdout = container.logs(
        stdout=True,
        stderr=False,
    ).decode(
        "utf-8",
        errors="replace",
    )

    stderr = container.logs(
        stdout=False,
        stderr=True,
    ).decode(
        "utf-8",
        errors="replace",
    )

    container.reload()

    exit_code = container.attrs[
        "State"
    ][
        "ExitCode"
    ]

    # --------------------------------------------------------
    # Parse measured CPU time
    # --------------------------------------------------------

    measured_cpu_time_total = 0.0
    measured_wall_time_total = 0.0

    program_outputs = []

    return_codes = []

    marker = (
        "_GREEN_CODE_BENCHMARK_RESULT_"
    )

    try:

        lines = stdout.splitlines()

        marker_index = lines.index(
            marker
        )

        json_line = lines[
            marker_index + 1
        ]

        wrapper_result = json.loads(
            json_line
        )

        measured_cpu_time_total = float(
            wrapper_result.get(
                "child_cpu_time_seconds",
                0.0,
            )
        )

        measured_wall_time_total = float(
            wrapper_result.get(
                "total_wall_time_seconds",
                0.0,
            )
        )

        program_outputs = (
            wrapper_result.get(
                "outputs",
                [],
            )
        )

        return_codes = (
            wrapper_result.get(
                "return_codes",
                [],
            )
        )

    except Exception as error:

        print(
            f"Warning: could not parse CPU measurement: "
            f"{error}",
            flush=True,
        )

    # --------------------------------------------------------
    # Normalize measurements to ONE execution
    # --------------------------------------------------------

    cpu_time_per_run = (
        measured_cpu_time_total
        / BENCHMARK_RUNS
    )

    wall_time_per_run = (
        measured_wall_time_total
        / BENCHMARK_RUNS
    )

    # --------------------------------------------------------
    # Energy calculation
    #
    # Energy = CPU time × estimated CPU power
    #
    # W × seconds = Joules
    # --------------------------------------------------------

    estimated_power_watts = (
        CPU_POWER_WATTS
    )

    estimated_energy_joules = (
        cpu_time_per_run
        * estimated_power_watts
    )

    # --------------------------------------------------------
    # Docker statistics
    # --------------------------------------------------------

    if stats_samples:

        average_cpu = (
            sum(
                sample["cpu"]
                for sample in stats_samples
            )
            / len(stats_samples)
        )

        max_cpu = max(
            sample["cpu"]
            for sample in stats_samples
        )

        max_memory = max(
            sample["memory_mib"]
            for sample in stats_samples
        )

        last_memory = (
            stats_samples[-1]["memory_mib"]
        )

    else:

        average_cpu = 0.0
        max_cpu = 0.0
        max_memory = 0.0
        last_memory = 0.0

    # --------------------------------------------------------
    # Program output
    # --------------------------------------------------------

    combined_output = ""

    if program_outputs:

        combined_output = "\n".join(
            program_outputs
        )

    # --------------------------------------------------------
    # Result object
    # --------------------------------------------------------

    result = {

        "target": TARGET_FILE,

        "benchmark_runs": BENCHMARK_RUNS,

        "exit_code": exit_code,

        "timeout": timed_out,

        "execution_time_seconds": round(
            wall_time_per_run,
            6,
        ),

        "cpu_time_seconds": round(
            cpu_time_per_run,
            6,
        ),

        "average_cpu_usage_percent": round(
            average_cpu,
            2,
        ),

        "max_cpu_usage_percent": round(
            max_cpu,
            2,
        ),

        "memory_usage_mib": round(
            last_memory,
            2,
        ),

        "max_memory_usage_mib": round(
            max_memory,
            2,
        ),

        "estimated_power_watts": round(
            estimated_power_watts,
            4,
        ),

        "estimated_energy_joules": round(
            estimated_energy_joules,
            6,
        ),

        "limits": {
            "cpu": "1 core",
            "memory": "256 MB",
            "network": "disabled",
            "pids_limit": 128,
        },

        "stdout": combined_output,

        "stderr": stderr,
    }

    # --------------------------------------------------------
    # Save result
    # --------------------------------------------------------

    result_path = (
        RESULTS_DIR
        / result_filename
    )

    with open(
        result_path,
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            result,
            file,
            indent=2,
        )

    # --------------------------------------------------------
    # Console output
    # --------------------------------------------------------

    print()
    print(
        "Benchmark finished.",
        flush=True,
    )

    print(
        f"Normalized execution time: "
        f"{wall_time_per_run:.6f} seconds",
        flush=True,
    )

    print(
        f"Measured CPU time: "
        f"{cpu_time_per_run:.6f} seconds",
        flush=True,
    )

    print(
        f"Docker CPU usage: "
        f"{average_cpu:.2f}%",
        flush=True,
    )

    print(
        f"Memory usage: "
        f"{last_memory:.2f} MiB",
        flush=True,
    )

    print(
        f"Max CPU usage: "
        f"{max_cpu:.2f}%",
        flush=True,
    )

    print(
        f"Max memory usage: "
        f"{max_memory:.2f} MiB",
        flush=True,
    )

    print(
        f"Estimated power: "
        f"{estimated_power_watts:.4f} W",
        flush=True,
    )

    print(
        f"Estimated energy per run: "
        f"{estimated_energy_joules:.6f} J",
        flush=True,
    )

    print(
        f"Results: {result_path}",
        flush=True,
    )

    if combined_output:

        print()
        print(
            "Program output:",
            flush=True,
        )

        print(
            combined_output,
            flush=True,
        )

    if stderr:

        print()
        print(
            "Program errors:",
            flush=True,
        )

        print(
            stderr,
            flush=True,
        )

    # --------------------------------------------------------
    # Cleanup
    # --------------------------------------------------------

    try:
        container.remove(
            force=True
        )
    except Exception:
        pass

    try:
        wrapper_path.unlink(
            missing_ok=True
        )
    except Exception:
        pass

    return result


# ============================================================
# Benchmark a specific code version
# ============================================================

def benchmark_code(
    code: str,
    result_filename: str,
):
    """
    Write code into benchmark_target.py
    and benchmark it.
    """

    INPUT_DIR.mkdir(
        exist_ok=True
    )

    input_path = (
        INPUT_DIR / TARGET_FILE
    )

    input_path.write_text(
        code,
        encoding="utf-8",
    )

    return run_benchmark(
        result_filename=result_filename
    )


# ============================================================
# Original vs Refactored
# ============================================================

def benchmark_original_vs_refactored(
    original_code: str,
    refactored_code: str,
):
    """
    Benchmark Original and Refactored separately
    and estimate carbon emissions from measured energy.
    """

    from carbon_estimator import estimate_carbon

    print()
    print(
        "========================================",
        flush=True,
    )

    print(
        "Energy + Carbon Benchmark: "
        "Original vs Refactored",
        flush=True,
    )

    print(
        "========================================",
        flush=True,
    )

    # --------------------------------------------------------
    # Original
    # --------------------------------------------------------

    print()
    print(
        "Benchmarking ORIGINAL code...",
        flush=True,
    )

    original_result = benchmark_code(
        original_code,
        "benchmark_original.json",
    )

    # --------------------------------------------------------
    # Refactored
    # --------------------------------------------------------

    print()
    print(
        "Benchmarking REFACTORED code...",
        flush=True,
    )

    refactored_result = benchmark_code(
        refactored_code,
        "benchmark_refactored.json",
    )

    # --------------------------------------------------------
    # Energy values
    # --------------------------------------------------------

    original_energy = float(
        original_result[
            "estimated_energy_joules"
        ]
    )

    refactored_energy = float(
        refactored_result[
            "estimated_energy_joules"
        ]
    )

    # --------------------------------------------------------
    # Carbon estimation
    # --------------------------------------------------------

    original_carbon = estimate_carbon(
        original_energy
    )

    refactored_carbon = estimate_carbon(
        refactored_energy
    )
    # --------------------------------------------------------
    # Carbon savings
    # --------------------------------------------------------

    carbon_saved = (
        original_carbon
        - refactored_carbon
    )

    carbon_saved_percent = 0.0

    if original_carbon > 0:
        carbon_saved_percent = (
            carbon_saved
            / original_carbon
            * 100.0
        )

    # --------------------------------------------------------
    # Comparison
    # --------------------------------------------------------

    comparison = {
    "original": {
        "execution_time_seconds":
            original_result[
                "execution_time_seconds"
            ],

        "cpu_time_seconds":
            original_result[
                "cpu_time_seconds"
            ],

        "estimated_power_watts":
            original_result[
                "estimated_power_watts"
            ],

        "estimated_energy_joules":
            original_energy,

        "estimated_carbon_grams_co2e":
            original_carbon,
    },

    "refactored": {
        "execution_time_seconds":
            refactored_result[
                "execution_time_seconds"
            ],

        "cpu_time_seconds":
            refactored_result[
                "cpu_time_seconds"
            ],

        "estimated_power_watts":
            refactored_result[
                "estimated_power_watts"
            ],

        "estimated_energy_joules":
            refactored_energy,

        "estimated_carbon_grams_co2e":
            refactored_carbon,
    },

    "carbon_comparison": {
        "carbon_saved_grams_co2e":
            carbon_saved,

        "carbon_saved_percent":
            carbon_saved_percent,
    },
}

    # --------------------------------------------------------
    # Save comparison
    # --------------------------------------------------------

    comparison_path = (
        RESULTS_DIR
        / "energy_comparison.json"
    )

    with open(
        comparison_path,
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            comparison,
            file,
            indent=2,
        )

    # --------------------------------------------------------
    # Print results
    # --------------------------------------------------------

    print()
    print(
        "========================================",
        flush=True,
    )

    print(
        "Energy + Carbon benchmark complete.",
        flush=True,
    )

    print(
        f"Original energy: "
        f"{original_energy:.6f} J",
        flush=True,
    )

    print(
        f"Refactored energy: "
        f"{refactored_energy:.6f} J",
        flush=True,
    )

    print(
        f"Original carbon: "
        f"{original_carbon:.10f} gCO2e",
        flush=True,
    )

    print(
        f"Refactored carbon: "
        f"{refactored_carbon:.10f} gCO2e",
        flush=True,
    )

    print(
        f"Comparison results: "
        f"{comparison_path}",
        flush=True,
    )

    print(
        "========================================",
        flush=True,
    )

    return comparison


# ============================================================
# Validation
# ============================================================

def run_validation():
    """
    Validate program behavior without measuring energy.
    """

    INPUT_DIR.mkdir(
        exist_ok=True
    )

    input_path = (
        INPUT_DIR / TARGET_FILE
    )

    if not input_path.exists():
        raise FileNotFoundError(
            f"Target file not found: {input_path}"
        )

    client = docker.from_env()

    container_name = (
        "green-code-validation-"
        + uuid.uuid4().hex[:8]
    )

    container = client.containers.run(
        image="python:3.12-slim",
        command=[
            "python",
            f"/app/input/{TARGET_FILE}",
        ],
        name=container_name,
        detach=True,
        network_mode="none",
        nano_cpus=1_000_000_000,
        mem_limit="256m",
        pids_limit=128,
        volumes={
            str(INPUT_DIR.resolve()): {
                "bind": "/app/input",
                "mode": "ro",
            }
        },
    )

    try:

        result = container.wait(
            timeout=TIMEOUT_SECONDS
        )

        stdout = container.logs(
            stdout=True,
            stderr=False,
        ).decode(
            "utf-8",
            errors="replace",
        )

        stderr = container.logs(
            stdout=False,
            stderr=True,
        ).decode(
            "utf-8",
            errors="replace",
        )

        exit_code = result.get(
            "StatusCode",
            -1,
        )

        return {
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "timeout": False,
        }

    except Exception as error:

        try:
            container.kill()
        except Exception:
            pass

        return {
            "exit_code": -1,
            "stdout": "",
            "stderr": str(error),
            "timeout": True,
        }

    finally:

        try:
            container.remove(
                force=True
            )
        except Exception:
            pass


def validate_refactor(
    original_code: str,
    refactored_code: str,
):
    """
    Check that Original and Refactored code
    have the same observable output and exit code.
    """

    input_path = (
        INPUT_DIR / TARGET_FILE
    )

    # Original
    input_path.write_text(
        original_code,
        encoding="utf-8",
    )

    original_result = run_validation()

    # Refactored
    input_path.write_text(
        refactored_code,
        encoding="utf-8",
    )

    refactored_result = run_validation()

    same_output = (
        original_result["exit_code"]
        == refactored_result["exit_code"]
        and
        original_result["stdout"]
        == refactored_result["stdout"]
    )

    return {
        "valid": same_output,
        "original": original_result,
        "refactored": refactored_result,
    }


# ============================================================
# Direct execution
# ============================================================

if __name__ == "__main__":
    run_benchmark()