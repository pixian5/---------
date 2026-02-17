import json
import time
import threading
from pathlib import Path
from typing import List, Optional, Tuple
import urllib.error

try:
    import requests  # type: ignore
except ImportError:
    requests = None

import urllib.request

#线程数
THREAD_COUNT = 20

API_URL = "https://opencode.ai/zen/v1/chat/completions"
API_KEY = "sk-LbbDOpqt28LlYqZk0YKwsPUlzNYXfdHMw0MEBAAY03HvL6DocQXyMsJXzqGwzBLc"
MODEL = "minimax-m2.5-free"

# 0 表示不截断，完整读取文件
MAX_INPUT_CHARS = 0
REQUEST_CONNECT_TIMEOUT = 20
REQUEST_READ_TIMEOUT = 40
RETRY_TIMES = 13
RETRY_DELAY = 3
FILE_RETRY_TIMES = 2
FILE_RETRY_DELAY = 8
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


def _retry_delay_seconds(attempt: int, base_delay: int) -> int:
    # Exponential backoff: 1x, 2x, 4x...
    return base_delay * (2 ** (attempt - 1))


def _extract_http_status(exc: Exception) -> Optional[int]:
    if requests is not None and isinstance(exc, requests.exceptions.HTTPError):
        if exc.response is not None:
            return exc.response.status_code
        return None
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code
    return None


def _is_retryable_exception(exc: Exception) -> bool:
    status = _extract_http_status(exc)
    if status is not None:
        return status == 429 or status >= 500

    if requests is not None and isinstance(
        exc, (requests.exceptions.Timeout, requests.exceptions.ConnectionError)
    ):
        return True

    if isinstance(exc, (urllib.error.URLError, TimeoutError)):
        return True

    msg = str(exc).lower()
    transient_words = (
        "timed out",
        "timeout",
        "temporarily unavailable",
        "connection reset",
        "connection aborted",
        "remote end closed",
    )
    return any(word in msg for word in transient_words)


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


def call_api(messages: list, file_name: str = "") -> str:
    if not API_KEY:
        raise ValueError("API_KEY 为空，请在脚本中填写或改为环境变量")

    payload = {
        "model": MODEL,
        "messages": messages,
        "temperature": 1.9,
        #"max_output_tokens": 1500,
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
            can_retry = _is_retryable_exception(exc)
            if attempt < RETRY_TIMES and can_retry:
                wait_seconds = _retry_delay_seconds(attempt, RETRY_DELAY)
                file_hint = f" ({file_name})" if file_name else ""
                print(
                    f"{time.strftime('%H:%M:%S')} [{MODEL}] API 请求失败{file_hint}，"
                    f"第 {attempt}/{RETRY_TIMES} 次：{exc}；{wait_seconds}s 后重试",
                    flush=True,
                )
                time.sleep(wait_seconds)
                continue
            if attempt < RETRY_TIMES and not can_retry:
                print(
                    f"{time.strftime('%H:%M:%S')} [{MODEL}] API 请求错误不可重试：{exc}",
                    flush=True,
                )
            break

    raise RuntimeError(f"API 调用失败（模型: {MODEL}）：{last_err}")


def summarize_one_file(file_path: Path) -> str:
    text = read_text(file_path, max_chars=MAX_INPUT_CHARS)
    return call_api(build_messages(text), file_path.name)


def summarize_one_file_with_retry(
    file_path: Path, idx: int, total: int, thread_id: int
) -> str:
    thread_name = f"线程{thread_id}"
    print(
        f"{time.strftime('%H:%M:%S')} [{MODEL}] [{thread_name}] [{idx}/{total}] 开始 {file_path.name}",
        flush=True,
    )

    summary = None
    last_exc = None
    for file_attempt in range(1, FILE_RETRY_TIMES + 1):
        try:
            summary = summarize_one_file(file_path)
            print(
                f"{time.strftime('%H:%M:%S')} [{MODEL}] [{thread_name}] [{idx}/{total}] 完成 {file_path.name}",
                flush=True,
            )
            break
        except Exception as exc:
            last_exc = exc
            if file_attempt < FILE_RETRY_TIMES:
                wait_seconds = _retry_delay_seconds(file_attempt, FILE_RETRY_DELAY)
                print(
                    f"{time.strftime('%H:%M:%S')} [{MODEL}] [{thread_name}] [{idx}/{total}] "
                    f"失败 {file_path.name}（文件级重试第 {file_attempt}/{FILE_RETRY_TIMES} 次）: {exc}；"
                    f"{wait_seconds}s 后重试",
                    flush=True,
                )
                time.sleep(wait_seconds)
            else:
                print(
                    f"[{MODEL}] [{thread_name}] [{idx}/{total}] 失败 {file_path.name}: {exc}",
                    flush=True,
                )

    if summary is None:
        summary = f"[总结失败] {last_exc}"
    return summary


def _index_width(total: int) -> int:
    return max(1, len(str(total)))


def _tmp_part_path(tmp_dir: Path, idx: int, total: int) -> Path:
    width = _index_width(total)
    return tmp_dir / f"{idx:0{width}d}.txt"


def summarize_files(files: List[Path], output_file: Path) -> None:
    total = len(files)
    print(f"[{MODEL}] 开始处理，共 {total} 个 TXT 文件，使用 {THREAD_COUNT} 线程...", flush=True)

    tmp_dir = Path("tmp")
    tmp_dir.mkdir(parents=True, exist_ok=True)
    for old_file in tmp_dir.glob("*.txt"):
        old_file.unlink()

    print(f"[{MODEL}] 输出文件: {output_file.resolve()}", flush=True)
    print(f"[{MODEL}] 临时目录: {tmp_dir.resolve()}", flush=True)

    indexed_files = list(enumerate(files, start=1))
    thread_buckets = [indexed_files[i::THREAD_COUNT] for i in range(THREAD_COUNT)]
    for thread_id, bucket in enumerate(thread_buckets, start=1):
        print(f"[{MODEL}] 线程{thread_id} 分配 {len(bucket)} 个文件", flush=True)

    def worker(thread_id: int, assigned_files: List[Tuple[int, Path]]) -> None:
        if not assigned_files:
            print(f"[{MODEL}] 线程{thread_id} 无任务", flush=True)
            return

        for idx, file_path in assigned_files:
            summary = summarize_one_file_with_retry(file_path, idx, total, thread_id)
            part = f"第{file_path.name}章总结：{MODEL}\n{'=' * 40}\n{summary}"
            part_file = _tmp_part_path(tmp_dir, idx, total)
            part_file.write_text(part, encoding="utf-8")
            print(
                f"{time.strftime('%H:%M:%S')} [{MODEL}] [线程{thread_id}] [{idx}/{total}] "
                f"已写入临时文件 {part_file.name}",
                flush=True,
            )

    threads: List[threading.Thread] = []
    for thread_id, assigned_files in enumerate(thread_buckets, start=1):
        t = threading.Thread(
            target=worker,
            args=(thread_id, assigned_files),
            name=f"summary-worker-{thread_id}",
            daemon=False,
        )
        t.start()
        threads.append(t)

    for t in threads:
        t.join()

    print(f"[{MODEL}] 所有线程完成，开始合并临时文件...", flush=True)
    with output_file.open("w", encoding="utf-8") as out:
        for idx, file_path in indexed_files:
            part_file = _tmp_part_path(tmp_dir, idx, total)
            if part_file.exists():
                part_content = part_file.read_text(encoding="utf-8", errors="ignore")
            else:
                part_content = (
                    f"第{file_path.name}章总结：{MODEL}\n{'=' * 40}\n"
                    f"[总结失败] 缺少临时文件 {part_file.name}"
                )
            if idx > 1:
                out.write("\n\n")
            out.write(part_content)

    print(f"[{MODEL}] 完成，已输出到：{output_file}", flush=True)


def main() -> None:
    input_dir = find_input_dir()
    files = list_txt_files(input_dir)
    print(f"发现 {len(files)} 个 TXT 文件，开始生成总结...", flush=True)
    output_file = Path(f"总结_opencode_{MODEL}.txt")
    summarize_files(files, output_file)


if __name__ == "__main__":
    main()
