import json
import time
from pathlib import Path
from typing import List

try:
    import requests  # type: ignore
except ImportError:
    requests = None

import urllib.request


API_URL = "https://aihubmix.com/v1/chat/completions"
API_KEY = "sk-hAqljoEtwdf8xTVt183244305e6948D8BcD33842F990FcAb"
MODELS = [
    "gpt-4.1-free",
    "coding-glm-5-free",
    "coding-minimax-m2.5-free",
    "gemini-3-flash-preview-free",
    "coding-glm-4.7-free",
]

MIN_SUMMARY_CHARS = 500
MAX_SUMMARY_CHARS = 1000
MAX_INPUT_CHARS = 120000
REQUEST_TIMEOUT = 40
RETRY_TIMES = 3
RETRY_DELAY = 3


def find_input_dir() -> Path:
    candidates = [Path("txt"), Path("TXT")]
    for path in candidates:
        if path.exists() and path.is_dir():
            return path
    raise FileNotFoundError("未找到 txt/TXT 目录")


def list_txt_files(input_dir: Path) -> List[Path]:
    files = sorted(input_dir.glob("*.txt"), key=lambda p: p.name)
    if not files:
        raise FileNotFoundError(f"目录 {input_dir} 中未找到 .txt 文件")
    return files


def read_text(file_path: Path) -> str:
    content = file_path.read_text(encoding="utf-8", errors="ignore")
    if len(content) <= MAX_INPUT_CHARS:
        return content

    head_len = MAX_INPUT_CHARS // 2
    tail_len = MAX_INPUT_CHARS - head_len
    return content[:head_len] + "\n\n...(中间内容已省略)...\n\n" + content[-tail_len:]


def build_messages(text: str) -> list:
    prompt = (
        "请对以下小说节选内容进行中文总结。要求："
        f"\n1. 总结长度约 {MIN_SUMMARY_CHARS}-{MAX_SUMMARY_CHARS} 字"
        "\n2. 保留核心人物、主要情节、重要转折"
        "\n3. 语言连贯，避免空话，不需要“核心人物、主要情节、重要转折”字眼"
        "\n4. 只输出总结正文，不要额外标题或说明"
        "\n\n小说内容：\n"
        + text
    )
    return [
        {"role": "system", "content": "你是擅长长篇小说情节压缩的中文编辑。"},
        {"role": "user", "content": prompt},
    ]


def _post_with_urllib(payload: dict, headers: dict) -> dict:
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        body = resp.read().decode("utf-8")
    return json.loads(body)


def call_api(messages: list, model: str) -> str:
    if not API_KEY:
        raise ValueError("API_KEY 为空，请在脚本中填写或改为环境变量")

    payload = {"model": model, "messages": messages, "temperature": 0.6}
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }

    last_err = None
    for attempt in range(1, RETRY_TIMES + 1):
        try:
            if requests is not None:
                response = requests.post(
                    url=API_URL,
                    headers=headers,
                    data=json.dumps(payload),
                    timeout=REQUEST_TIMEOUT,
                )
                response.raise_for_status()
                result = response.json()
            else:
                result = _post_with_urllib(payload, headers)
            return result["choices"][0]["message"]["content"].strip()
        except Exception as exc:
            last_err = exc
            if attempt < RETRY_TIMES:
                time.sleep(RETRY_DELAY)

    raise RuntimeError(f"API 调用失败（模型: {model}）：{last_err}")


def summarize_files(input_dir: Path, output_file: Path) -> None:
    files = list_txt_files(input_dir)
    print(f"发现 {len(files)} 个 TXT 文件，开始总结...")

    # 每次运行先清空旧文件，再逐条追加，避免中途失败导致全部丢失
    output_file.write_text("", encoding="utf-8")

    for idx, file_path in enumerate(files, start=1):
        print(f"[{idx}/{len(files)}] 处理 {file_path.name}")
        text = read_text(file_path)
        messages = build_messages(text)

        # 每个文件轮换起始模型；当前模型失败后按顺序切到下一个模型重试
        start_model_idx = (idx - 1) % len(MODELS)
        model_try_order = MODELS[start_model_idx:] + MODELS[:start_model_idx]

        summary = None
        used_model = None
        last_err = None
        for model in model_try_order:
            try:
                print(f"  尝试模型: {model}")
                summary = call_api(messages, model)
                used_model = model
                break
            except Exception as exc:
                last_err = exc
                print(f"  模型失败: {model} -> {exc}")

        if summary is None or used_model is None:
            raise RuntimeError(f"{file_path.name} 总结失败，所有模型均不可用：{last_err}")

        part = f"第{file_path.name}章总结：{used_model}\n{'=' * 40}\n{summary}"
        with output_file.open("a", encoding="utf-8") as f:
            if idx > 1:
                f.write("\n\n")
            f.write(part)

    print(f"完成，已输出到：{output_file}")


def main() -> None:
    input_dir = find_input_dir()
    output_file = Path("总结.txt")
    summarize_files(input_dir, output_file)


if __name__ == "__main__":
    main()
