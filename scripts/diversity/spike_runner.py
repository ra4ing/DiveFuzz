"""
Spike 模拟器执行器
使用原始的spike命令而非wrapper
"""
import subprocess
from pathlib import Path
from typing import List
from .config import FuzzerConfig


def build_spike_command(elf_path: str, fuzzer_config: FuzzerConfig) -> List[str]:
    """根据fuzzer配置构建spike命令，参考原始diversty.py中的实现"""
    cmd = ["/home/ra4ing/workspace/riscv/DiveFuzzTest/ref/riscv-isa-sim-adapter/build/spike", "-d", "--log-commits"]

    # 添加pc_override（如果存在）
    if fuzzer_config.pc_override:
        cmd.extend(["--pc", fuzzer_config.pc_override])

    # 添加ISA配置，根据fuzzer类型
    cmd.extend([
        "--isa", fuzzer_config.isa,
        "--debug-cmd-from-string", fuzzer_config.debug_cmd,
        elf_path
    ])

    return cmd


def run_spike(elf_path: Path, fuzzer_config: FuzzerConfig) -> str:
    """运行单个ELF文件并返回输出"""
    cmd = build_spike_command(str(elf_path), fuzzer_config)

    try:
        # 使用更简单的运行方式，避免需要debug-cmd文件
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,  # 设置超时避免长时间等待
            check=False  # 不自动抛异常，因为spike可能正常返回非0码
        )

        # 合并stdout和stderr
        output = result.stdout + result.stderr
        return output
    except subprocess.TimeoutExpired:
        print(f"Timeout running Spike on {elf_path}")
        return ""
    except Exception as e:
        print(f"Error running Spike on {elf_path}: {e}")
        return ""


def run_spike_directory(elf_dir: Path, output_dir: Path, fuzzer_config: FuzzerConfig) -> int:
    """运行目录下所有 ELF 文件

    Args:
        elf_dir: ELF文件目录
        output_dir: 输出目录
        fuzzer_config: Fuzzer配置

    Returns:
        成功处理的文件数
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    elf_files = sorted(elf_dir.glob("*.elf"))
    total = len(elf_files)
    success_count = 0

    for idx, elf_file in enumerate(elf_files, 1):
        output = run_spike(elf_file, fuzzer_config)
        if output:
            output_file = output_dir / f"{elf_file.name}.txt"
            output_file.write_text(output)
            success_count += 1
            print(f"[{idx}/{total}] {elf_file.name} -> {output_file.name}")
        else:
            print(f"[{idx}/{total}] {elf_file.name} FAILED")

    return success_count