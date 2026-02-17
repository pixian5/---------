import json
import time
import threading
import re
import random
from pathlib import Path
from typing import List, Optional, Tuple
import urllib.error

try:
    import requests  # type: ignore
except ImportError:
    requests = None

import urllib.request

BASE_DIR = Path(__file__).resolve().parent

# 从第几个文件开始继续跑（从 1 开始）
START_INDEX = 1
#线程数
THREAD_COUNT = 20
Words=2000
API_URL = "https://opencode.ai/zen/v1/chat/completions"
API_KEYS = [
    "sk-8CzKpYr0v6YC7wrPwdBHcukNCGQ0WWVnfFikk07cB5tO1o0KktFiU3vfqVD9yTED",
    "sk-QA88Hyv5U46dKAyVNi1VYYfwBgDHnVRpfqSOUFsUCoCsGnixnMPlSzrDjq0eWUgG",
    "sk-EMpdqy5Cw0QQwRGDlkX31okfbpCQAQcNmM4dnG5mi3etGX1nVKWuXHzmHzUOae4M",
    "sk-LbbDOpqt28LlYqZk0YKwsPUlzNYXfdHMw0MEBAAY03HvL6DocQXyMsJXzqGwzBLc",
]
MODEL = "minimax-m2.5-free"

# 0 表示不截断，完整读取文件
MAX_INPUT_CHARS = 0
REQUEST_CONNECT_TIMEOUT = 20
REQUEST_READ_TIMEOUT = 40
RETRY_TIMES = 13
RETRY_DELAY = 3
FILE_RETRY_TIMES = 2
FILE_RETRY_DELAY = 8
IDLE_RETRY_SECONDS = 60
# 是否启动时清空 tmp（True=清空后重跑，False=保留以便断点续跑）
CLEAN_TMP_ON_START = False
# 临时文件已存在时的处理方式：0=跳过（不再调用 API），1=覆盖（重新调用 API）
TMP_EXISTS_MODE = 0
DEFAULT_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    # 避免被 Cloudflare 按默认 Python-urllib 指纹拦截（403/1010）
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/145.0.0.0 Safari/537.36"
    ),
}


def _build_headers(api_key: str) -> dict:
    headers = DEFAULT_HEADERS.copy()
    headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _mask_api_key(api_key: str) -> str:
    if len(api_key) <= 12:
        return api_key
    return f"{api_key[:8]}...{api_key[-6:]}"


def _available_api_keys() -> List[str]:
    return [key.strip() for key in API_KEYS if key and key.strip()]


def _pick_random_key_index(key_count: int, excluded_indices: set) -> Optional[int]:
    candidates = [idx for idx in range(key_count) if idx not in excluded_indices]
    if not candidates:
        return None
    return random.choice(candidates)


def _retry_delay_seconds(attempt: int, base_delay: int) -> int:
    # Exponential backoff: 1x, 2x, 4x...
    return base_delay * (2 ** (attempt - 1))


def _iter_exception_chain(exc: Exception):
    seen = set()
    current: Optional[BaseException] = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def _extract_http_status(exc: Exception) -> Optional[int]:
    for one_exc in _iter_exception_chain(exc):
        if requests is not None and isinstance(one_exc, requests.exceptions.HTTPError):
            if one_exc.response is not None:
                return one_exc.response.status_code
            continue
        if isinstance(one_exc, urllib.error.HTTPError):
            return one_exc.code

        msg = str(one_exc)
        status_match = re.search(r"\bhttp\s*(\d{3})\b", msg, flags=re.IGNORECASE)
        if status_match:
            return int(status_match.group(1))
    return None


def _extract_retry_after_seconds(exc: Exception) -> Optional[int]:
    for one_exc in _iter_exception_chain(exc):
        retry_after_raw = None

        if requests is not None and isinstance(one_exc, requests.exceptions.HTTPError):
            if one_exc.response is not None:
                retry_after_raw = one_exc.response.headers.get("Retry-After")
        elif isinstance(one_exc, urllib.error.HTTPError):
            retry_after_raw = one_exc.headers.get("Retry-After")

        if retry_after_raw is None:
            continue

        retry_after_raw = retry_after_raw.strip()
        if not retry_after_raw:
            continue

        try:
            retry_after = int(float(retry_after_raw))
        except ValueError:
            continue

        return max(0, retry_after)

    return None


def _is_rate_limit_exception(exc: Exception) -> bool:
    status = _extract_http_status(exc)
    if status == 429:
        return True

    msg = str(exc).lower()
    return "too many requests" in msg or "rate limit" in msg


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
    candidates = [BASE_DIR / "txt", BASE_DIR / "TXT", Path("txt"), Path("TXT")]
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
        f"\n1. 总结长度约 {Words} 字"
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
    available_keys = _available_api_keys()
    if not available_keys:
        raise ValueError("API_KEYS 为空，请在脚本中填写有效 key")

    payload = {
        "model": MODEL,
        "messages": messages,
        "temperature": 1.9,
        #"max_output_tokens": 1500,
    }
    key_count = len(available_keys)
    key_index = _pick_random_key_index(key_count, excluded_indices=set())
    if key_index is None:
        raise ValueError("未找到可用 APIKey")
    headers = _build_headers(available_keys[key_index])
    failed_key_indices: set = set()

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
            file_hint = f" ({file_name})" if file_name else ""

            can_retry = _is_retryable_exception(exc)
            if attempt < RETRY_TIMES and can_retry:
                failed_key_indices.add(key_index)
                next_key_index = _pick_random_key_index(
                    key_count=key_count,
                    excluded_indices=failed_key_indices,
                )
                if next_key_index is None:
                    # 本轮所有 key 都失败后，重置失败池再继续随机切换
                    failed_key_indices = {key_index}
                    next_key_index = _pick_random_key_index(
                        key_count=key_count,
                        excluded_indices=failed_key_indices,
                    )

                if next_key_index is None:
                    print(
                        f"{time.strftime('%H:%M:%S')} [{MODEL}] API 请求失败{file_hint}："
                        f"没有可切换的 APIKey，停止重试",
                        flush=True,
                    )
                    break

                old_key = _mask_api_key(available_keys[key_index])
                key_index = next_key_index
                new_key = _mask_api_key(available_keys[key_index])
                headers = _build_headers(available_keys[key_index])
                wait_seconds = _retry_delay_seconds(attempt, RETRY_DELAY)
                retry_after_seconds = _extract_retry_after_seconds(exc)
                if retry_after_seconds is not None:
                    wait_seconds = max(wait_seconds, retry_after_seconds)

                if _is_rate_limit_exception(exc):
                    retry_after_hint = (
                        f"（Retry-After={retry_after_seconds}s）"
                        if retry_after_seconds is not None
                        else ""
                    )
                    print(
                        f"{time.strftime('%H:%M:%S')} [{MODEL}] API 触发 Too Many Requests{file_hint}，"
                        f"切换 APIKey: {old_key} -> {new_key}；{wait_seconds}s 后重试{retry_after_hint}",
                        flush=True,
                    )
                else:
                    print(
                        f"{time.strftime('%H:%M:%S')} [{MODEL}] API 请求失败{file_hint}，"
                        f"第 {attempt}/{RETRY_TIMES} 次：{exc}；切换 APIKey: {old_key} -> {new_key}；"
                        f"{wait_seconds}s 后重试",
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


def _summary_length(summary: str) -> int:
    # Ignore whitespace when evaluating whether the summary is too short.
    return len(re.sub(r"\s+", "", summary))


def _min_summary_length() -> int:
    return max(1, Words // 4)


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
            summary_len = _summary_length(summary)
            min_len = _min_summary_length()
            if summary_len < min_len:
                raise ValueError(
                    f"summary too short: {summary_len} < {min_len} (Words={Words})"
                )
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


def summarize_files(
    files: List[Path],
    output_file: Path,
    start_index: int = 1,
    clean_tmp: bool = False,
    tmp_exists_mode: int = TMP_EXISTS_MODE,
) -> None:
    available_keys = _available_api_keys()
    if not available_keys:
        raise ValueError("API_KEYS 为空，请在脚本中填写有效 key")

    thread_count = THREAD_COUNT
    total = len(files)
    if start_index < 1 or start_index > total:
        raise ValueError(f"start_index 超出范围：{start_index}，应在 1~{total}")
    if tmp_exists_mode not in (0, 1):
        raise ValueError(f"tmp_exists_mode 仅支持 0 或 1，当前值：{tmp_exists_mode}")

    print(f"[{MODEL}] 开始处理，共 {total} 个 TXT 文件，使用 {thread_count} 线程...", flush=True)
    print(
        f"[{MODEL}] 从第 {start_index} 个文件开始：{files[start_index - 1].name}",
        flush=True,
    )

    tmp_dir = BASE_DIR / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    if clean_tmp:
        for old_file in tmp_dir.glob("*.txt"):
            old_file.unlink()
        print(f"[{MODEL}] 已清空临时目录：{tmp_dir.resolve()}", flush=True)
    else:
        mode_text = "跳过（不调用 API）" if tmp_exists_mode == 0 else "覆盖（重新调用 API）"
        print(f"[{MODEL}] 保留已有临时文件，存在则{mode_text}", flush=True)

    print(f"[{MODEL}] 输出文件: {output_file.resolve()}", flush=True)
    print(f"[{MODEL}] 临时目录: {tmp_dir.resolve()}", flush=True)

    indexed_files = list(enumerate(files, start=1))
    pending_indexed_files = indexed_files[start_index - 1 :]
    thread_buckets = [pending_indexed_files[i::thread_count] for i in range(thread_count)]
    for thread_id, bucket in enumerate(thread_buckets, start=1):
        print(
            f"[{MODEL}] 线程{thread_id} 分配 {len(bucket)} 个文件（每次请求随机选择 key）",
            flush=True,
        )

    def worker(thread_id: int, assigned_files: List[Tuple[int, Path]]) -> None:
        if not assigned_files:
            print(f"[{MODEL}] 线程{thread_id} 无任务", flush=True)
            return

        for idx, file_path in assigned_files:
            part_file = _tmp_part_path(tmp_dir, idx, total)
            if part_file.exists() and tmp_exists_mode == 0:
                print(
                    f"{time.strftime('%H:%M:%S')} [{MODEL}] [线程{thread_id}] [{idx}/{total}] "
                    f"跳过 {file_path.name}（临时文件已存在）",
                    flush=True,
                )
                continue

            summary = summarize_one_file_with_retry(file_path, idx, total, thread_id)
            part = f"第{file_path.name}章总结：{MODEL}\n{'=' * 40}\n{summary}"
            part_file.parent.mkdir(parents=True, exist_ok=True)
            part_file.write_text(part, encoding="utf-8")

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
    output_file.parent.mkdir(parents=True, exist_ok=True)
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
    while True:
        try:
            input_dir = find_input_dir()
            files = list_txt_files(input_dir)
            break
        except FileNotFoundError as exc:
            print(f"[{MODEL}] {exc}", flush=True)
            print(
                f"[{MODEL}] 请将 .txt 文件放到 {(BASE_DIR / 'TXT').resolve()} 或 {(BASE_DIR / 'txt').resolve()}，"
                f"{IDLE_RETRY_SECONDS} 秒后重试...",
                flush=True,
            )
            time.sleep(IDLE_RETRY_SECONDS)

    print(f"发现 {len(files)} 个 TXT 文件，开始生成总结...", flush=True)
    output_file = BASE_DIR / f"总结_opencode_{MODEL}.txt"
    summarize_files(
        files,
        output_file,
        start_index=START_INDEX,
        clean_tmp=CLEAN_TMP_ON_START,
        tmp_exists_mode=TMP_EXISTS_MODE,
    )


if __name__ == "__main__":
    main()
