import json
import time
from pathlib import Path
from typing import List
import urllib.error

try:
    import requests  # type: ignore
except ImportError:
    requests = None

import urllib.request


API_URL = "https://opencode.ai/zen/v1/chat/completions"
API_KEY = "sk-LbbDOpqt28LlYqZk0YKwsPUlzNYXfdHMw0MEBAAY03HvL6DocQXyMsJXzqGwzBLc"
MODEL = "minimax-m2.5-free"

# 0 表示不截断，完整读取文件
MAX_INPUT_CHARS = 0
REQUEST_CONNECT_TIMEOUT = 20
REQUEST_READ_TIMEOUT = 40
RETRY_TIMES = 3
RETRY_DELAY = 3
DEFAULT_HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
    "Accept": "application/json",
    # 避免被 Cloudflare 按默认 Python-urllib 指纹拦截（403/1010）
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/145.0.0.0 Safari/537.36"
    ),
}


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


def read_text(file_path: Path, max_chars: int = MAX_INPUT_CHARS) -> str:
    content = file_path.read_text(encoding="utf-8", errors="ignore")
    if max_chars <= 0:
        return content
    if len(content) <= max_chars:
        return content

    head_len = max_chars // 2
    tail_len = max_chars - head_len
    return content[:head_len] + "\n\n...(中间内容已省略)...\n\n" + content[-tail_len:]


def build_messages(text: str) -> list:
    prompt = (
        "请对以下小说节选内容进行中文总结。要求："
        f"\n1. 总结长度约 1000 字"
        "\n2. 保留主要人物、情节、重要转折"
        "\n3. 语言连贯，避免空话，不需要“主要人物、情节、重要转折”字眼"
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
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_READ_TIMEOUT) as resp:
            body = resp.read().decode("utf-8")
        return json.loads(body)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"HTTP {e.code}: {detail[:300]}") from e


def call_api(messages: list) -> str:
    if not API_KEY:
        raise ValueError("API_KEY 为空，请在脚本中填写或改为环境变量")

    payload = {
        "model": MODEL,
        "messages": messages,
        "temperature": 0.6,
        "max_tokens": 1000,
    }
    headers = DEFAULT_HEADERS.copy()

    last_err = None
    for attempt in range(1, RETRY_TIMES + 1):
        try:
            if requests is not None:
                response = requests.post(
                    url=API_URL,
                    headers=headers,
                    data=json.dumps(payload),
                    timeout=(REQUEST_CONNECT_TIMEOUT, REQUEST_READ_TIMEOUT),
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

    raise RuntimeError(f"API 调用失败（模型: {MODEL}）：{last_err}")


def summarize_one_file(file_path: Path) -> str:
    text = read_text(file_path, max_chars=MAX_INPUT_CHARS)
    return call_api(build_messages(text))


def summarize_files(files: List[Path], output_file: Path) -> None:
    print(f"[{MODEL}] 开始处理，共 {len(files)} 个 TXT 文件...", flush=True)

    # 启动即创建/清空输出文件，确保运行过程中可见
    output_file.write_text("", encoding="utf-8")
    print(f"[{MODEL}] 输出文件: {output_file.resolve()}", flush=True)

    for idx, file_path in enumerate(files, start=1):
        print(
            f"{time.strftime('%H:%M:%S')} [{MODEL}] [{idx}/{len(files)}] 开始 {file_path.name}",
            flush=True,
        )
        try:
            summary = summarize_one_file(file_path)
            print(
                f"{time.strftime('%H:%M:%S')} [{MODEL}] [{idx}/{len(files)}] 完成 {file_path.name}",
                flush=True,
            )
        except Exception as exc:
            summary = f"[总结失败] {exc}"
            print(f"[{MODEL}] [{idx}/{len(files)}] 失败 {file_path.name}: {exc}", flush=True)

        part = f"第{file_path.name}章总结：{MODEL}\n{'=' * 40}\n{summary}"
        with output_file.open("a", encoding="utf-8") as f:
            if idx > 1:
                f.write("\n\n")
            f.write(part)

    print(f"[{MODEL}] 完成，已输出到：{output_file}", flush=True)


def main() -> None:
    input_dir = find_input_dir()
    files = list_txt_files(input_dir)
    print(f"发现 {len(files)} 个 TXT 文件，开始生成总结...", flush=True)
    output_file = Path(f"总结_opencode_{MODEL}.txt")
    summarize_files(files, output_file)


if __name__ == "__main__":
    main()
