#!/usr/bin/env python3

"""
run_young_autopt_eval.py

for category in web_security network_security access_control cryptography; do
    ./run_young_autopt_eval.py --all-machines --level in-vitro --category "$category" --repetitions 1
  done

用法範例：
  單一機器：
    ./run_young_autopt_eval.py --level in-vitro --category access_control --vm-id 0 --repetitions 3

  單一類別：
    ./run_young_autopt_eval.py --all-machines --level in-vitro --category web_security --repetitions 2

  全部：
    ./run_young_autopt_eval.py --mode all --repetitions 1

所有可選參數：
  --mode {machine,category,all}
    執行範圍。預設為 machine

  --all-machines
    跑指定 level/category 底下的全部機器。等同於 --mode category

  --level LEVEL
    題目層級，例如：in-vitro、real-world

  --category CATEGORY
    題目類別，例如：access_control、web_security、network_security、
    cryptography、cve

  --vm-id VM_ID
    指定目標 vm 編號。當 --mode=machine 時必填

  --repetitions N
    每個選定題目要執行幾次。預設為 1

  --max-steps N
    傳給 young-autopt 的 --max-steps。預設為 18

  --games-file PATH
    games.json 路徑。預設為 auto-pen-bench/data/games.json

  --run-eval-script PATH
    run_eval.sh 路徑。預設為 auto-pen-bench/run_eval.sh

  --autopt-dir PATH
    Young-AutoPT-v2 路徑。預設為 /home/younglee/Thesis/Young-AutoPT-v2

  --log-dir PATH
    log 輸出目錄。預設為 auto-pen-bench/logs/<timestamp>/

  --dry-run
    只顯示將執行的流程並建立 log 檔，不真的執行 run_eval.sh 與 young-autopt

  --stop-on-error
    遇到第一個失敗的題目時立刻停止
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_GAMES_FILE = SCRIPT_DIR / "data" / "games.json"
DEFAULT_RUN_EVAL_SCRIPT = SCRIPT_DIR / "run_eval.sh"
DEFAULT_AUTOPT_DIR = SCRIPT_DIR.parent / "Young-AutoPT-v2"


@dataclass(frozen=True)
class TaskCase:
    level: str
    category: str
    vm_id: int
    target: str
    task: str
    expected_flag: str = ""

    @property
    def display_name(self) -> str:
        return f"{self.target} ({self.level}/{self.category}, vm{self.vm_id})"


@dataclass(frozen=True)
class RunResult:
    case: TaskCase
    repetition: int
    log_path: Path
    run_eval_exit_code: int
    cli_exit_code: int | None
    captured_flag: str = ""

    @property
    def succeeded(self) -> bool:
        return self.run_eval_exit_code == 0 and self.cli_exit_code == 0

    @property
    def flag_matched(self) -> bool:
        if not self.captured_flag or not self.case.expected_flag:
            return False
        return self.captured_flag == self.case.expected_flag


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Automate AutoPenBench machine startup and Young-AutoPT runs, "
            "with one log file per task/repetition."
        )
    )
    parser.add_argument(
        "--mode",
        choices=("machine", "category", "all"),
        default="machine",
        help="Run a single machine, a whole category, or every task in games.json. Default: machine.",
    )
    parser.add_argument(
        "--all-machines",
        action="store_true",
        help="Run every machine in the selected level/category. Equivalent to --mode category.",
    )
    parser.add_argument("--level", help="Task level, for example: in-vitro or real-world.")
    parser.add_argument("--category", help="Task category, for example: access_control or cve.")
    parser.add_argument("--vm-id", type=int, help="VM id for --mode machine.")
    parser.add_argument(
        "--repetitions",
        type=int,
        default=None,
        help="How many times to run each selected task. Default: 1.",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=18,
        help="Value passed to young-autopt --max-steps. Default: 18.",
    )
    parser.add_argument(
        "--games-file",
        type=Path,
        default=DEFAULT_GAMES_FILE,
        help=f"Path to games.json. Default: {DEFAULT_GAMES_FILE}",
    )
    parser.add_argument(
        "--run-eval-script",
        type=Path,
        default=DEFAULT_RUN_EVAL_SCRIPT,
        help=f"Path to run_eval.sh. Default: {DEFAULT_RUN_EVAL_SCRIPT}",
    )
    parser.add_argument(
        "--autopt-dir",
        type=Path,
        default=DEFAULT_AUTOPT_DIR,
        help=f"Path to Young-AutoPT-v2. Default: {DEFAULT_AUTOPT_DIR}",
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=None,
        help="Directory where log files are stored. Default: auto-pen-bench/logs/<timestamp>/",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print commands and create log files without actually running them.",
    )
    parser.add_argument(
        "--stop-on-error",
        action="store_true",
        help="Stop after the first failed run_eval.sh or young-autopt invocation.",
    )
    return parser


def load_cases(games_file: Path) -> list[TaskCase]:
    raw = json.loads(games_file.read_text(encoding="utf-8"))
    cases: list[TaskCase] = []

    for level, categories in raw.items():
        for category, entries in categories.items():
            for index, entry in enumerate(entries):
                target = str(entry["target"])
                task = str(entry["task"])
                vm_id = parse_vm_id(target, fallback=index)
                cases.append(
                    TaskCase(
                        level=str(level),
                        category=str(category),
                        vm_id=vm_id,
                        target=target,
                        task=task,
                        expected_flag=str(entry.get("flag", "")),
                    )
                )

    cases.sort(key=lambda case: (case.level, case.category, case.vm_id))
    return cases


def parse_vm_id(target: str, fallback: int) -> int:
    match = re.search(r"_vm(\d+)$", target)
    if match:
        return int(match.group(1))
    return fallback


def resolve_selection(args: argparse.Namespace, cases: Sequence[TaskCase]) -> tuple[str, list[TaskCase], int]:
    if args.repetitions is not None and args.repetitions <= 0:
        raise SystemExit("--repetitions must be greater than 0.")
    if args.max_steps <= 0:
        raise SystemExit("--max-steps must be greater than 0.")

    mode = resolve_mode(args)
    selected_cases = select_cases(mode, args, cases)
    repetitions = args.repetitions if args.repetitions is not None else 1

    return mode, selected_cases, repetitions


def resolve_mode(args: argparse.Namespace) -> str:
    if not args.all_machines:
        return args.mode

    if args.mode == "all":
        raise SystemExit("--all-machines cannot be used together with --mode all.")

    return "category"


def select_cases(mode: str, args: argparse.Namespace, cases: Sequence[TaskCase]) -> list[TaskCase]:
    if mode == "all":
        return list(cases)

    levels = sorted({case.level for case in cases})
    level = args.level
    if not level:
        raise SystemExit(f"--mode {mode} requires --level.")
    if level not in levels:
        raise SystemExit(f"Unknown level: {level}")

    categories = sorted({case.category for case in cases if case.level == level})
    category = args.category
    if not category:
        raise SystemExit(f"--mode {mode} requires --category.")
    if category not in categories:
        raise SystemExit(f"Unknown category for level {level}: {category}")

    matching = [case for case in cases if case.level == level and case.category == category]
    if mode == "category":
        return matching

    if mode != "machine":
        raise SystemExit(f"Unsupported mode: {mode}")

    vm_id = args.vm_id
    if vm_id is None:
        raise SystemExit("--mode machine requires --vm-id.")

    selected = [case for case in matching if case.vm_id == vm_id]
    if not selected:
        raise SystemExit(f"No case found for {level}/{category} vm{vm_id}.")
    return selected


def ensure_paths(args: argparse.Namespace) -> tuple[Path, Path, Path]:
    games_file = args.games_file.resolve()
    run_eval_script = args.run_eval_script.resolve()
    autopt_dir = args.autopt_dir.resolve()

    if not games_file.is_file():
        raise SystemExit(f"games.json not found: {games_file}")
    if not run_eval_script.is_file():
        raise SystemExit(f"run_eval.sh not found: {run_eval_script}")
    if not autopt_dir.is_dir():
        raise SystemExit(f"Young-AutoPT-v2 directory not found: {autopt_dir}")

    cli_file = autopt_dir / "cli.py"
    if not cli_file.is_file():
        raise SystemExit(f"cli.py not found under: {autopt_dir}")

    return games_file, run_eval_script, autopt_dir


def resolve_log_dir(log_dir_arg: Path | None) -> Path:
    if log_dir_arg is not None:
        log_dir = log_dir_arg.resolve()
    else:
        log_dir = SCRIPT_DIR / "logs" / datetime.now().strftime("%Y%m%d-%H%M%S")
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def write_log_header(
    handle,
    *,
    case: TaskCase,
    repetition: int,
    mode: str,
    max_steps: int,
    log_path: Path,
) -> None:
    handle.write("=== Young-AutoPT Auto Evaluation Log ===\n")
    handle.write(f"timestamp: {datetime.now().isoformat(timespec='seconds')}\n")
    handle.write(f"mode: {mode}\n")
    handle.write(f"target: {case.target}\n")
    handle.write(f"level: {case.level}\n")
    handle.write(f"category: {case.category}\n")
    handle.write(f"vm_id: {case.vm_id}\n")
    handle.write(f"repetition: {repetition}\n")
    handle.write(f"log_file: {log_path}\n")
    handle.write(f"max_steps: {max_steps}\n")
    handle.write("objective_source: games.json task field via --objective\n")
    handle.write("\n=== User Input (task) ===\n")
    handle.write(case.task)
    if not case.task.endswith("\n"):
        handle.write("\n")


def format_command(command: Sequence[str]) -> str:
    return shlex.join([str(part) for part in command])


def stream_command(
    *,
    label: str,
    command: Sequence[str],
    cwd: Path,
    handle,
    dry_run: bool,
) -> int:
    handle.write(f"\n=== {label} ===\n")
    handle.write(f"cwd: {cwd}\n")
    handle.write(f"command: {format_command(command)}\n")
    handle.flush()

    if dry_run:
        line = f"[dry-run] skipped {label}\n"
        print(line, end="")
        handle.write(line)
        handle.flush()
        return 0

    process = subprocess.Popen(
        [str(part) for part in command],
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    assert process.stdout is not None
    for line in process.stdout:
        sys.stdout.write(line)
        handle.write(line)
    process.stdout.close()
    return_code = process.wait()
    handle.write(f"\n[{label}] exit_code={return_code}\n")
    handle.flush()
    return return_code


def _pump_stream(stream, handle) -> None:
    try:
        for line in iter(stream.readline, ""):
            handle.write(line)
            handle.flush()
    finally:
        stream.close()
        handle.close()


def start_kali_log_capture(*, kali_log_path: Path, dry_run: bool) -> tuple[subprocess.Popen[str] | None, threading.Thread | None]:
    with kali_log_path.open("w", encoding="utf-8") as handle:
        handle.write("=== Kali Server Log Capture ===\n")
        handle.write(f"timestamp: {datetime.now().isoformat(timespec='seconds')}\n")
        handle.write("source: docker exec -i kali_master tail -n 0 -F /var/log/young_pentest_server.log\n")
        if dry_run:
            handle.write("[dry-run] skipped kali log capture\n")
            return None, None

    process = subprocess.Popen(
        [
            "docker",
            "exec",
            "-i",
            "kali_master",
            "tail",
            "-n",
            "0",
            "-F",
            "/var/log/young_pentest_server.log",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert process.stdout is not None

    handle = kali_log_path.open("a", encoding="utf-8")
    thread = threading.Thread(target=_pump_stream, args=(process.stdout, handle), daemon=True)
    thread.start()
    return process, thread


def stop_kali_log_capture(
    *,
    process: subprocess.Popen[str] | None,
    thread: threading.Thread | None,
    kali_log_path: Path,
) -> None:
    if process is None:
        return

    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    if thread is not None:
        thread.join(timeout=5)

    with kali_log_path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n[kali-log-capture] exit_code={process.returncode}\n")


def run_case(
    *,
    case: TaskCase,
    repetition: int,
    mode: str,
    max_steps: int,
    log_dir: Path,
    run_eval_script: Path,
    autopt_dir: Path,
    dry_run: bool,
) -> RunResult:
    log_path = log_dir / f"{case.target}_{repetition}.log"
    kali_log_path = log_dir / f"{case.target}_{repetition}_kali.log"
    run_eval_command = ["bash", str(run_eval_script), case.level, case.category, str(case.vm_id)]
    cli_command = [
        "uv",
        "run",
        "python",
        "cli.py",
        "young-autopt",
        "--max-steps",
        str(max_steps),
        "--objective",
        case.task,
    ]

    with log_path.open("w", encoding="utf-8") as handle:
        write_log_header(
            handle,
            case=case,
            repetition=repetition,
            mode=mode,
            max_steps=max_steps,
            log_path=log_path,
        )
        run_eval_exit_code = stream_command(
            label="run_eval.sh",
            command=run_eval_command,
            cwd=SCRIPT_DIR,
            handle=handle,
            dry_run=dry_run,
        )
        cli_exit_code: int | None = None
        if run_eval_exit_code == 0:
            kali_process, kali_thread = start_kali_log_capture(kali_log_path=kali_log_path, dry_run=dry_run)
            try:
                cli_exit_code = stream_command(
                    label="young-autopt",
                    command=cli_command,
                    cwd=autopt_dir,
                    handle=handle,
                    dry_run=dry_run,
                )
            finally:
                stop_kali_log_capture(
                    process=kali_process,
                    thread=kali_thread,
                    kali_log_path=kali_log_path,
                )
        else:
            handle.write("\nSkipping young-autopt because run_eval.sh failed.\n")
            with kali_log_path.open("w", encoding="utf-8") as kali_handle:
                kali_handle.write("=== Kali Server Log Capture ===\n")
                kali_handle.write(f"timestamp: {datetime.now().isoformat(timespec='seconds')}\n")
                kali_handle.write("Skipping kali log capture because run_eval.sh failed.\n")

    # Parse captured_flag from log (logger.info output has no ANSI codes)
    captured_flag = ""
    try:
        with log_path.open("r", encoding="utf-8") as f:
            for line in f:
                m = re.search(r"captured_flag=(flag\{[^}]+\})", line)
                if m:
                    captured_flag = m.group(1)
                    break
    except Exception:
        pass

    return RunResult(
        case=case,
        repetition=repetition,
        log_path=log_path,
        run_eval_exit_code=run_eval_exit_code,
        cli_exit_code=cli_exit_code,
        captured_flag=captured_flag,
    )


def print_selection_summary(mode: str, selected_cases: Sequence[TaskCase], repetitions: int, log_dir: Path) -> None:
    print("Execution plan")
    print(f"  mode: {mode}")
    print(f"  selected tasks: {len(selected_cases)}")
    print(f"  repetitions per task: {repetitions}")
    print(f"  log directory: {log_dir}")
    for case in selected_cases:
        print(f"  - {case.display_name}")
    print("")


def print_results(results: Iterable[RunResult]) -> int:
    results = list(results)
    succeeded = sum(result.succeeded for result in results)
    flag_matched = sum(result.flag_matched for result in results)
    print("Run summary")
    print(f"  succeeded: {succeeded}/{len(results)}")
    print(f"  flag_matched: {flag_matched}/{len(results)}")
    for result in results:
        status = "OK" if result.succeeded else "FAILED"
        flag_status = "FLAG_OK" if result.flag_matched else ("FLAG_MISS" if result.case.expected_flag else "NO_FLAG")
        cli_code = "-" if result.cli_exit_code is None else str(result.cli_exit_code)
        print(
            f"  [{status}] [{flag_status}] {result.case.target} rep={result.repetition} "
            f"run_eval={result.run_eval_exit_code} cli={cli_code} "
            f"expected={result.case.expected_flag} captured={result.captured_flag} "
            f"log={result.log_path}"
        )
    return 0 if succeeded == len(results) else 1


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    games_file, run_eval_script, autopt_dir = ensure_paths(args)
    cases = load_cases(games_file)
    mode, selected_cases, repetitions = resolve_selection(args, cases)
    log_dir = resolve_log_dir(args.log_dir)

    print_selection_summary(mode, selected_cases, repetitions, log_dir)

    results: list[RunResult] = []
    for case in selected_cases:
        for repetition in range(1, repetitions + 1):
            print(f"=== Running {case.target} repetition {repetition}/{repetitions} ===")
            result = run_case(
                case=case,
                repetition=repetition,
                mode=mode,
                max_steps=args.max_steps,
                log_dir=log_dir,
                run_eval_script=run_eval_script,
                autopt_dir=autopt_dir,
                dry_run=args.dry_run,
            )
            results.append(result)

            if args.stop_on_error and not result.succeeded:
                return print_results(results)

    return print_results(results)


if __name__ == "__main__":
    sys.exit(main())
