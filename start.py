"""C.A.S.S.I.E. API 版 开始脚本。

职责：
  1. 检查仓库有没有新版本
  2. 有新版本 → 通知本地网页游戏 + 在控制台询问
  3. 确认后下载、替换（保留 cassie 与用户数据）、再通知游戏
  4. 启动 cassie_play.py

用法：
    python start.py              正常启动
    python start.py --check      只检查更新，不启动服务
    python start.py --update     跳过询问，直接更新
    python start.py --no-server  更新完不启动服务
"""

import argparse
import http.server
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

# ============================================================================
#  配置区 —— 需要你填的地方
# ============================================================================

# 【方式一，推荐】指向仓库里的版本清单，脚本读它拿到最新版本号和下载地址。
#   清单格式（放在仓库里，例如 version.json）：
#     { "version": "1.2.0",
#       "url": "https://github.com/你/仓库/releases/download/v1.2.0/cassie-api.zip",
#       "notes": "这次改了什么" }
UPDATE_MANIFEST_URL = ""

# 【方式二】只填仓库，脚本走 GitHub Releases API 取最新 release。
#   例如 "leisiyu/cassie"。私有仓库还要填 GITHUB_TOKEN。
UPDATE_REPO = ""

# 方式二用哪个分支的清单来判断（留空则只用 Releases 的 tag）
UPDATE_BRANCH = ""

# 私有仓库需要的 token；公开仓库留空即可。
GITHUB_TOKEN = ""

# 给本地网页游戏推送更新消息的端口（不要和 CASSIE 的 8080 冲突）。
NOTIFY_PORT = 8099

# 更新时【不替换】的东西，相对路径，可以是文件或文件夹。
#   cassie         —— 494 MB 音频素材，仓库里没有，必须留着
#   alarms         —— 警报音频（24 MB），仓库里可能也没有
#   json/settings.json / json/alarms —— 对方的设置和自定义警报，属于用户数据
# 想严格按「除了 cassie 以外全部替换」，把这里改成 ("cassie",) 即可，
# 但那样会清掉对方的设置与警报。
PRESERVE = ("cassie", "alarms", "json/settings.json", "json/alarms")

# 始终跳过（版本控制目录与缓存）。
SKIP_NAMES = {".git", "__pycache__", ".venv", "venv", ".idea", ".vscode"}

# 覆盖但不要先删（正在运行的脚本在 Windows 上删不掉，直接覆盖即可）。
OVERWRITE_ONLY = {"start.py"}

CHECK_TIMEOUT = 15          # 检查更新的网络超时（秒）
DOWNLOAD_TIMEOUT = 60       # 下载超时（秒）
ASK_TIMEOUT = 120           # 控制台询问等待多久（秒），超时视为不更新
NOTIFY_GRACE = 8            # 不启动服务时，通知服务再保留多久（秒）供游戏读最终状态
SERVER_PORT = 8080          # CASSIE 服务端口

# ============================================================================

PROJECT_ROOT = Path(__file__).resolve().parent
LOCAL_VERSION_FILE = PROJECT_ROOT / "version.json"
SERVER_SCRIPT = "cassie_play.py"

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass


def log(message):
    print("[CASSIE] {}".format(message), flush=True)


def version_tuple(text):
    """把 '1.2.3' 变成 (1, 2, 3) 以便比较；非数字部分忽略。"""
    parts = []
    for chunk in str(text or "").strip().lstrip("vV").split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def is_newer(remote, local):
    return version_tuple(remote) > version_tuple(local)


def read_local_version():
    try:
        data = json.loads(LOCAL_VERSION_FILE.read_text(encoding="utf-8"))
        return str(data.get("version") or "").strip() or "0.0.0"
    except Exception:
        return "0.0.0"


# ---------------------------------------------------------------------------
#  给网页游戏推送消息的本地服务
# ---------------------------------------------------------------------------

class UpdateNotifier:
    """一个极小的 HTTP 服务，让本地网页游戏能实时收到更新状态。

    接口：
        GET  /status   当前状态（JSON），适合轮询
        GET  /events   SSE 事件流，适合 EventSource 实时接收
        GET  /         一张自检页，浏览器打开能看到是否连通
        POST /decide   {"update": true|false} —— 让游戏替玩家做决定
    """

    def __init__(self, port):
        self.port = port
        self.lock = threading.Lock()
        self.subscribers = []
        self.decision = None
        self.decision_event = threading.Event()
        self.state = {
            "stage": "idle",
            "current_version": read_local_version(),
            "latest_version": "",
            "notes": "",
            "percent": 0,
            "message": "等待检查更新",
            "updated_at": time.time(),
        }
        self.server = None
        self.thread = None

    def snapshot(self):
        with self.lock:
            return dict(self.state)

    def set_state(self, broadcast=True, **fields):
        with self.lock:
            self.state.update(fields)
            self.state["updated_at"] = time.time()
            payload = dict(self.state)
        if broadcast:
            self._broadcast(payload)
        return payload

    def _broadcast(self, payload):
        dead = []
        for subscriber in list(self.subscribers):
            try:
                subscriber.put_nowait(payload)
            except Exception:
                dead.append(subscriber)
        for subscriber in dead:
            try:
                self.subscribers.remove(subscriber)
            except ValueError:
                pass

    def wait_decision(self, timeout):
        """等游戏通过 /decide 给答复；超时返回 None。"""
        if self.decision_event.wait(timeout):
            return self.decision
        return None

    def submit_decision(self, value):
        self.decision = bool(value)
        self.decision_event.set()

    def start(self):
        notifier = self
        port = self.port

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def _cors(self):
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")

            def _json(self, payload, status=200):
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=UTF-8")
                self.send_header("Content-Length", str(len(body)))
                self._cors()
                self.end_headers()
                self.wfile.write(body)

            def do_OPTIONS(self):
                self.send_response(204)
                self._cors()
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_GET(self):
                path = self.path.split("?")[0]
                if path == "/status":
                    self._json(notifier.snapshot())
                elif path == "/events":
                    self._sse()
                elif path == "/":
                    self._json({"service": "cassie-update-notifier",
                                "endpoints": ["/status", "/events", "/decide"],
                                "state": notifier.snapshot()})
                else:
                    self._json({"error": "not found"}, 404)

            def do_POST(self):
                path = self.path.split("?")[0]
                if path != "/decide":
                    self._json({"error": "not found"}, 404)
                    return
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                    body = self.rfile.read(length).decode("utf-8") if length else "{}"
                    data = json.loads(body or "{}")
                except Exception as error:
                    self._json({"ok": False, "error": str(error)}, 400)
                    return
                value = data.get("update", data.get("ok"))
                if value is None:
                    self._json({"ok": False, "error": "缺少 update 字段"}, 400)
                    return
                notifier.submit_decision(value)
                self._json({"ok": True, "accepted": bool(value)})

            def _sse(self):
                subscriber = queue.Queue()
                notifier.subscribers.append(subscriber)
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream; charset=UTF-8")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Connection", "keep-alive")
                    self._cors()
                    self.end_headers()
                    self._write_sse(notifier.snapshot())
                    while True:
                        try:
                            payload = subscriber.get(timeout=15)
                        except queue.Empty:
                            self.wfile.write(b": keepalive\n\n")
                            self.wfile.flush()
                            continue
                        self._write_sse(payload)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                    pass
                finally:
                    if subscriber in notifier.subscribers:
                        notifier.subscribers.remove(subscriber)

            def _write_sse(self, payload):
                chunk = "data: {}\n\n".format(
                    json.dumps(payload, ensure_ascii=False)).encode("utf-8")
                self.wfile.write(chunk)
                self.wfile.flush()

        try:
            self.server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
        except OSError as error:
            log("通知服务端口 {} 用不了（{}），更新照常，但游戏收不到消息。".format(port, error))
            return False
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       kwargs={"poll_interval": 0.3},
                                       daemon=True, name="cassie-notifier")
        self.thread.start()
        log("更新通知服务已启动：http://127.0.0.1:{}/events  （游戏用 EventSource 接）".format(port))
        return True

    def stop(self):
        if self.server:
            try:
                self.server.shutdown()
                self.server.server_close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
#  检查更新
# ---------------------------------------------------------------------------

def http_json(url, timeout=CHECK_TIMEOUT, headers=None):
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def github_headers():
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "cassie-updater"}
    if GITHUB_TOKEN:
        headers["Authorization"] = "Bearer {}".format(GITHUB_TOKEN)
    return headers


def fetch_manifest():
    """返回 {'version', 'url', 'notes'}，取不到返回 None。"""
    if UPDATE_MANIFEST_URL:
        data = http_json(UPDATE_MANIFEST_URL)
        return {
            "version": str(data.get("version") or "").strip(),
            "url": str(data.get("url") or data.get("download") or "").strip(),
            "notes": str(data.get("notes") or "").strip(),
        }

    if UPDATE_REPO:
        # 先从分支上的 version.json 读下载地址，再退回 Releases 的 zip 包
        raw = ""
        if UPDATE_BRANCH:
            raw = "https://raw.githubusercontent.com/{}/{}/version.json".format(
                UPDATE_REPO, UPDATE_BRANCH)
        if raw:
            try:
                data = http_json(raw)
                url = str(data.get("url") or "").strip()
                version = str(data.get("version") or "").strip()
                if version and url:
                    return {"version": version, "url": url,
                            "notes": str(data.get("notes") or "").strip()}
            except Exception:
                pass

        release = http_json(
            "https://api.github.com/repos/{}/releases/latest".format(UPDATE_REPO),
            headers=github_headers())
        assets = release.get("assets") or []
        url = assets[0].get("browser_download_url", "") if assets else ""
        if not url:
            url = release.get("zipball_url", "")
        return {
            "version": str(release.get("tag_name") or "").strip(),
            "url": url,
            "notes": str(release.get("body") or "").strip(),
        }

    return None


def check_for_update():
    """返回 (manifest, error)；没有可用配置时 manifest 为 None 且 error 为提示语。"""
    if not UPDATE_MANIFEST_URL and not UPDATE_REPO:
        return None, ("还没配置更新源：请在 start.py 顶部填 UPDATE_MANIFEST_URL "
                      "或 UPDATE_REPO。")
    try:
        manifest = fetch_manifest()
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None, "更新源返回 404：地址或分支不对，或者仓库是私有的（需要 GITHUB_TOKEN）。"
        return None, "检查更新失败：HTTP {} {}".format(error.code, error.reason)
    except Exception as error:
        return None, "检查更新失败：{}".format(error)
    if not manifest or not manifest.get("version"):
        return None, "更新源没有给出有效的版本号。"
    return manifest, None


# ---------------------------------------------------------------------------
#  下载与替换
# ---------------------------------------------------------------------------

def download(url, destination, notifier, headers=None):
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT) as response:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        last_report = 0.0
        with open(destination, "wb") as handle:
            while True:
                chunk = response.read(262144)
                if not chunk:
                    break
                handle.write(chunk)
                done += len(chunk)
                now = time.time()
                if now - last_report > 0.4:
                    last_report = now
                    percent = int(done * 100 / total) if total else 0
                    notifier.set_state(stage="downloading", percent=percent,
                                       message="正在下载 {:.1f} MB{}".format(
                                           done / 1048576,
                                           " / {:.1f} MB".format(total / 1048576) if total else ""))
    return done


def extract_package(archive, target):
    """解压并把 GitHub 归档多出来的顶层目录剥掉。"""
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        _safe_extract(bundle, target)

    entries = [item for item in target.iterdir() if item.name not in SKIP_NAMES]
    if len(entries) == 1 and entries[0].is_dir():
        inner = entries[0]
        if (inner / SERVER_SCRIPT).exists():
            # 形如 repo-main/... 的归档，把里面那层提上来
            staging = target.parent / (target.name + "_flat")
            if staging.exists():
                shutil.rmtree(staging)
            inner.rename(staging)
            shutil.rmtree(target)
            staging.rename(target)
    return target


def _skipped(relative):
    """路径里只要有一段属于 SKIP_NAMES 就跳过。

    不能靠 os.walk 的 dirs[:] 过滤：topdown=False 时子目录在 yield 之前就已经
    递归完了，那样过滤拦不住 .git 里的文件，会把它们当垃圾删掉。
    """
    return any(part in SKIP_NAMES for part in Path(relative).parts)


def _preserved(relative, preserve):
    """relative 本身被保留，或它是某个被保留路径的上级目录。"""
    low = str(relative).replace("\\", "/").strip("/").lower()
    if not low:
        return True
    for item in preserve:
        item_low = str(item).replace("\\", "/").strip("/").lower()
        if low == item_low or low.startswith(item_low + "/"):
            return True
        if item_low.startswith(low + "/"):
            return True
    return False


def _safe_extract(bundle, target):
    """解压前挡住路径穿越（zip 里带 ../ 或绝对路径）。"""
    target = Path(target).resolve()
    for member in bundle.infolist():
        name = member.filename.replace("\\", "/")
        if name.startswith("/") or ".." in Path(name).parts or (len(name) > 1 and name[1] == ":"):
            raise RuntimeError("更新包里含有不安全的路径：{}".format(member.filename))
        destination = (target / name).resolve()
        if not str(destination).startswith(str(target)):
            raise RuntimeError("更新包里含有越界路径：{}".format(member.filename))
    bundle.extractall(target)


def apply_update(source, project, notifier, preserve=PRESERVE):
    if not (source / SERVER_SCRIPT).exists():
        raise RuntimeError("更新包里没有 {}，看起来不是 CASSIE 的包，已中止。".format(SERVER_SCRIPT))

    # 暂存目录绝不能放在项目里面：删除步骤会清掉一切不在保留列表里的东西，
    # 那样会先把暂存目录（连同刚解压出来的新文件）删掉，结果就是「全删了、啥也没写」。
    source_real = str(Path(source).resolve())
    project_real = str(Path(project).resolve())
    if source_real == project_real or source_real.startswith(project_real + os.sep):
        raise RuntimeError("更新暂存目录不能在项目目录内（{}）。".format(source))

    preserve = tuple(preserve)
    removed, copied, skipped = [], [], []

    # 1) 删掉所有不该留的（自底向上，先文件后目录）
    for current, dirs, files in os.walk(project, topdown=False):
        current_path = Path(current)
        for name in files:
            target = current_path / name
            relative = target.relative_to(project)
            if _skipped(relative) or _preserved(relative, preserve):
                continue
            if str(relative).replace("\\", "/") in OVERWRITE_ONLY:
                continue
            try:
                target.unlink()
                removed.append(str(relative))
            except OSError as error:
                skipped.append("{}（{}）".format(relative, error))
        for name in dirs:
            target = current_path / name
            relative = target.relative_to(project)
            if _skipped(relative) or _preserved(relative, preserve):
                continue
            try:
                shutil.rmtree(target)
                removed.append(str(relative) + "/")
            except OSError as error:
                skipped.append("{}（{}）".format(relative, error))

    # 2) 拷贝新文件
    total_files = sum(len(files) for _, _, files in os.walk(source))
    done = 0
    for current, dirs, files in os.walk(source):
        current_path = Path(current)
        for name in files:
            src = current_path / name
            relative = src.relative_to(source)
            if _skipped(relative) or _preserved(relative, preserve):
                continue
            dst = project / relative
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copied.append(str(relative))
            done += 1
            if total_files and done % 20 == 0:
                notifier.set_state(stage="applying",
                                   percent=int(done * 100 / total_files),
                                   message="正在替换文件 {}/{}".format(done, total_files))

    return removed, copied, skipped


# ---------------------------------------------------------------------------
#  询问
# ---------------------------------------------------------------------------

def ask_update(notifier, manifest):
    """控制台 + 游戏，两边谁先答都算。返回 True 表示更新。

    只起一个读取线程：反复起线程去抢 input() 会互相干扰。
    """
    notifier.decision_event.clear()
    notifier.decision = None
    notifier.set_state(stage="update_available",
                       latest_version=manifest["version"],
                       notes=manifest.get("notes", ""),
                       message="发现新版本 {}".format(manifest["version"]))

    log("发现新版本：{}（当前 {}）".format(manifest["version"], read_local_version()))
    if manifest.get("notes"):
        log("更新说明：{}".format(manifest["notes"]))
    log("已在 /events 通知游戏；也可以在游戏里点「更新」替你做决定。")

    holder = {}

    def asker():
        try:
            holder["text"] = input("要现在更新吗？[y/N]（游戏里也能回答，回车=跳过） ")
        except EOFError:
            # 没有交互式控制台（stdin 被重定向、被脚本拉起等）。
            # 这不能当成「玩家说了不」，否则游戏那边的答复永远轮不上。
            holder["eof"] = True
        except KeyboardInterrupt:
            holder["text"] = ""

    threading.Thread(target=asker, daemon=True, name="cassie-ask").start()

    started = time.time()
    deadline = started + ASK_TIMEOUT
    while time.time() < deadline:
        if notifier.wait_decision(0.25) is not None:
            decision = bool(notifier.decision)
            log("游戏那边给出了答复：{}".format("更新" if decision else "跳过"))
            return decision
        if "text" in holder:
            return holder["text"].strip().lower() in ("y", "yes", "是", "1", "true")
        if "eof" in holder and not notifier.subscribers and time.time() - started > 3:
            log("没有交互式控制台，也没有游戏在监听，跳过更新。")
            return False
    log("等待 {} 秒没有答复，跳过更新。".format(ASK_TIMEOUT))
    return False


# ---------------------------------------------------------------------------
#  主流程
# ---------------------------------------------------------------------------

def run_server():
    log("启动 CASSIE 服务：{}".format(SERVER_SCRIPT))
    return subprocess.Popen([sys.executable, SERVER_SCRIPT], cwd=str(PROJECT_ROOT))


def main():
    parser = argparse.ArgumentParser(description="CASSIE API 版开始脚本")
    parser.add_argument("--check", action="store_true", help="只检查更新，不启动服务")
    parser.add_argument("--update", action="store_true", help="跳过询问，直接更新")
    parser.add_argument("--no-server", action="store_true", help="更新完不启动服务")
    parser.add_argument("--no-notify", action="store_true", help="不启动通知服务")
    parser.add_argument("--dry-run", action="store_true", help="只显示会删改哪些文件")
    args = parser.parse_args()

    log("目录：{}".format(PROJECT_ROOT))
    log("本地版本：{}".format(read_local_version()))

    notifier = UpdateNotifier(NOTIFY_PORT)
    if not args.no_notify:
        notifier.start()

    try:
        notifier.set_state(stage="checking", message="正在检查更新")
        manifest, error = check_for_update()

        if error:
            log(error)
            notifier.set_state(stage="up_to_date", message=error)
        elif not is_newer(manifest["version"], read_local_version()):
            log("已是最新版本（{}）。".format(read_local_version()))
            notifier.set_state(stage="up_to_date",
                               latest_version=manifest["version"],
                               message="已是最新版本")
        else:
            if args.check:
                # --check 只报告，不询问也不更新
                log("发现新版本 {}（当前 {}）。运行 python start.py 即可更新。".format(
                    manifest["version"], read_local_version()))
                notifier.set_state(stage="update_available",
                                   latest_version=manifest["version"],
                                   notes=manifest.get("notes", ""),
                                   message="发现新版本 {}".format(manifest["version"]))
            else:
                proceed = args.update or ask_update(notifier, manifest)
                if not proceed:
                    notifier.set_state(stage="cancelled", message="已跳过本次更新")
                    log("已跳过更新。")
                else:
                    notifier.set_state(stage="updating", percent=0, message="开始更新")
                    # 下载与解压都在系统临时目录里做，不放进项目目录
                    work_dir = Path(tempfile.mkdtemp(prefix="cassie_update_"))
                    archive = work_dir / "update.zip"
                    staging = work_dir / "staging"
                    try:
                        log("下载：{}".format(manifest["url"]))
                        size = download(manifest["url"], archive, notifier,
                                        headers=github_headers() if "github" in manifest["url"] else None)
                        log("下载完成：{:.1f} MB".format(size / 1048576))

                        notifier.set_state(stage="applying", percent=0, message="正在解压")
                        if staging.exists():
                            shutil.rmtree(staging)
                        extract_package(archive, staging)

                        if args.dry_run:
                            removed, copied, skipped = [], [], []
                            for current, dirs, files in os.walk(staging):
                                dirs[:] = [d for d in dirs if d not in SKIP_NAMES]
                                for name in files:
                                    relative = Path(current, name).relative_to(staging)
                                    if not _preserved(relative, PRESERVE):
                                        copied.append(str(relative))
                            log("[dry-run] 会写入 {} 个文件，保留 {}".format(len(copied), PRESERVE))
                        else:
                            removed, copied, skipped = apply_update(staging, PROJECT_ROOT, notifier)
                            log("替换完成：删除 {} 项，写入 {} 个文件".format(len(removed), len(copied)))
                            if skipped:
                                log("跳过 {} 项（被占用）：{}".format(len(skipped), skipped[:5]))

                            version_file = PROJECT_ROOT / "version.json"
                            version_file.write_text(
                                json.dumps({"version": manifest["version"]}, ensure_ascii=False, indent=2),
                                encoding="utf-8")

                        notifier.set_state(stage="done", percent=100,
                                           current_version=manifest["version"],
                                           message="更新完成，版本 {}".format(manifest["version"]))
                        log("更新完成。")
                    except Exception as error:
                        notifier.set_state(stage="failed", message="更新失败：{}".format(error))
                        log("更新失败：{}".format(error))
                    finally:
                        shutil.rmtree(work_dir, ignore_errors=True)

        if args.check or args.no_server:
            # 不启动服务时不要把进程永久挂住：留一小段时间让游戏读到最终状态就退出
            if not args.no_notify:
                log("通知服务再保留 {} 秒供游戏读取最终状态，然后退出。".format(NOTIFY_GRACE))
                time.sleep(NOTIFY_GRACE)
            return 0

        child = run_server()
        try:
            return child.wait()
        except KeyboardInterrupt:
            child.terminate()
            return 0
    except KeyboardInterrupt:
        log("已中断。")
        return 130
    finally:
        notifier.stop()


if __name__ == "__main__":
    sys.exit(main())
