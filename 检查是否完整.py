from pathlib import Path


def collect_numbered_txt_files(folder: Path) -> tuple[list[int], list[str], int]:
    """收集形如 0001.txt 的文件编号，返回编号列表、非法文件名和编号位数。"""
    numbers: list[int] = []
    invalid_names: list[str] = []
    max_width = 0

    for file_path in folder.glob("*.txt"):
        stem = file_path.stem
        if stem.isdigit():
            numbers.append(int(stem))
            max_width = max(max_width, len(stem))
        else:
            invalid_names.append(file_path.name)

    return sorted(set(numbers)), sorted(invalid_names), max_width


def main() -> None:
    base_dir = Path(__file__).resolve().parent
    tmp_dir = base_dir / "tmp"

    if not tmp_dir.exists():
        print(f"未找到目录: {tmp_dir}")
        return

    numbers, invalid_names, detected_width = collect_numbered_txt_files(tmp_dir)

    if not numbers:
        print(f"目录 {tmp_dir} 中没有可检查的数字编号 txt 文件。")
        if invalid_names:
            print("以下 txt 文件名不符合纯数字命名规则:")
            for name in invalid_names:
                print(f"- {name}")
        return

    first_num = numbers[0]
    last_num = numbers[-1]
    width = max(detected_width, len(str(last_num)))

    existing = set(numbers)
    expected = set(range(first_num, last_num + 1))
    missing = sorted(expected - existing)

    print(f"检查目录: {tmp_dir}")
    print(f"首个编号: {first_num:0{width}d}.txt")
    print(f"末尾编号: {last_num:0{width}d}.txt")
    print(f"实际文件数: {len(existing)}")
    print(f"应有文件数: {last_num - first_num + 1}")

    if invalid_names:
        print(f"\n不符合数字命名规则的 txt 文件 ({len(invalid_names)} 个):")
        for name in invalid_names:
            print(f"- {name}")

    if not missing:
        print("\n编号完整，无缺失文件。")
        return

    print(f"\n缺失文件 ({len(missing)} 个):")
    for num in missing:
        print(f"- {num:0{width}d}.txt")


if __name__ == "__main__":
    main()
