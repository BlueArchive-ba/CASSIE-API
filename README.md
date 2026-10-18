# C.A.S.S.I.E. API 版

C.A.S.S.I.E. 广播生成器的**纯 API 版本**：只提供 HTTP 接口，不提供任何网页界面，
调用即**实时播放**（不是生成音频文件）。供本地网页游戏等外部程序调用。

- 纯 API，无界面、无历史记录、无预设、无文档页、无音频导出
- 文本指令完整支持（声道、偏移、警报、特殊词、数字朗读）
- 警报占用 9~12 号专用通道，最多同时 4 条
- 内置更新检查与自动更新，并通过本地事件通道通知网页游戏
- 附带 `cassie_api.py` Python 客户端与 `api_test.html` 调用测试页

---

## 目录

- [1. 目录结构](#1-目录结构)
- [2. 安装](#2-安装)
- [3. 运行](#3-运行)
- [4. HTTP API 参考](#4-http-api-参考)
- [5. 可调参数](#5-可调参数)
- [6. 文本指令语法](#6-文本指令语法)
- [7. 警报](#7-警报)
- [8. 自动更新](#8-自动更新)
- [9. 给网页游戏接收更新消息](#9-给网页游戏接收更新消息)
- [10. Python 客户端](#10-python-客户端)
- [11. 调用测试页](#11-调用测试页)
- [12. 故障排查](#12-故障排查)
- [13. 与完整版的区别](#13-与完整版的区别)

---

## 1. 目录结构

```
CASSIE API/
├── start.py                开始脚本：检查更新 → 通知游戏 → 更新 → 启动服务
├── cassie_play.py          CASSIE 服务本体（HTTP API）
├── cassie_api.py           Python 客户端
├── api_test.html           调用测试页（双击打开即可，纯本地文件）
├── version.json            当前版本号，更新脚本据此比对
├── README.md               本文件
├── cassie/                 音频素材（约 494 MB，随包附带）
│   ├── words/              单词音频（988 个）
│   └── sounds/             铃声（41 个，含 bg_4..bg_40 背景铃声）
├── alarms/                 警报音频源文件（.wav）
└── json/
    ├── settings.json       默认设置
    └── alarms/<ID>.json    保存的警报
```

---

## 2. 安装

只需要 **Python 3.8+** 和以下依赖：

```bash
pip install bottle cheroot pygame pydub numpy scipy
```

音频格式转换（部分铃声/导出）还需要 **ffmpeg** 在 PATH 里；纯播放通常不需要。

素材已随目录附带，**不需要额外下载**。若 `cassie/words` 为空，服务启动时会提示。

---

## 3. 运行

### 3.1 推荐：用开始脚本

```bash
cd CASSIE API
python start.py
```

它会依次做四件事：

1. 检查仓库有没有新版本（需先在 `start.py` 顶部填更新源，见 [第 8 节](#8-自动更新)）
2. 有更新 → 通过本地事件通道通知游戏，并在控制台询问
3. 确认后下载并替换（保留 `cassie/` 与用户数据）
4. 启动 `cassie_play.py`

**启动成功的标志**：看到 `API 已就绪：http://127.0.0.1:8080/api/v1`。

### 3.2 直接跑服务（不用更新检查）

```bash
python cassie_play.py
```

### 3.3 start.py 的参数

| 参数 | 作用 |
|---|---|
| `--check` | 只检查更新并报告，不询问、不更新、不启动服务 |
| `--update` | 跳过询问，直接更新 |
| `--no-server` | 更新完不启动服务（通知通道多保留 8 秒供游戏读最终状态） |
| `--no-notify` | 不启动通知服务（游戏收不到消息） |
| `--dry-run` | 只列出会写入哪些文件，不真正替换 |
| `--version` | 打印本地 `version.json` 里的版本号后退出 |
| `--pack [ZIP]` | 把代码打成更新包（默认 `dist/cassie-api-<版本>.zip`）后退出 |

### 3.4 服务监听地址

默认 **`127.0.0.1:8080`**（只监听本机 IPv4，改动见 `cassie_play.py` 里的 `API_HOST` 与 `port`）。

> 注意：绑定写的是 IPv4 字面量 `127.0.0.1`，不是 `localhost`。Windows 上 `localhost`
> 只解析到 IPv6 的 `::1`，两者是不同地址，写错会导致「浏览器能开、程序连不上」。
>
> 要让别的机器调用，把 `API_HOST` 改成 `'0.0.0.0'`，并**务必**设置环境变量
> `CASSIE_API_KEY`，否则同网段任何人都能触发广播。

---

## 4. HTTP API 参考

### 4.1 通用约定

- 所有接口都在 `/api/v1` 前缀下，`GET /api/v1` 返回接口清单
- 请求体用 JSON，`Content-Type: application/json`
- 已开启 CORS（`Access-Control-Allow-Origin: *`），所以 `file://` 打开的页面也能调
- `OPTIONS` 预检返回 204，已带齐 CORS 头

**成功响应**

```json
{ "ok": true, "api_version": "v1", "data": { } }
```

**失败响应**（HTTP 4xx/5xx）

```json
{
  "ok": false,
  "api_version": "v1",
  "error": {
    "code": "unknown_fields",
    "message": "不支持的参数: bogus",
    "unknown_fields": ["bogus"]
  }
}
```

常见的 `code`：`empty_text`、`unknown_fields`、`invalid_json`、`invalid_value`、
`no_fields`、`playback_rejected`、`plan_failed`。

> **参数名写错会明确报错**（`unknown_fields`），不会被静默忽略。
> 这是故意的：以前静默丢弃，导致「设了没反应也不报错」，极难排查。

**鉴权**：设置环境变量 `CASSIE_API_KEY` 后，每个请求都要带 `X-API-Key` 头，否则返回 401。

**语言**：带 `X-Cassie-Lang: en` 头可让错误消息用英文。

### 4.2 接口一览

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/v1` | 接口清单、参数默认值 |
| GET | `/api/v1/health` | 环境与素材自检 |
| GET | `/api/v1/words` | 可用单词列表 |
| GET | `/api/v1/sounds` | 可用铃声列表 |
| POST | `/api/v1/validate` | 拼写检查（不播放） |
| POST | `/api/v1/plan` | 生成时间线（不播放、不出音频） |
| POST | `/api/v1/play` | **实时播放**，立即返回 202 |
| POST | `/api/v1/stop` | 请求停止 |
| GET | `/api/v1/status` | 播放状态 |
| GET | `/api/v1/settings` | 读取当前设置与默认值 |
| POST / PUT | `/api/v1/settings` | 修改并保存设置 |

### 4.3 `GET /api/v1/health`

```json
{
  "ok": true,
  "data": {
    "project_version": "1.1.0",
    "status": "ok",
    "playing": false,
    "mixer_initialized": true,
    "audio_device_count": 2,
    "spatial_quality_levels": [0, 1, 2, 3, 4, 5, 6],
    "features": { "spoken_label": true, "number_words": true, "sentence_mode": true },
    "library": {
      "words_dir": ".../cassie/words", "word_files": 988,
      "sounds_dir": ".../cassie/sounds", "sound_files": 41
    }
  }
}
```

适合程序启动时做一次自检。

### 4.4 `POST /api/v1/validate`

请求：`{"text": "attention , zzzz ."}`

```json
{ "ok": true, "data": { "text": "attention , zzzz .", "not_found": ["zzzz"], "ok": false } }
```

`data.ok` 为 `false` 表示有词不在词库里。指令（`[channel:]`、`[alert:]` 等）不会被误报。

### 4.5 `POST /api/v1/plan`

请求：`{"text": "...", ...任意可调参数}`

返回完整时间线，**不播放**：

```json
{
  "ok": true,
  "data": {
    "text": "attention , all unit report .",
    "errors": [],
    "word_count": 4,
    "event_count": 5,
    "content_ms": 5392,
    "duration_ms": 8127,
    "tail_ms": 2735,
    "channels_used": [0, 8],
    "elapsed_ms": 1561,
    "settings": { "speed": -10, "include_bell": false, "...": "本次实际生效的设置" },
    "events": [
      { "index": 0, "channel": 8, "label": "bg_10", "start_ms": 0,
        "end_ms": 20300, "duration_ms": 20300, "slot_ms": 20300, "is_alarm": false }
    ]
  }
}
```

| 字段 | 说明 |
|---|---|
| `content_ms` | 正文时间线长度（不含混响拖尾） |
| `duration_ms` | 总长，含混响拖尾 |
| `tail_ms` | `duration_ms - content_ms` |
| `events[].slot_ms` | 该事件占用的时间槽 |
| `events[].duration_ms` | 该事件音频实际长度（开空间效果时会比 `slot_ms` 长，多出拖尾） |
| `events[].is_alarm` | 是否来自 `[alert:]` |
| `settings` | 本次调用**实际生效**的设置，便于确认参数有没有传对 |

### 4.6 `POST /api/v1/play`

请求：`{"text": "...", ...可调参数}`

**异步**：立即返回 `202`，播放由后台线程进行。

```json
{ "ok": true, "data": { "playing": true, "text": "..." } }
```

正在播放时再调用会返回 `409 playback_rejected`。

### 4.7 `POST /api/v1/stop` 与 `GET /api/v1/status`

`/stop` 只是**置停止标志**，当前片段播完才真的停（铃声可能很长，但停止最多等一个片段）：

```json
{ "ok": true, "data": { "playing": false, "stop_requested": true } }
```

`/status`：

```json
{ "ok": true, "data": { "playing": true, "stop_requested": false, "play_lock_held": true } }
```

三个字段要分开看：

| 字段 | 含义 |
|---|---|
| `playing` | 音频是否已经在响 |
| `play_lock_held` | 是否占着播放权。**`playing=false` 且 `play_lock_held=true` = 正在合成音频**（长文本 + 空间效果要好几秒），这时不能当成「已播完」 |
| `stop_requested` | 是否已请求停止 |

> 轮询建议：等到 `playing` 变 `false` **且** `play_lock_held` 变 `false`，才算真的结束。

### 4.8 `GET /api/v1/settings`

```json
{
  "ok": true,
  "data": {
    "settings": { "speed": -10, "include_bell": false, "...": "..." },
    "defaults": { "speed": -10, "...": "..." },
    "mutable_fields": ["pitch", "speed", "..."]
  }
}
```

### 4.9 `POST` / `PUT /api/v1/settings`

只传要改的字段；传 `{"reset": true}` 恢复默认。

```json
{ "ok": true, "data": { "applied": { "include_bell": true }, "settings": { "...": "..." } } }
```

设置会写入 `json/settings.json`，**对之后所有调用生效**。

### 4.10 调用参数的优先级（重要）

```
调用时传的参数  >  json/settings.json 里保存的设置  >  内置默认值
```

也就是说：**调用时传了参数，就会盖掉保存的设置**。所以平时应当「改设置、然后不带参数调用」；
只有想临时试一次别的参数时才在调用里传。

---

## 5. 可调参数

共 33 项，既能作为 `/plan`、`/play` 的调用参数，也能通过 `/api/v1/settings` 保存。

### 广播

| 字段 | 默认 | 说明 |
|---|---|---|
| `speed` | `-10` | 语速。负值更慢（-40 比 -10 明显慢） |
| `pitch` | `1.0` | 音高倍率 |
| `include_bell` | `false` | 广播铃声开关。旧名 `enable_bell` 仍兼容 |
| `enable_special_bell` | `false` | 用 `bell_start.wav` / `bell_end.wav` 代替背景铃声（需先开 `include_bell`） |
| `enable_number_reading` | `false` | 数字朗读 |
| `verbose_mode` | `false` | 播放日志详细输出 |
| `bell_lead_time` | `3` | 铃声前置时长（秒） |
| `bell_extra_duration` | `3` | 铃声额外时长（秒） |
| `special_bell_start` | `bell_start.wav` | 特殊铃声开头文件 |
| `special_bell_end` | `bell_end.wav` | 特殊铃声结尾文件 |
| `stutter_duration` | `0.14` | 结巴效果单次时长（秒） |

### 音色处理

| 字段 | 默认 | 说明 |
|---|---|---|
| `low_cut_freq` | `0` | 低切（Hz），0 = 关 |
| `high_cut_freq` | `0` | 高切（Hz），0 = 关 |
| `mid_boost_gain` | `2.0` | 中频提升（dB） |
| `overdrive_gain` | `0.0` | 过载（dB） |
| `clip_threshold` | `0.0` | 削波阈值，0 = 关 |
| `compressor_threshold` | `-12.0` | 压缩阈值（dB） |
| `compressor_ratio` | `6.0` | 压缩比 |

### 空间效果与混响

| 字段 | 默认 | 说明 |
|---|---|---|
| `broadcast_effect_enabled` | `false` | 空间效果总开关 |
| `spatial_mode` | `word` | `word` 逐词 / `sentence` 整句 |
| `spatial_quality` | `0` | 0 最精细、6 最省时 |
| `reverb_enabled` | `true` | 混响开关 |
| `reverb_pre_delay` | `18.0` | 预延迟（ms） |
| `reverb_room_size` | `1.0` | 房间大小 |
| `reverb_decay_time` | `5.5` | 衰减时间（秒） |
| `reverb_damping` | `4000.0` | 阻尼（Hz） |
| `reverb_diffusion` | `0.72` | 扩散 |
| `reverb_tail_brightness` | `0.55` | 尾部亮度 |
| `reverb_wet` | `0.35` | 湿度 |
| `treble_stretch` | `800.0` | 高频延伸（Hz） |
| `treble_tail_gain` | `-28.0` | 尾部增益（dB） |
| `noise_volume` | `-35.0` | 底噪音量（dB） |
| `noise_type` | `pink` | `pink` / `white` / `brown` |

---

## 6. 文本指令语法

| 指令 | 说明 |
|---|---|
| `[channel:偏移量]` … `[channel:stop]` | 控制声道与偏移。偏移可正可负、可小数，声道自动计算 |
| `[alert:ID,start]` … `[alert:ID,stop]` | 叠加警报 |
| `[cd:秒数]` | 插入停顿 |
| `mtf` | 特殊词（另有 `g1`~`g9` 等） |
| `[error:数值]` | 出错标记 |

标点与停顿：句号最长、逗号次之。单词之间用空格分隔，词库外的词会在 `errors` 里报告。

示例：

```
attention , all unit report to the checkpoint . mtf epsilon 11 . move out .
```

---

## 7. 警报

警报是 `json/alarms/<ID>.json`，音频取自 `alarms/`：

```json
{
  "id": "Fire_Drill",
  "name": "Fire Drill",
  "loop": 3,
  "tracks": [
    { "audio": "Alarm.wav", "start_ms": 0, "volume_db": 0, "speed": 1,
      "trim_start_ms": 0, "trim_end_ms": null,
      "fade_in_ms": 0, "fade_out_ms": 0, "loop": false }
  ]
}
```

用法：

```
[alert:Fire_Drill,start] all unit report to the checkpoint . [alert:Fire_Drill,stop] move out .
```

规则：

- 各音轨会在服务端**混成一条**警报再播放（与编辑器里的听感一致）
- 警报占用 **9~12 号专用通道**，最多同时 4 条；这些通道不会被 `[channel]` 指令占用
  （正文 0~7，铃声 8）
- 警报**按自身长度播完**，遇到 `stop` 标签、或正文播完就被掐断
- **四条同时响就直接并排写**：

```
[alert:A,start][alert:A,stop][alert:B,start][alert:B,stop]
```

> 想让警报完整响完，块后面要留足够的正文。放在正文末尾会被立刻掐掉。

---

## 8. 自动更新

### 8.1 更新源（已配好，开箱可用）

`start.py` 顶部已经指向本仓库：

```python
UPDATE_MANIFEST_URL = ""                          # 留空：不用自定义清单
UPDATE_REPO = "BlueArchive-ba/CASSIE-API"         # 仓库
UPDATE_BRANCH = "main"                            # 读 version.json 的分支
GITHUB_TOKEN = ""                                 # 私有仓库才需要
```

检查更新时按这个顺序取：

1. 分支上的 `version.json` 里**显式写了 `url`** → 直接用这个地址（仓库主人手动指定的发布方式）
2. 有 **GitHub Release** → 用最新 release 里的 `.zip` 资产（最省流量，推荐）
3. 两者都没有 → 用 `main` 分支源码包（`codeload.github.com/.../zip/refs/heads/main`，能用但每次都要下整包）

发布新版本的流程：

1. 改代码，把 `version.json` 的 `version` 和 `cassie_play.py` 的 `PROJECT_VERSION` 一起改
2. `python start.py --pack` → 生成 `dist/cassie-api-<版本>.zip`（不含 `cassie/`、`alarms/` 与用户数据）
3. 在 GitHub 建一个 tag 为 `v<版本>` 的 Release，把 zip 传上去
4. 客户端下次 `python start.py` 就会看到新版本

`version.json` 的完整格式（`url`、`notes` 都可省略）：

```json
{
  "version": "1.2.0",
  "url": "https://github.com/BlueArchive-ba/CASSIE-API/releases/download/v1.2.0/cassie-api.zip",
  "notes": "这一版改了什么"
}
```

想换更新源：把 `UPDATE_REPO` 改成别的 `用户名/仓库名`，或者只填
`UPDATE_MANIFEST_URL` 指向任意一个清单文件。

> 一个都取不到时，脚本会提示「检查更新失败」，然后**照常启动服务**，不影响使用。

### 8.2 其它配置

```python
NOTIFY_PORT = 8099
ASK_TIMEOUT = 120
NOTIFY_GRACE = 8
PRESERVE = ("cassie", "alarms", "json/settings.json", "json/alarms")
```

- `NOTIFY_PORT`：给游戏推送消息的端口，不要和 8080 冲突
- `ASK_TIMEOUT`：询问等待秒数，超时视为不更新
- `NOTIFY_GRACE`：`--check` / `--no-server` 时通知通道多保留几秒
- `PRESERVE`：更新时原样保留的路径（见 8.4）

### 8.3 更新包怎么打包

```bash
python start.py --pack                    # → dist/cassie-api-<版本>.zip
python start.py --pack D:\out\cassie.zip  # 指定输出路径
```

`--pack` 会跳过 `cassie/`（494 MB 音频）、`alarms/`、`json/settings.json`、
`json/alarms/`、`.git`、`__pycache__` 等，只打代码与文档（约 220 KB）。

GitHub 自动生成的源码归档（形如 `仓库名-main/...`）也能直接用，脚本会自动剥掉那层目录。
包里**必须**有 `cassie_play.py`，否则脚本会判定「不是 CASSIE 的包」并中止。

### 8.4 替换规则

更新时会：

- **删除**项目里所有不在保留列表中的文件与文件夹
- **写入**更新包里的新文件
- **永久跳过** `.git`、`__pycache__`、`.venv`、`venv`、`.idea`、`.vscode`
- `start.py` 自己**只覆盖不删除**（正在运行的脚本在 Windows 上删不掉）
- 下载与解压都在**系统临时目录**里做，项目目录里不留临时文件

保留列表默认是：

| 保留项 | 为什么 |
|---|---|
| `cassie/` | 494 MB 音频，更新包里不该有，下载整包时也只会白白多占带宽 |
| `alarms/` | 警报音频（约 25 MB），同上 |
| `json/settings.json` | **对方的设置**，覆盖会重置 |
| `json/alarms/` | **对方自己做的警报**，覆盖会丢失 |

> 想严格按「除了 `cassie` 以外全部替换」，把 `PRESERVE` 改成 `("cassie",)`。
> 但那样会清掉对方的设置与警报，**除非更新包里带一份完整且正确的默认值**。

### 8.5 更新流程

```
检查更新 → 通知游戏(update_available) → 控制台询问 / 等游戏答复
   → 同意 → 通知游戏(updating) → 下载(downloading) → 解压并替换(applying)
   → 通知游戏(done) → 启动服务
   → 拒绝 → 通知游戏(cancelled) → 照常启动服务
   → 出错 → 通知游戏(failed) → 照常启动服务（旧文件可能已被部分替换）
```

---

## 9. 给网页游戏接收更新消息

开始脚本会在 `http://127.0.0.1:8099` 上开一个很小的本地服务，专门给游戏推消息。

### 9.1 三个接口

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/events` | **SSE 事件流**，用 `EventSource` 实时接收（推荐） |
| GET | `/status` | 当前状态 JSON，适合轮询 |
| POST | `/decide` | `{"update": true}` / `{"update": false}` —— 让游戏替玩家决定要不要更新 |

已开 CORS，所以游戏是 `file://` 直接打开的本地页面也能连。

### 9.2 状态对象

```json
{
  "stage": "update_available",
  "current_version": "1.1.0",
  "latest_version": "1.2.0",
  "notes": "这一版改了什么",
  "percent": 0,
  "message": "发现新版本 1.2.0",
  "updated_at": 1735900000.123
}
```

`stage` 的取值：

| stage | 含义 | 游戏该做什么 |
|---|---|---|
| `idle` | 初始 | 忽略 |
| `checking` | 正在检查 | 可显示「检查更新中」 |
| `up_to_date` | 已是最新，或检查失败（看 `message`） | 忽略 |
| **`update_available`** | **发现新版本** | **弹横幅，问玩家要不要更新** |
| `updating` | 已确认，开始更新 | 显示「更新中…」 |
| `downloading` | 下载中，`percent` 有效 | 显示进度条 |
| `applying` | 正在替换文件 | 显示「正在安装」 |
| `done` | 更新完成 | 提示「更新完成」，可让玩家重启游戏 |
| `cancelled` | 玩家/控制台选择了跳过 | 关掉横幅 |
| `failed` | 更新失败，看 `message` | 提示失败原因 |

### 9.3 最简接收方式

```html
<script>
  const cassie = new EventSource('http://127.0.0.1:8099/events');
  cassie.onmessage = (e) => {
    const s = JSON.parse(e.data);
    console.log('CASSIE 更新状态：', s.stage, s.percent + '%');
  };
</script>
```

### 9.4 完整例子：横幅 + 让玩家决定

```html
<div id="cassie-banner" style="display:none">
  CASSIE 有新版本 <b id="cassie-version"></b>
  <button id="cassie-yes">现在更新</button>
  <button id="cassie-no">跳过</button>
</div>

<script>
(function () {
  const BASE = 'http://127.0.0.1:8099';
  const banner = document.getElementById('cassie-banner');
  const version = document.getElementById('cassie-version');

  const source = new EventSource(BASE + '/events');

  source.onmessage = (event) => {
    const s = JSON.parse(event.data);

    if (s.stage === 'update_available') {
      version.textContent = s.latest_version;
      if (s.notes) banner.title = s.notes;
      banner.style.display = 'block';
    }

    if (s.stage === 'downloading') {
      version.textContent = s.percent + '%';
    }

    if (s.stage === 'done') {
      banner.textContent = 'CASSIE 已更新完成，重启游戏后生效';
    }

    if (s.stage === 'failed') {
      banner.textContent = '更新失败：' + s.message;
    }

    if (s.stage === 'cancelled') {
      banner.style.display = 'none';
    }
  };

  // 连不上不影响游戏：脚本没开通知服务时就是这个情况
  source.onerror = () => { banner.style.display = 'none'; };

  function decide(update) {
    fetch(BASE + '/decide', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ update })
    }).then(() => { banner.style.display = 'none'; });
  }

  document.getElementById('cassie-yes').onclick = () => decide(true);
  document.getElementById('cassie-no').onclick = () => decide(false);
})();
</script>
```

### 9.5 不想用 SSE？改用轮询

```js
setInterval(async () => {
  try {
    const s = await (await fetch('http://127.0.0.1:8099/status')).json();
    if (s.stage === 'update_available') {
      // 弹你自己的提示
    }
  } catch (e) {
    // 服务没开，忽略
  }
}, 2000);
```

### 9.6 关于「谁来做决定」

- **控制台**：`start.py` 会打印 `要现在更新吗？[y/N]`，回车/`n` 跳过，`y` 更新
- **游戏**：随时 `POST /decide`
- **两边谁先回答就算谁的**，另一个自动失效
- 都没回答 → 等 `ASK_TIMEOUT`（默认 120 秒）后跳过
- **没有交互式控制台时**（比如被脚本/服务拉起、stdin 被重定向），控制台不会抢答，
  会一直等游戏答复

### 9.7 自检

浏览器打开 <http://127.0.0.1:8099/> 会看到一段 JSON，包含当前状态与接口清单。
服务没起来时打不开 —— 说明游戏该走 `onerror` 分支。

---

## 10. Python 客户端

```python
from cassie_api import CassieClient

# 远程调用
with CassieClient.remote('http://127.0.0.1:8080') as c:
    c.play('attention , all unit report to the checkpoint .', speed=-10)
    c.wait_until_done()

# 也可以在本进程内直接调，不起 HTTP
with CassieClient.local() as c:
    print(c.health())
    print(c.validate('attention .'))
    print(c.describe('attention , all unit report .'))   # 打印时间线
```

可用方法：`health` `words` `sounds` `validate` `plan` `settings` `update_settings`
`play` `stop` `status` `wait_until_done` `describe` `api_documentation`。

---

## 11. 调用测试页

双击 `api_test.html` 即可（纯本地文件，通过 CORS 调本机 API）。

- 顶部**自动探测**可用地址（`127.0.0.1` / `localhost` / `[::1]` 逐个试），
  连上会显示「已连接：…」
- **广播文本**：写要播的内容
- **本次调用覆盖（可选）**：默认**不勾**，此时完全使用服务器设置。
  勾上后才会把面板里的参数随请求发出（可点「从服务器设置填入」先同步当前值）
- **服务器设置**：33 项设置分三组（广播 / 音色处理 / 混响），
  「应用并保存」写回 `json/settings.json`，对之后所有调用生效
- **调用**：播放 / 停止 / 状态 / 拼写检查 / 时间线 / 健康检查 / 接口清单 / 读设置
- **输出**：显示每次调用的原始 JSON

> 页面里勾的「广播铃声」等开关属于**本次调用覆盖**，不会改服务器设置。
> 想永久打开铃声，去「服务器设置」里勾 `include_bell` 并保存。

---

## 12. 故障排查

| 现象 | 原因与解决 |
|---|---|
| 网页显示 `Failed to fetch` / `HTTP 0` | 服务没起，或地址端口不对。确认 `python start.py` 在跑，并访问 <http://127.0.0.1:8080/api/v1/health> 验证。若服务只绑了 `::1`，把地址改成 `http://localhost:8080` |
| 改了设置但没生效 | 调用时传了同名参数，参数优先级更高。别传参数，或把参数面板的「本次调用覆盖」取消勾选 |
| 勾了广播铃声却听不到 | ① 确认勾的是**服务器设置**里的 `include_bell` 并已保存；② 确认文字够长 —— 铃声按内容长度选 `bg_N.wav`，正文播完铃声就被掐断；③ 参数名写成 `enable_bell` 也能用，但建议统一 |
| `unknown_fields` 报错 | 参数名写错了，错误消息里会列出是哪个 |
| 警报不响 | 检查块后面有没有正文（放在末尾会被立即掐断）；ID 是否与 `json/alarms/` 里的文件名一致 |
| `playing` 一直是 `false` 但播放在响 | 长文本 + 空间效果时，合成阶段 `playing=false` 而 `play_lock_held=true`，属正常 |
| 停止后没立刻停 | `/stop` 只置标志，当前片段播完才停 |
| 更新后设置被重置 | `PRESERVE` 里要有 `json/settings.json` |
| 更新后警报都没了 | `PRESERVE` 里要有 `alarms` 和 `json/alarms` |
| 游戏收不到更新消息 | 确认没用 `--no-notify`；确认 `NOTIFY_PORT` 没被占用；浏览器控制台看 `EventSource` 是否报错 |

---

## 13. 与完整版的区别

**去掉**：网页主界面、警报编辑器、历史记录、预设、帮助/开发者文档、
音频导出（`/api/v1/synthesize` 与 `/export*`）、静态文件服务。

**保留**：文本指令解析、实时播放、警报、空间效果、设置读写、Python 客户端。

**新增**：开始脚本（更新检查 + 自动更新 + 通知通道）、调用测试页。
