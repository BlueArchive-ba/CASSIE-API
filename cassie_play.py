from bottle import route, run, request, static_file, response, abort, hook, HTTPResponse
import mimetypes
import base64
import datetime
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import uuid
import wave
import contextlib
import math
import random
import pygame
from pydub import AudioSegment
from pydub.silence import detect_leading_silence
import numpy as np
import colorednoise as cn

if not sys.warnoptions:
    import warnings
    warnings.filterwarnings('ignore', category=ResourceWarning)

PROJECT_BASE_PATH = os.path.dirname(os.path.abspath(__file__))
AUDIO_BASE_PATH = os.path.join(PROJECT_BASE_PATH, "cassie", "words")
SOUND_BASE_PATH = os.path.join(PROJECT_BASE_PATH, "cassie", "sounds")
AUDIO_EXTENSION = ".wav"
JSON_DIR = os.path.join(PROJECT_BASE_PATH, "json")
SETTINGS_FILE = os.path.join(JSON_DIR, "settings.json")
ALARM_DIR = os.path.join(JSON_DIR, "alarms")
ALARM_AUDIO_DIR = os.path.join(PROJECT_BASE_PATH, "alarms")
ALARM_EXTENSION = ".json"
ALERT_BLOCK_RE = re.compile(r'\[(?:alert|alart):([^\],]+)\s*,\s*(start|stop)\]', re.IGNORECASE)

API_VERSION = 'v1'
API_PREFIX = '/api/v1'

API_HOST = '127.0.0.1'
PROJECT_VERSION = '1.1.0'

BRACKET_COMMAND_RE = re.compile(r'\[[^\]]*\]')
BARE_COMMAND_WORDS = frozenset({'mtf'})

CASSIE_TAIL_FADE_REFERENCE = 0.35

ASSETS_DOWNLOAD_URL = 'https://github.com/BlueArchive-ba/CASSIE'


_PENDING_PROGRESS = threading.local()

_PENDING_TIMELINE = threading.local()

SUPPORTED_LANGUAGES = ('zh', 'en')
DEFAULT_LANGUAGE = 'zh'

def normalize_language(value):
    if value is None:
        return None
    text = str(value).strip().lower().replace('_', '-')
    if not text:
        return None
    primary = text.split('-')[0]
    return primary if primary in SUPPORTED_LANGUAGES else None

MESSAGES = {
    'zh': {
        'content_empty': '内容不能为空',
        'json_object_required': '请求体必须是 JSON 对象',
        'text_must_be_string': 'text 必须是字符串',
        'plan_failed': '解析失败: {error}',
        'read_result_failed': '读取合成结果失败: {error}',
        'unknown_fields': '不支持的参数: {fields}',
        'no_fields': '没有需要修改的参数',
        'spatial_mode_invalid': 'spatial_mode 只能是 {modes}',
        'api_key_invalid': 'API Key 无效',
        'settings_save_failed': '设置已生效但写入失败: {message}',
        'play_busy': '正在播放中，请稍后再试',
        'play_or_export_busy': '正在播放或导出中，请稍后再试',
        'play_error': '播放错误: {error}',
        'play_done': '播放完成',
        'nothing_to_export': '没有音频可导出',
        'no_export_audio': '没有可导出的音频',
        'wav_write_failed': '写入 WAV 文件失败: {error}',
        'sentence_label': '整句',
        'api_description': 'C.A.S.S.I.E. 广播生成器 HTTP API',
        'cd_missing_params': 'CD 指令参数不足：[cd:start,end,separator]',
        'cd_start_end_not_int': 'CD 指令的起止值必须是整数',
        'cd_start_end_equal': 'CD 指令的起止值不能相同',
        'mtf_invalid_params': 'MTF 指令参数无效：[mtf:word1,number1,word2,number2,scp_count]',
        'backup_missing_unit': 'backup 指令缺少单位名称',
        'warhead_invalid_type': 'warhead 指令类型必须是 start、resume 或 cancelled',
        'warhead_countdown_positive': 'warhead 指令的倒计时必须是正整数',
        'hostile_invalid_params': 'hostile_enter 指令参数无效',
        'channl_offset_invalid': '[channel] / [channl] 指令需要一个秒数偏移（可为负数），最多三位小数',
        'channl_missing_stop': '[channel] / [channl] 指令缺少配对的 [channel:stop]',
        'channl_no_free_channel': '[channel] / [channl] 指令没有可用的独立声道',
        'alert_missing_stop': '[alert] 指令缺少配对的 [alert:{0},stop]',
        'alert_not_found': '[alert] 指令引用了不存在的警报：{0}',
        'alert_no_free_channel': '[alert] 指令没有空闲的专用警报通道（最多同时 4 条警报）',
        'not_found': '[未找到] {item}',
        'bell_missing': '[铃声缺失] {item}',
        'bell_playing': '[播放铃声] {item}',
        'verbose_pause': '[停顿] {seconds}秒',
        'verbose_word': '[{index}/{total}] {word} (音高 {pitch})',
        'verbose_number': '[{index}/{total}] {word} (数字)',
        'verbose_stutter': '[{index}/{total}] {word} (卡顿{count}次, 音高 {pitch}){suffix}',
        'verbose_stutter_full': ', 完整播放',
        'verbose_stutter_only': ', 仅卡顿',
        'spatial_level_0_name': '原始',
        'spatial_level_0_summary': '不削减，与历史版本完全一致',
        'spatial_level_1_name': '轻度',
        'spatial_level_1_summary': '块长翻倍、拖尾略收短；几乎听不出差别',
        'spatial_level_2_name': '中度',
        'spatial_level_2_summary': '块长再翻倍、拖尾明显收短；拖尾变得短促',
        'spatial_level_3_name': '最大加速',
        'spatial_level_3_summary': '块长拉满、拖尾最短；只保留紧贴单词的回声',
        'spatial_level_4_name': '激进',
        'spatial_level_4_summary': '拖尾再收一半；混响变成一层薄薄的尾音',
        'spatial_level_5_name': '极限',
        'spatial_level_5_summary': '拖尾约 1/3 秒；只能听出"刚说完还有一点回响"',
        'spatial_level_6_name': '单声道混响',
        'spatial_level_6_summary': '极限档基础上把立体声混响合成单声道，再快近一倍；'
                                   '干声仍是立体声，只是拖尾左右相同、失去宽度',
        'spatial_mode_word': '逐词',
        'spatial_mode_sentence': '整句',
        'spatial_mode_word_summary': '逐词：每个单词各自加一次混响，拖尾逐词叠加，最贴近原版听感。'
                                     '耗时随词数线性增长。',
        'spatial_mode_sentence_summary': '整句：先把整句话拼好，再整体做一次后处理。拖尾只算一次，'
                                         '长广播明显更快；代价是逐词的音高/效果差异会被统一。',
        'startup_banner': 'C.A.S.S.I.E. {version}  启动于 {started_at}',
        'startup_quality_levels': '  空间效果质量档次: {count} 档',
        'startup_fingerprint': '  功能指纹: {status}{hint}',
        'startup_all_ready': '全部就绪',
        'startup_missing': '缺少 {items}',
        'startup_outdated_hint': '  ← 请确认运行的是最新代码',
        'startup_health_hint': '  /api/v1/health 可查看同样的信息（改了后端务必重启本进程）',
        'startup_open_browser': 'API 已就绪：http://127.0.0.1:{port}/api/v1  （调用测试页：双击 api_test.html）',
        'assets_missing_title': '!! 没有找到音频素材，现在还不能生成任何广播。',
        'assets_missing_where': '   期望目录: {path}',
        'assets_missing_how': '   请运行 CASSIE语音生成/cassie_download.py 下载素材，',
        'assets_missing_how2': '   或从发布页获取: {url}',
        'assets_missing_after': '   下载完成后重启本程序。',
    },
    'en': {
        'content_empty': 'Content cannot be empty',
        'json_object_required': 'Request body must be a JSON object',
        'text_must_be_string': 'text must be a string',
        'plan_failed': 'Failed to parse: {error}',
        'read_result_failed': 'Failed to read the synthesized result: {error}',
        'unknown_fields': 'Unsupported parameters: {fields}',
        'no_fields': 'No parameters to update',
        'spatial_mode_invalid': 'spatial_mode must be one of: {modes}',
        'api_key_invalid': 'Invalid API key',
        'settings_save_failed': 'Settings applied, but writing them failed: {message}',
        'play_busy': 'Already playing, please try again later',
        'play_or_export_busy': 'Already playing or exporting, please try again later',
        'play_error': 'Playback error: {error}',
        'play_done': 'Playback finished',
        'nothing_to_export': 'No audio to export',
        'no_export_audio': 'No audio available to export',
        'wav_write_failed': 'Failed to write the WAV file: {error}',
        'sentence_label': 'sentence',
        'api_description': 'C.A.S.S.I.E. broadcast generator HTTP API',
        'cd_missing_params': '[cd] command is missing parameters: [cd:start,end,separator]',
        'cd_start_end_not_int': '[cd] start and end must be integers',
        'cd_start_end_equal': '[cd] start and end must not be equal',
        'mtf_invalid_params': '[mtf] invalid parameters: [mtf:word1,number1,word2,number2,scp_count]',
        'backup_missing_unit': '[backup] command is missing the unit name',
        'warhead_invalid_type': '[warhead] type must be start, resume or cancelled',
        'warhead_countdown_positive': '[warhead] the countdown must be a positive integer',
        'hostile_invalid_params': '[hostile_enter] invalid parameters',
        'channl_offset_invalid': '[channel] / [channl] needs a seconds offset (negative allowed) with at most 3 decimal places',
        'channl_missing_stop': '[channel] / [channl] command is missing its paired [channel:stop]',
        'channl_no_free_channel': '[channel] / [channl] command has no free dedicated channel',
        'alert_missing_stop': '[alert] command is missing its paired [alert:{0},stop]',
        'alert_not_found': '[alert] command references an alarm that does not exist: {0}',
        'alert_no_free_channel': '[alert] command has no free dedicated alarm channel (at most 4 alarms at once)',
        'not_found': '[not found] {item}',
        'bell_missing': '[missing bell] {item}',
        'bell_playing': '[playing bell] {item}',
        'verbose_pause': '[pause] {seconds}s',
        'verbose_word': '[{index}/{total}] {word} (pitch {pitch})',
        'verbose_number': '[{index}/{total}] {word} (number)',
        'verbose_stutter': '[{index}/{total}] {word} (stutter x{count}, pitch {pitch}){suffix}',
        'verbose_stutter_full': ', full playback',
        'verbose_stutter_only': ', stutter only',
        'spatial_level_0_name': 'Original',
        'spatial_level_0_summary': 'No reduction, identical to earlier versions',
        'spatial_level_1_name': 'Light',
        'spatial_level_1_summary': 'Block size doubled, tail slightly shortened; barely audible',
        'spatial_level_2_name': 'Moderate',
        'spatial_level_2_summary': 'Block size doubled again, tail clearly shortened; the tail becomes brief',
        'spatial_level_3_name': 'Maximum speed',
        'spatial_level_3_summary': 'Block size maxed out, shortest tail; only echoes hugging the words remain',
        'spatial_level_4_name': 'Aggressive',
        'spatial_level_4_summary': 'Tail halved again, reverb becomes a thin layer of tail',
        'spatial_level_5_name': 'Extreme',
        'spatial_level_5_summary': 'Tail around 1/3 second; only a hint of ring-out after each word',
        'spatial_level_6_name': 'Mono reverb',
        'spatial_level_6_summary': 'Builds on Extreme by collapsing the stereo reverb to mono, '
                                   'nearly doubling the speed again; the dry signal stays stereo, '
                                   'only the tail loses its width',
        'spatial_mode_word': 'Per word',
        'spatial_mode_sentence': 'Per sentence',
        'spatial_mode_word_summary': 'Per word: each word gets its own reverb pass and the tails '
                                     'stack word by word, closest to the original sound. Cost grows '
                                     'linearly with the word count.',
        'spatial_mode_sentence_summary': 'Per sentence: the whole sentence is assembled first and '
                                         'post-processed once. The tail is computed only once, which '
                                         'is much faster on long broadcasts; the trade-off is that '
                                         'per-word pitch and effect differences are unified.',
        'startup_banner': 'C.A.S.S.I.E. {version}  started at {started_at}',
        'startup_quality_levels': '  Spatial effect quality tiers: {count}',
        'startup_fingerprint': '  Feature fingerprint: {status}{hint}',
        'startup_all_ready': 'all ready',
        'startup_missing': 'missing {items}',
        'startup_outdated_hint': '  <- please make sure the latest code is running',
        'startup_health_hint': '  /api/v1/health shows the same information '
                               '(always restart this process after backend changes)',
        'startup_open_browser': 'API ready: http://127.0.0.1:{port}/api/v1  (call test page: open api_test.html)',
        'assets_missing_title': '!! Audio assets not found — no broadcast can be generated yet.',
        'assets_missing_where': '   Expected directory: {path}',
        'assets_missing_how': '   Run CASSIE语音生成/cassie_download.py to fetch the assets,',
        'assets_missing_how2': '   or get them from the releases page: {url}',
        'assets_missing_after': '   Restart this program once the download finishes.',
    },
}

_REQUEST_LANG = threading.local()

_PROCESS_LANGUAGE = normalize_language(os.environ.get('CASSIE_LANG')) or DEFAULT_LANGUAGE

def current_language():
    language = getattr(_REQUEST_LANG, 'value', None)
    return language if language in SUPPORTED_LANGUAGES else _PROCESS_LANGUAGE

def set_language(value):
    _REQUEST_LANG.value = normalize_language(value) or DEFAULT_LANGUAGE

def language_from_request():
    for value in (request.query.get('lang'), request.headers.get('X-Cassie-Lang')):
        if value is None or not str(value).strip():
            continue
        return normalize_language(value) or DEFAULT_LANGUAGE
    return DEFAULT_LANGUAGE

@hook('before_request')
def _write_request_language():
    set_language(language_from_request())

def language_join(items, zh_separator=' 或 ', en_separator=' or '):
    separator = zh_separator if current_language() == DEFAULT_LANGUAGE else en_separator
    return separator.join(items)

def tr(key, **kwargs):
    template = (MESSAGES.get(current_language()) or {}).get(key)
    if template is None:
        template = MESSAGES[DEFAULT_LANGUAGE].get(key)
    if template is None:
        return key
    if not kwargs:
        return template
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError):
        return template

SYNTHESIS_PARAM_DEFAULTS = {
    'pitch': 1.0,
    'speed': -10,
    'enable_number_reading': False,
    'include_bell': False,
    'enable_special_bell': False,
    'low_cut_freq': 0.0,
    'high_cut_freq': 0.0,
    'mid_boost_gain': 2.0,
    'overdrive_gain': 0.0,
    'clip_threshold': 0.0,
    'compressor_threshold': -12.0,
    'compressor_ratio': 6.0,
    'reverb_enabled': True,
    'reverb_pre_delay': 18.0,
    'reverb_room_size': 1.0,
    'reverb_decay_time': 5.5,
    'reverb_damping': 4000.0,
    'reverb_diffusion': 0.72,
    'reverb_tail_brightness': 0.55,
    'reverb_wet': 0.35,
    'treble_stretch': 800.0,
    'treble_tail_gain': -28.0,
    'noise_volume': -35.0,
    'noise_type': 'pink',
    'stutter_duration': 0.14,
    'bell_lead_time': 3,
    'bell_extra_duration': 3.0,
    'special_bell_start': 'bell_start.wav',
    'special_bell_end': 'bell_end.wav',
    'broadcast_effect_enabled': False,
    'spatial_quality': 0,
    'spatial_mode': 'word',
}

API_MUTABLE_FIELDS = (
    'pitch', 'speed', 'enable_number_reading', 'include_bell', 'enable_special_bell',
    'verbose_mode',
    'low_cut_freq', 'high_cut_freq', 'mid_boost_gain', 'overdrive_gain', 'clip_threshold',
    'compressor_threshold', 'compressor_ratio', 'reverb_enabled', 'reverb_pre_delay',
    'reverb_room_size', 'reverb_decay_time', 'reverb_damping', 'reverb_diffusion',
    'reverb_tail_brightness', 'reverb_wet', 'treble_stretch', 'treble_tail_gain',
    'noise_volume', 'noise_type', 'stutter_duration', 'bell_lead_time',
    'bell_extra_duration', 'special_bell_start', 'special_bell_end',
    'broadcast_effect_enabled',
    'spatial_quality', 'spatial_mode',
)

BELL_CHANNEL = 8
ALARM_CHANNELS = (9, 10, 11, 12)
SPEECH_CHANNEL_COUNT = 8

pygame.mixer.init()
pygame.mixer.set_num_channels(max(ALARM_CHANNELS) + 1)

nato_map = {
    'alpha': 'a', 'bravo': 'b', 'charlie': 'c', 'delta': 'd',
    'echo': 'e', 'foxtrot': 'f', 'golf': 'g', 'hotel': 'h',
    'india': 'i', 'juliett': 'j', 'kilo': 'k', 'lima': 'l',
    'mike': 'm', 'november': 'n', 'oscar': 'o', 'papa': 'p',
    'quebec': 'q', 'romeo': 'r', 'sierra': 's', 'tango': 't',
    'uniform': 'u', 'victor': 'v', 'whiskey': 'w', 'xray': 'x',
    'yankee': 'y', 'zulu': 'z'
}

port = 8080

class CASSIETerminal:
    def __init__(self):
        self.is_playing = False
        self.enable_bell = False
        self.enable_special_bell = False
        self.special_bell_start = 'bell_start.wav'
        self.special_bell_end = 'bell_end.wav'
        self.enable_number_reading = False
        self.verbose_mode = False
        self.stop_requested = False
        self.stutter_duration = 0.14
        self.word_channel = 0
        self.bell_channel = 8
        self.current_input = ""
        self.settings_file = SETTINGS_FILE
        self.alarm_dir = ALARM_DIR
        self.word_set = self.load_word_set()
        self.pitch = 1.0
        self.speed = 20
        self.bell_lock = threading.Lock()
        self.play_lock = threading.Lock()
        self.settings_lock = threading.RLock()
        self.bell_lead_time = 3
        self.bell_extra_duration = 3.0

        self.broadcast_effect_enabled = False
        self.include_bell = False
        self.low_cut_freq = 0
        self.high_cut_freq = 0
        self.mid_boost_gain = 2.0
        self.overdrive_gain = 0.0
        self.clip_threshold = 0.0
        self.compressor_threshold = -12.0
        self.compressor_ratio = 6.0
        self.compressor_attack = 2.0
        self.compressor_release = 50.0
        self.reverb_enabled = True
        self.reverb_pre_delay = 18.0
        self.reverb_room_size = 1.0
        self.reverb_decay_time = 5.5
        self.reverb_damping = 4000.0
        self.reverb_diffusion = 0.72
        self.reverb_tail_brightness = 0.55
        self.reverb_wet = 0.35
        self.reverb_early_reflections = True
        self.spatial_quality = 0
        self.spatial_mode = 'word'
        self._reverb_cache = {}
        self.noise_volume = -35.0
        self.noise_type = 'pink'
        self.treble_stretch = 800.0
        self.treble_tail_gain = -28.0
        self.hiss_enabled = True
        self.hiss_start_freq = 2000.0
        self.hiss_duration = 4000.0
        self.hiss_decay_rate = 0.92
        self.hiss_blur_filter = 3000.0
        self.hiss_mix_ratio = 0.30

        self.stored_settings = self.apply_stored_settings()
        self.started_at = datetime.datetime.now().isoformat(timespec='seconds')

    def load_word_set(self):
        word_set = set()
        if os.path.exists(AUDIO_BASE_PATH):
            for f in os.listdir(AUDIO_BASE_PATH):
                if f.endswith(AUDIO_EXTENSION):
                    word_set.add(f[:-len(AUDIO_EXTENSION)])
        for nato_word in nato_map.keys():
            word_set.add(nato_word)
        for letter in 'abcdefghijklmnopqrstuvwxyz':
            word_set.add('_' + letter)
        for i in range(1, 10):
            if os.path.exists(os.path.join(AUDIO_BASE_PATH, f'g{i}{AUDIO_EXTENSION}')):
                word_set.add(f'g{i}')
        return word_set


    def load_settings(self):
        if not os.path.exists(self.settings_file):
            return {}
        try:
            with open(self.settings_file, 'r', encoding='utf-8') as f:
                content = f.read().strip()
            if not content:
                return {}
            stored = json.loads(content)
        except Exception:
            return {}
        if not isinstance(stored, dict):
            return {}
        return {key: value for key, value in stored.items()
                if key in API_MUTABLE_FIELDS}

    def save_settings(self):
        payload = {key: getattr(self, key, SYNTHESIS_PARAM_DEFAULTS.get(key))
                   for key in API_MUTABLE_FIELDS}
        try:
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            return True, ''
        except Exception as error:
            return False, str(error)

    def apply_stored_settings(self):
        stored = self.load_settings()
        for key, value in stored.items():
            if key in ('spatial_quality',):
                value = self.quality_profile(value)['level']
            elif key == 'spatial_mode':
                value = value if value in self.SPATIAL_MODES else 'word'
            setattr(self, key, value)
        self._reverb_cache.clear()
        return stored

    def get_audio_duration(self, filepath):
        if not os.path.exists(filepath):
            return 0
        try:
            with contextlib.closing(wave.open(filepath, 'r')) as f:
                frames = f.getnframes()
                rate = f.getframerate()
                return frames / float(rate)
        except:
            return 0.5

    def get_special_bell_path(self, filename, fallback):
        candidates = [
            os.path.join(SOUND_BASE_PATH, filename),
            os.path.join(AUDIO_BASE_PATH, filename)
        ]
        for path in candidates:
            if os.path.exists(path):
                return path
        return os.path.join(SOUND_BASE_PATH, fallback)

    def stop_all_audio(self):
        for channel in range(pygame.mixer.get_num_channels()):
            pygame.mixer.Channel(channel).stop()

    def wait_for_channels(self, channels=None, timeout=600, should_stop=None):
        channels = list(range(pygame.mixer.get_num_channels())) if channels is None else channels
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if should_stop is not None and should_stop():
                return False
            if not any(pygame.mixer.Channel(channel).get_busy() for channel in channels):
                return True
            time.sleep(0.01)
        return False

    def generate_noise(self, duration_ms, sample_rate=44100, channels=1, sample_width=2, noise_type='pink'):
        num_samples = int(duration_ms * sample_rate / 1000)
        if noise_type == 'pink':
            noise = cn.powerlaw_psd_gaussian(1, num_samples)
        else:
            noise = cn.powerlaw_psd_gaussian(0, num_samples)
        max_val = 2 ** (sample_width * 8 - 1) - 1
        noise = noise / np.max(np.abs(noise)) * max_val * 0.3
        noise = noise.astype(np.int16)
        if channels > 1:
            noise = np.tile(noise, channels)
        return AudioSegment(
            noise.tobytes(),
            frame_rate=sample_rate,
            sample_width=sample_width,
            channels=channels
        )

    def generate_treble_tail(self, audio):
        duration_ms = max(0.0, float(self.treble_stretch))
        if duration_ms <= 0 or len(audio) < 20:
            return AudioSegment.empty()

        try:
            high_band = audio.high_pass_filter(1500)
            samples = np.asarray(high_band.get_array_of_samples(), dtype=np.float64)
            if high_band.channels > 1:
                samples = samples.reshape((-1, high_band.channels)).mean(axis=1)
            if samples.size < 32:
                return AudioSegment.empty()

            window_size = min(samples.size, max(256, int(high_band.frame_rate * 0.12)))
            analysis = samples[-window_size:]
            analysis *= np.hanning(analysis.size)
            spectrum = np.abs(np.fft.rfft(analysis))
            frequencies = np.fft.rfftfreq(analysis.size, 1.0 / high_band.frame_rate)
            upper_frequency = min(12000.0, high_band.frame_rate / 2.0 - 100.0)
            valid = (frequencies >= 1500.0) & (frequencies <= upper_frequency)
            if not np.any(valid):
                return AudioSegment.empty()
            peak_index = np.where(valid)[0][np.argmax(spectrum[valid])]
            frequency = frequencies[peak_index]
            rms = float(np.sqrt(np.mean(analysis ** 2)))
            if rms < 1.0:
                return AudioSegment.empty()

            sample_count = max(1, int(duration_ms * high_band.frame_rate / 1000.0))
            time_axis = np.arange(sample_count, dtype=np.float64) / high_band.frame_rate
            envelope = np.exp(-3.0 * time_axis / max(duration_ms / 1000.0, 0.001))
            fade_in = min(sample_count, int(high_band.frame_rate * 0.008))
            if fade_in > 1:
                envelope[:fade_in] *= np.linspace(0.0, 1.0, fade_in)
            amplitude = min(32767.0, rms * (10.0 ** (self.treble_tail_gain / 20.0)))
            tail = np.sin(2.0 * np.pi * frequency * time_axis) * envelope * amplitude
            tail = np.clip(tail, -32768, 32767).astype(np.int16)
            if audio.channels > 1:
                tail = np.tile(tail[:, None], (1, audio.channels)).reshape(-1)
            return AudioSegment(tail.tobytes(), frame_rate=audio.frame_rate,
                                sample_width=2, channels=audio.channels)
        except Exception:
            return AudioSegment.empty()

    FDN_DELAY_LINES = (941, 1093, 1229, 1361, 1483, 1609, 1721, 1879)
    FDN_BLOCK = 64
    FDN_MIN_HF_RATIO = 0.4
    FDN_DAMPING_POLE = 0.8
    FDN_DAMPING_CHUNK = 64
    REVERB_SEND_GAIN = 0.45

    SPATIAL_QUALITY_LEVELS = (
        {
            'level': 0,
            'name': '原始',
            'summary': '不削减，与历史版本完全一致',
            'block': 64,
            'tail_factor': 0.35,
            'min_tail_sec': 0.06,
            'mono_reverb': False,
        },
        {
            'level': 1,
            'name': '轻度',
            'summary': '块长翻倍、拖尾略收短；几乎听不出差别',
            'block': 128,
            'tail_factor': 0.28,
            'min_tail_sec': 0.06,
            'mono_reverb': False,
        },
        {
            'level': 2,
            'name': '中度',
            'summary': '块长再翻倍、拖尾明显收短；拖尾变得短促',
            'block': 256,
            'tail_factor': 0.18,
            'min_tail_sec': 0.05,
            'mono_reverb': False,
        },
        {
            'level': 3,
            'name': '最大加速',
            'summary': '块长拉满、拖尾最短；只保留紧贴单词的回声',
            'block': 941,
            'tail_factor': 0.10,
            'min_tail_sec': 0.04,
            'mono_reverb': False,
        },
        {
            'level': 4,
            'name': '激进',
            'summary': '拖尾再收一半；混响变成一层薄薄的尾音',
            'block': 941,
            'tail_factor': 0.060,
            'min_tail_sec': 0.03,
            'mono_reverb': False,
        },
        {
            'level': 5,
            'name': '极限',
            'summary': '拖尾约 1/3 秒；只能听出"刚说完还有一点回响"',
            'block': 941,
            'tail_factor': 0.030,
            'min_tail_sec': 0.02,
            'mono_reverb': False,
        },
        {
            'level': 6,
            'name': '单声道混响',
            'summary': '极限档基础上把立体声混响合成单声道，再快近一倍；'
                       '干声仍是立体声，只是拖尾左右相同、失去宽度',
            'block': 941,
            'tail_factor': 0.030,
            'min_tail_sec': 0.02,
            'mono_reverb': True,
        },
    )

    SPATIAL_MODES = ('word', 'sentence')

    @classmethod
    def quality_profile(cls, level):
        try:
            index = int(level)
        except (TypeError, ValueError):
            index = 0
        index = min(max(index, 0), len(cls.SPATIAL_QUALITY_LEVELS) - 1)
        return cls.SPATIAL_QUALITY_LEVELS[index]

    def spatial_profile(self):
        return self.quality_profile(getattr(self, 'spatial_quality', 0))

    @staticmethod
    def _build_hadamard(size):
        matrix = np.ones((1, 1), dtype=np.float64)
        while matrix.shape[0] < size:
            matrix = np.block([[matrix, matrix], [matrix, -matrix]])
        return matrix / math.sqrt(matrix.shape[0])

    @staticmethod
    def _fft_convolve(signal, impulse):
        total = len(signal) + len(impulse) - 1
        size = 1 << max(1, int(total - 1).bit_length())
        spectrum = np.fft.rfft(signal, size) * np.fft.rfft(impulse, size)
        return np.fft.irfft(spectrum, size)[:total]

    def _prepare_fdn(self, frame_rate, channel):
        delay_lines = np.asarray(self.FDN_DELAY_LINES, dtype=np.float64)
        count = len(delay_lines)
        if channel > 0:
            delay_lines = delay_lines * (1.0 + 0.019 * (channel % 2) + 0.011 * (channel // 2))

        room_size = float(np.clip(self.reverb_room_size, 0.2, 3.0))
        decay = float(np.clip(self.reverb_decay_time, 0.1, 30.0))
        damping = float(np.clip(self.reverb_damping, 200.0, 18000.0))
        diffusion = float(np.clip(self.reverb_diffusion, 0.0, 1.0))

        delays = np.maximum(16, np.round(delay_lines * room_size)).astype(np.int64)
        max_delay = int(delays.max())

        feedback = np.clip(10.0 ** (-3.0 * delays / (decay * frame_rate)), 0.0, 0.9995)

        damping_mix, damping_pole = self._solve_damping(self.damping_ratio(damping))

        matrix = self._build_hadamard(count)
        matrix = diffusion * matrix + (1.0 - diffusion) * np.eye(count)

        profile = self.spatial_profile()
        block_cap = int(delays.min())
        block = max(8, min(int(profile['block']), block_cap))

        return {
            'frame_rate': int(frame_rate),
            'channel': int(channel),
            'count': count,
            'delays': delays,
            'max_delay': max_delay,
            'feedback': feedback,
            'damping_mix': damping_mix,
            'damping_pole': damping_pole,
            'matrix': matrix,
            'block': block,
            'decay': decay,
            'room_size': room_size,
            'quality_level': int(profile['level']),
        }

    def _fdn_key(self, frame_rate, channel):
        return (int(frame_rate), int(channel),
                int(self.spatial_profile()['level']),
                round(float(np.clip(self.reverb_room_size, 0.2, 3.0)), 3),
                round(float(np.clip(self.reverb_decay_time, 0.1, 30.0)), 2),
                round(float(np.clip(self.reverb_damping, 200.0, 18000.0)), 1),
                round(float(np.clip(self.reverb_diffusion, 0.0, 1.0)), 2))

    def _fdn_parameters(self, frame_rate, channel):
        key = self._fdn_key(frame_rate, channel)
        cached = self._reverb_cache.get(key)
        if cached is None:
            cached = self._prepare_fdn(frame_rate, channel)
            if len(self._reverb_cache) > 24:
                self._reverb_cache.clear()
            self._reverb_cache[key] = cached
        return cached

    def _run_fdn(self, source, params, *, inject_burst=False, tail_samples=None,
                 collect_energy=False):
        delays = params['delays']
        count = params['count']
        max_delay = params['max_delay']
        feedback = params['feedback']
        damping_mix = params['damping_mix']
        pole = params['damping_pole']
        matrix = params['matrix']
        block = params['block']

        source = np.asarray(source, dtype=np.float64).reshape(-1)
        source_length = source.size
        if tail_samples is None:
            tail_samples = int(params['decay'] * params['frame_rate'] * 1.05) + max_delay
        total = source_length + max(0, int(tail_samples))
        if total <= 0:
            return np.zeros(0), []

        buffer = np.zeros((max_delay, count), dtype=np.float64)
        wet = np.zeros(total, dtype=np.float64)
        line_columns = np.arange(count)

        burst = None
        if inject_burst:
            burst = np.random.RandomState(0x43415353).randn(count, block).astype(np.float64)
            burst /= math.sqrt(float(np.mean(burst ** 2)))

        position = 0
        read_offsets = max_delay - delays
        damp_state = np.zeros(count, dtype=np.float64)
        energy_trace = [] if collect_energy else None
        while position < total:
            span = min(block, total - position)
            rows = (read_offsets[:, None] + position + np.arange(span)[None, :]) % max_delay
            read = buffer[rows, line_columns[:, None]]

            wet[position:position + span] = read.sum(axis=0)
            mixed = matrix @ read

            if inject_burst and position < block:
                take = min(span, block - position)
                mixed[:, :take] += burst[:, :take]
            elif source_length and position < source_length:
                take = min(span, source_length - position)
                mixed[:, :take] += source[position:position + take][None, :]

            if damping_mix > 1e-6:
                for begin in range(0, span, self.FDN_DAMPING_CHUNK):
                    end = min(begin + self.FDN_DAMPING_CHUNK, span)
                    steps = np.arange(end - begin)
                    curve = pole ** steps
                    segment = mixed[:, begin:end]
                    total_curve = np.cumsum(segment * (curve ** -1)[None, :], axis=1)
                    lowpass = (1.0 - pole) * curve[None, :] * total_curve
                    lowpass = lowpass + (pole ** (steps + 1))[None, :] * damp_state[:, None]
                    damp_state = lowpass[:, -1].copy()
                    mixed[:, begin:end] = ((1.0 - damping_mix) * segment
                                           + damping_mix * lowpass)

            write_positions = (position + np.arange(span)[None, :]) % max_delay
            buffer[write_positions, line_columns[:, None]] = mixed * feedback[:, None]
            if collect_energy:
                energy_trace.append((float(np.sum(buffer ** 2)), block))
            position += span

        if not np.all(np.isfinite(wet)):
            wet = np.zeros(0, dtype=np.float64)
        if collect_energy:
            return wet, energy_trace
        return wet, []

    @staticmethod
    def damping_ratio(damping_hz):
        try:
            value = float(damping_hz)
        except (TypeError, ValueError):
            value = 4000.0
        position = (4000.0 - min(max(value, 500.0), 4000.0)) / (4000.0 - 500.0)
        return 1.0 + position * (CASSIETerminal.FDN_MIN_HF_RATIO - 1.0)

    @staticmethod
    def _solve_damping(target_ratio):
        pole = float(CASSIETerminal.FDN_DAMPING_POLE)
        if target_ratio >= 1.0:
            return 0.0, pole
        omega = 2.0 * math.pi * 4000.0 / 44100.0
        lowpass = (1.0 - pole) / abs(
            1.0 - pole * complex(math.cos(omega), -math.sin(omega)))
        denominator = 1.0 - lowpass
        if denominator <= 1e-6:
            return 0.0, pole
        mix = (1.0 - target_ratio) / denominator
        return min(1.0, max(0.0, mix)), pole

    def _generate_fdn_tail(self, frame_rate, channel, room_size, decay, damping, diffusion,
                           collect_energy=False):
        for key, value in (('reverb_room_size', room_size),
                           ('reverb_decay_time', decay),
                           ('reverb_damping', damping),
                           ('reverb_diffusion', diffusion)):
            setattr(self, key, value)
        params = self._prepare_fdn(frame_rate, channel)
        total = int(decay * frame_rate * 1.05) + params['max_delay']
        total = int(np.clip(total, frame_rate // 10, 90 * frame_rate))
        return self._run_fdn(np.zeros(0), params, inject_burst=True,
                             tail_samples=total, collect_energy=True)

    def apply_room_reverb(self, audio, wet=None):
        if len(audio) == 0 or audio.sample_width != 2:
            return audio
        wet_gain = float(np.clip(self.reverb_wet if wet is None else wet, 0.0, 1.0))
        if wet_gain <= 0:
            return audio
        try:
            frame_rate = int(audio.frame_rate)
            channels = int(audio.channels)
            samples = np.asarray(audio.get_array_of_samples(), dtype=np.float64)
            frames = samples.reshape((-1, channels)) if channels > 1 else samples.reshape((-1, 1))

            profile = self.spatial_profile()
            decay = float(np.clip(self.reverb_decay_time, 0.1, 30.0))
            pre_delay_ms = max(0.0, float(self.reverb_pre_delay))
            tail_samples = (int(decay * float(profile['tail_factor']) * frame_rate)
                            + int(pre_delay_ms * frame_rate / 1000.0))
            tail_samples = max(tail_samples, int(frame_rate * float(profile['min_tail_sec'])))
            fade_samples = 0
            if profile['tail_factor'] < CASSIE_TAIL_FADE_REFERENCE:
                fade_samples = min(int(frame_rate * 0.05), tail_samples // 3)

            mono_reverb = bool(profile.get('mono_reverb')) and channels > 1

            wet_parts = []
            if mono_reverb:
                mono_source = frames.mean(axis=1)
                params = self._fdn_parameters(frame_rate, 0)
                wet, _ = self._run_fdn(mono_source, params, tail_samples=tail_samples)
                wet_parts = [wet] * channels
            else:
                for index in range(channels):
                    params = self._fdn_parameters(frame_rate, index)
                    wet, _ = self._run_fdn(frames[:, index], params, tail_samples=tail_samples)
                    wet_parts.append(wet)
            if not wet_parts:
                return audio

            if fade_samples > 1:
                faded = []
                for part in wet_parts:
                    if part.size > fade_samples:
                        part = part.copy()
                        part[-fade_samples:] *= np.linspace(1.0, 0.0, fade_samples)
                    faded.append(part)
                wet_parts = faded

            wet_length = max(part.size for part in wet_parts)
            length = max(wet_length, frames.shape[0])
            wet_frames = np.zeros((length, channels), dtype=np.float64)
            for index, part in enumerate(wet_parts):
                wet_frames[:part.size, index] = part

            dry_frames = np.zeros((length, channels), dtype=np.float64)
            dry_frames[:frames.shape[0]] = frames

            dry_rms = float(np.sqrt(np.mean(frames ** 2)))
            wet_rms = float(np.sqrt(np.mean(wet_frames ** 2)))
            if wet_rms > 1e-9 and dry_rms > 1e-9:
                wet_frames = wet_frames * (dry_rms / wet_rms) * self.REVERB_SEND_GAIN

            mixed = dry_frames * (1.0 - 0.25 * wet_gain) + wet_frames * wet_gain
            mixed = self._soft_limit(mixed, 32767.0)

            pcm = np.clip(np.round(mixed), -32768, 32767).astype(np.int16)
            return AudioSegment(pcm.reshape(-1).tobytes(), frame_rate=frame_rate,
                                sample_width=2, channels=channels)
        except Exception:
            traceback.print_exc()
            return audio

    @staticmethod
    def _soft_limit(samples, ceiling):
        knee = ceiling * 0.78
        magnitude = np.abs(samples)
        if magnitude.size == 0 or float(np.max(magnitude)) <= knee:
            return samples
        span = ceiling - knee
        clipped = np.where(
            magnitude <= knee,
            magnitude,
            np.where(magnitude >= ceiling,
                     ceiling,
                     ceiling - span * ((ceiling - magnitude) / span) ** 3))
        return np.sign(samples) * clipped

    def apply_broadcast_effect(self, audio):
        if not self.broadcast_effect_enabled:
            return audio
        try:
            if self.low_cut_freq > 0:
                audio = audio.high_pass_filter(self.low_cut_freq)
            if self.high_cut_freq > 0:
                audio = audio.low_pass_filter(self.high_cut_freq)
            if self.mid_boost_gain != 0:
                audio = audio + self.mid_boost_gain
            if self.overdrive_gain > 0 and self.clip_threshold > 0:
                audio = audio + self.overdrive_gain
                samples = audio.get_array_of_samples()
                max_val = 32767
                clip_val = int(max_val * self.clip_threshold)
                for i in range(len(samples)):
                    if samples[i] > clip_val:
                        samples[i] = clip_val
                    elif samples[i] < -clip_val:
                        samples[i] = -clip_val
                audio = audio._spawn(samples)
            try:
                audio = audio.compress_dynamic(
                    threshold=self.compressor_threshold,
                    ratio=self.compressor_ratio,
                    attack=self.compressor_attack,
                    release=self.compressor_release
                )
            except Exception:
                pass
            treble_tail = self.generate_treble_tail(audio)
            if len(treble_tail) > 0:
                audio = audio.append(treble_tail, crossfade=min(8, len(treble_tail)))
            if self.noise_volume < 0:
                noise = self.generate_noise(
                    duration_ms=len(audio),
                    sample_rate=audio.frame_rate,
                    channels=audio.channels,
                    sample_width=audio.sample_width,
                    noise_type=getattr(self, 'noise_type', 'pink')
                )
                noise = noise.apply_gain(self.noise_volume)
                if audio.channels == 2 and noise.channels == 1:
                    noise = noise.set_channels(2)
                audio = audio.overlay(noise, position=0, gain_during_overlay=0)
        except Exception as e:
            traceback.print_exc()
            return audio
        return audio

    def _prepare_audio(self, audio, pitch=1.0, speed=0, apply_effects=True):
        if pitch != 1.0:
            new_frame_rate = int(audio.frame_rate * pitch)
            audio = audio._spawn(audio.raw_data, overrides={'frame_rate': new_frame_rate})
            audio = audio.set_frame_rate(audio.frame_rate)

        if speed < 0:
            threshold = -35.0
            start_trim = detect_leading_silence(audio, silence_threshold=threshold)
            end_trim = detect_leading_silence(audio.reverse(), silence_threshold=threshold)
            trim_strength = abs(speed) / 20.0
            start_cut = int(start_trim * trim_strength)
            end_cut = int(end_trim * trim_strength)
            if start_cut > 0 or end_cut > 0:
                audio = audio[start_cut:len(audio)-end_cut]

        if apply_effects and self.broadcast_effect_enabled:
            audio = self.apply_broadcast_effect(audio)

        return audio

    @staticmethod
    def load_audio(path, fmt='wav'):
        with open(path, 'rb') as handle:
            if fmt == 'wav':
                return AudioSegment.from_wav(handle)
            return AudioSegment.from_file(handle, fmt)

    @staticmethod
    def export_audio(audio, path, fmt='wav'):
        exported = audio.export(path, format=fmt)
        try:
            exported.close()
        except Exception:
            pass
        return path

    def _play_audio_segment(self, channel, audio, wait=True):
        if audio is None:
            return 0.0
        processed_duration = len(audio) / 1000.0
        if processed_duration <= 0:
            return 0.0

        temp_file = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
        export_path = temp_file.name
        temp_file.close()
        try:
            exported = audio.export(export_path, format="wav")
            try:
                exported.close()
            except Exception:
                pass
            with open(export_path, 'rb') as handle:
                payload = handle.read()
        finally:
            if os.path.exists(export_path):
                try:
                    os.unlink(export_path)
                except OSError:
                    pass

        sound = pygame.mixer.Sound(io.BytesIO(payload))
        pygame.mixer.Channel(channel).play(sound)
        if wait:
            time.sleep(processed_duration)
        return processed_duration

    def play_audio_on_channel(self, channel, filepath, start_delay=0, pitch=1.0, speed=0, wait=True):
        if start_delay > 0:
            time.sleep(start_delay)
        if not os.path.exists(filepath):
            return

        audio = self.load_audio(filepath)

        if pitch == 1.0 and speed == 0 and not self.broadcast_effect_enabled:
            sound = pygame.mixer.Sound(filepath)
            pygame.mixer.Channel(channel).play(sound)
            duration = self.get_audio_duration(filepath)
            if wait:
                time.sleep(duration)
            return duration

        return self._play_audio_segment(
            channel, self._prepare_audio(audio, pitch=pitch, speed=speed), wait=wait)

    def play_number_on_channel(self, channel, words, pitch=1.0, speed=0, wait=True):
        audio = AudioSegment.empty()
        for word in words:
            filepath = os.path.join(AUDIO_BASE_PATH, word + AUDIO_EXTENSION)
            if os.path.exists(filepath):
                audio += self.load_audio(filepath)
        if len(audio) == 0:
            return
        return self._play_audio_segment(
            channel, self._prepare_audio(audio, pitch=pitch, speed=speed), wait=wait)

    def play_stutter(self, filepath, stutter_count, pitch=1.0, speed=0, channel=None, full_play=True, wait=True):
        if channel is None:
            channel = self.word_channel

        if not os.path.exists(filepath):
            return

        audio = self.load_audio(filepath)

        if pitch != 1.0:
            new_frame_rate = int(audio.frame_rate * pitch)
            audio = audio._spawn(audio.raw_data, overrides={'frame_rate': new_frame_rate})
            audio = audio.set_frame_rate(audio.frame_rate)

        if speed < 0:
            threshold = -35.0
            start_trim = detect_leading_silence(audio, silence_threshold=threshold)
            end_trim = detect_leading_silence(audio.reverse(), silence_threshold=threshold)
            trim_strength = abs(speed) / 20.0
            start_cut = int(start_trim * trim_strength)
            end_cut = int(end_trim * trim_strength)
            if start_cut > 0 or end_cut > 0:
                audio = audio[start_cut:len(audio)-end_cut]

        temp_file = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
        export_path = temp_file.name
        temp_file.close()
        self.export_audio(audio, export_path)

        duration = self.get_audio_duration(export_path)
        stutter_duration = min(duration, self.stutter_duration)
        sound = pygame.mixer.Sound(export_path)

        total_duration = stutter_duration * stutter_count + (duration if full_play else 0)

        def play_sequence():
            for _ in range(stutter_count):
                pygame.mixer.Channel(channel).play(sound)
                time.sleep(stutter_duration)
                pygame.mixer.Channel(channel).stop()
            if full_play:
                pygame.mixer.Channel(channel).play(sound)
                time.sleep(duration)

        try:
            if wait:
                play_sequence()
            else:
                thread = threading.Thread(target=play_sequence, daemon=True)
                thread.start()
            return total_duration
        finally:
            if os.path.exists(export_path):
                os.unlink(export_path)

    SAMPLE_LABELS = {
        'the_vowel': 'the',
        'the_consonant': 'the',
    }

    NUMBER_WORDS = {
        0: 'zero', 1: 'one', 2: 'two', 3: 'three', 4: 'four', 5: 'five',
        6: 'six', 7: 'seven', 8: 'eight', 9: 'nine', 10: 'ten',
        11: 'eleven', 12: 'twelve', 13: 'thirteen', 14: 'fourteen',
        15: 'fifteen', 16: 'sixteen', 17: 'seventeen', 18: 'eighteen',
        19: 'nineteen', 20: 'twenty', 30: 'thirty', 40: 'forty',
        50: 'fifty', 60: 'sixty', 70: 'seventy', 80: 'eighty', 90: 'ninety',
    }

    @classmethod
    def render_sample_name(cls, name):
        text = str(name)
        if text in cls.SAMPLE_LABELS:
            return cls.SAMPLE_LABELS[text]
        if len(text) == 2 and text[0] == '_' and text[1].isalpha():
            return text[1]
        if text.isdigit():
            number = int(text)
            if number in cls.NUMBER_WORDS:
                return cls.NUMBER_WORDS[number]
        return text

    @classmethod
    def spoken_label(cls, item_type, word):
        return ' '.join(cls.spoken_parts(item_type, word))

    @classmethod
    def spoken_offsets(cls, event, pieces):
        count = len(pieces)
        if count == 0:
            return []
        if count == 1:
            return [0]

        spans = list(event.get('piece_durations_ms') or [])
        if len(spans) == count:
            total = float(sum(spans)) or 1.0
            slot_ms = max(1, int(event.get('end_ms', event['start_ms'])) - int(event['start_ms']))
            offsets = []
            elapsed = 0.0
            for span in spans:
                offsets.append(int(round(elapsed / total * slot_ms)))
                elapsed += span
            return offsets

        slot_ms = max(1, int(event.get('end_ms', event['start_ms'])) - int(event['start_ms']))
        return [int(slot_ms * index / count) for index in range(count)]

    @classmethod
    def spoken_parts(cls, item_type, word):
        if item_type == 'number':
            parts = word if isinstance(word, (list, tuple)) else [word]
            return [cls.render_sample_name(part) for part in parts]
        if isinstance(word, (list, tuple)):
            return [cls.render_sample_name(part) for part in word]
        return [cls.render_sample_name(word)]

    def process_number(self, num_str):
        num = float(num_str)
        parts = num_str.split('.')
        integer_part = int(parts[0])
        decimal_part = parts[1] if len(parts) > 1 else None
        result = []
        if integer_part == 0:
            result.append('0')
        elif integer_part > 0:
            if integer_part <= 20:
                result.append(str(integer_part))
            elif integer_part < 100:
                tens = (integer_part // 10) * 10
                units = integer_part % 10
                result.append(str(tens))
                if units > 0:
                    result.append(str(units))
            elif integer_part < 1000:
                hundreds = integer_part // 100
                remainder = integer_part % 100
                result.append(str(hundreds))
                result.append('hundred')
                if remainder > 0:
                    result.append('and')
                    if remainder <= 20:
                        result.append(str(remainder))
                    else:
                        tens = (remainder // 10) * 10
                        units = remainder % 10
                        result.append(str(tens))
                        if units > 0:
                            result.append(str(units))
            elif integer_part < 1000000:
                thousands = integer_part // 1000
                remainder = integer_part % 1000
                result.extend(self.process_number(str(thousands)))
                result.append('thousand')
                if remainder > 0:
                    if remainder < 100:
                        result.append('and')
                    result.extend(self.process_number(str(remainder)))
            elif integer_part < 100000000:
                millions = integer_part // 1000000
                remainder = integer_part % 1000000
                result.extend(self.process_number(str(millions)))
                result.append('million')
                if remainder > 0:
                    if remainder < 100:
                        result.append('and')
                    result.extend(self.process_number(str(remainder)))
            else:
                return None
        if decimal_part:
            result.append('point')
            for digit in decimal_part:
                result.append(digit)
        return result

    def play_bell_audio(self, filepath):
        if not os.path.exists(filepath):
            return 0
        with self.bell_lock:
            channel = pygame.mixer.Channel(self.bell_channel)
            channel.stop()
            sound = pygame.mixer.Sound(filepath)
            channel.play(sound)
        return self.get_audio_duration(filepath)

    def parse_broadcast_text(self, text, enable_number_reading=None):
        if not text or not text.strip():
            return {'queue': [], 'errors': [tr('content_empty')]}

        errors = []

        def replace_command(pattern, builder):
            nonlocal text
            while True:
                match = re.search(pattern, text)
                if not match:
                    return
                replacement = builder(match)
                if replacement is None:
                    text = text.replace(match.group(0), '')
                else:
                    text = text.replace(match.group(0), replacement, 1)


        def build_cd(match):
            parts = [part.strip() for part in match.group(1).split(',')]
            if len(parts) < 2:
                errors.append(tr('cd_missing_params'))
                return ''
            try:
                start = int(parts[0])
                end = int(parts[1])
            except ValueError:
                errors.append(tr('cd_start_end_not_int'))
                return ''
            if start == end:
                errors.append(tr('cd_start_end_equal'))
                return ''

            separator = parts[2] if len(parts) > 2 else ' [gap:0.6] '
            sep_with_spaces = ' {} '.format(separator.strip())
            step = -1 if start > end else 1
            numbers = range(start, end + step, step)
            return sep_with_spaces.join(str(number) for number in numbers)

        def build_mtf(match):
            parts = [part.strip() for part in match.groups()]
            if (not parts[0] or not parts[2] or
                    not all(part.isdigit() and int(part) > 0 for part in (parts[1], parts[3], parts[4]))):
                errors.append(tr('mtf_invalid_params'))
                return ''
            subject = 'scp+subject' if int(parts[4]) == 1 else 'scp+subjects'
            return ('mobile+task+force+unit {0} {1} designated {2} {3} '
                    'has+entered+the+facility . all+remaining+personnel . '
                    'awating+recontainment . {4} {5} . ').format(
                        parts[0], parts[1], parts[2], parts[3], parts[4], subject)

        def build_backup(match):
            word = match.group(1).strip()
            if not word:
                errors.append(tr('backup_missing_unit'))
                return ''
            return '{} backup unit has+entered+the+facility . '.format(word)

        def build_warhead(match):
            number = match.group(1).strip()
            mode = match.group(2).strip().lower()
            if mode not in ('start', 'resume', 'cancelled'):
                errors.append(tr('warhead_invalid_type'))
                return ''
            if mode != 'cancelled' and (not number.isdigit() or int(number) < 1):
                errors.append(tr('warhead_countdown_positive'))
                return ''
            return 'warhead+cancelled' if mode == 'cancelled' else 'warhead+{} {}s'.format(mode, number)

        def build_hostile(match):
            number, word1, word2, word3 = [part.strip() for part in match.groups()]
            if not number.isdigit() or int(number) < 1 or not word1 or not word2:
                errors.append(tr('hostile_invalid_params'))
                return ''
            return 'attention , all personnel . detected {} {} at {} . {} . '.format(
                number, word1, word2, word3 or 'lethal force authorized')

        replace_command(r'\[cd:([^\]]+)\]', build_cd)
        replace_command(r'\[mtf:([^,]+),([^,]+),([^,]+),([^,]+),([^,]+)\]', build_mtf)
        replace_command(r'\[backup:([^\]]+)\]', build_backup)
        replace_command(r'\[warhead:([^,]+),([^,]+)\]', build_warhead)
        replace_command(r'\[hostile_enter:([^,]+),([^,]+),([^,]+),([^,]+)\]', build_hostile)
        channl_blocks = {}
        block_marker = re.compile(
            r'\[(?:channl|channel):([^\]]+)\]'
            r'|\[(?:alert|alart):([^\],]+)\s*,\s*(start|stop)\]',
            re.IGNORECASE)
        output_parts = []
        source_position = 0
        while True:
            opening = block_marker.search(text, source_position)
            if opening is None:
                output_parts.append(text[source_position:])
                break

            alert_id = opening.group(2)
            alert_action = opening.group(3)
            if alert_id is not None:
                alert_id = alert_id.strip()
                if alert_action.lower() == 'stop':
                    output_parts.append(text[source_position:opening.start()])
                    source_position = opening.end()
                    continue
                depth = 1
                closing = None
                scan_position = opening.end()
                while depth:
                    marker = block_marker.search(text, scan_position)
                    if marker is None:
                        break
                    if (marker.group(2) is not None
                            and marker.group(2).strip().lower() == alert_id.lower()):
                        if marker.group(3).lower() == 'stop':
                            depth -= 1
                            if depth == 0:
                                closing = marker
                                break
                        else:
                            depth += 1
                    scan_position = marker.end()
                if closing is None:
                    errors.append(tr('alert_missing_stop').format(alert_id))
                    output_parts.append(text[source_position:opening.start()])
                    source_position = opening.end()
                    continue
                output_parts.append(text[source_position:opening.start()])
                inner = text[opening.end():closing.start()]
                nested_queue = []
                if inner.strip():
                    nested = self.parse_broadcast_text(
                        inner, enable_number_reading=enable_number_reading)
                    errors.extend(nested['errors'])
                    nested_queue = nested['queue']
                marker = '__cassie_alert_{}_{}__'.format(uuid.uuid4().hex, len(channl_blocks))
                channl_blocks[marker] = ('alert', alert_id, nested_queue)
                output_parts.append(' ' + marker + ' ')
                source_position = closing.end()
                continue

            offset_text = (opening.group(1) or '').strip()
            if offset_text.lower() == 'stop':
                output_parts.append(text[source_position:opening.start()])
                source_position = opening.end()
                continue
            if not re.fullmatch(r'[+-]?(?:\d+(?:\.\d{1,3})?|\.\d{1,3})', offset_text):
                errors.append(tr('channl_offset_invalid'))
                output_parts.append(text[source_position:opening.start()])
                source_position = opening.end()
                continue
            offset = float(offset_text)

            depth = 1
            closing = None
            scan_position = opening.end()
            while depth:
                marker = block_marker.search(text, scan_position)
                if marker is None:
                    break
                if marker.group(2) is None and marker.group(1).strip().lower() == 'stop':
                    depth -= 1
                    if depth == 0:
                        closing = marker
                        break
                elif marker.group(2) is None:
                    depth += 1
                scan_position = marker.end()
            if closing is None:
                errors.append(tr('channl_missing_stop'))
                output_parts.append(text[source_position:opening.start()])
                source_position = opening.end()
                continue

            output_parts.append(text[source_position:opening.start()])
            inner = text[opening.end():closing.start()]
            nested_queue = []
            if inner.strip():
                nested = self.parse_broadcast_text(
                    inner, enable_number_reading=enable_number_reading)
                errors.extend(nested['errors'])
                nested_queue = nested['queue']
            marker = '__cassie_channl_{}_{}__'.format(uuid.uuid4().hex, len(channl_blocks))
            channl_blocks[marker] = (offset, nested_queue)
            output_parts.append(' ' + marker + ' ')
            source_position = closing.end()
        text = ''.join(output_parts)

        error_count = 0
        error_match = re.search(r'\[error:(\d+)\]', text)
        if error_match:
            error_count = int(error_match.group(1))
            text = re.sub(r'\[error:\d+\]', '', text)

        segments = re.sub(r'\s+', ' ', text).strip().lower().split()
        queue = []
        previous_number_mode = self.enable_number_reading
        if enable_number_reading is not None:
            self.enable_number_reading = enable_number_reading
        for index, segment in enumerate(segments):
            if segment in channl_blocks:
                payload = channl_blocks[segment]
                if payload[0] == 'alert':
                    queue.append(('alert', payload[1], payload[2]))
                else:
                    queue.append(('channl', payload[0], payload[1]))
                continue
            parsed = self.parse_segment(segments, index)
            if parsed:
                queue.extend(parsed)
            else:
                errors.append(tr('not_found', item=segment))
        self.enable_number_reading = previous_number_mode

        if error_count > 0:
            word_indices = [index for index, item in enumerate(queue) if item[0] == 'word']
            available_glitches = [name for name in self.word_set if re.match(r'^g\d+$', name)]
            if word_indices and available_glitches:
                for position in sorted(random.sample(word_indices, min(error_count, len(word_indices))), reverse=True):
                    original = queue[position][1]
                    if random.choice([True, False]):
                        queue.insert(position, ('word', random.choice(available_glitches)))
                    else:
                        queue[position] = ('stutter', original, random.randint(1, 4))

        return {'queue': queue, 'errors': errors}

    def render_alarm_track(self, track):
        name = os.path.basename(str(track.get('audio') or '').strip())
        if not name:
            return None
        path = os.path.join(ALARM_AUDIO_DIR, name)
        if not os.path.exists(path):
            return None
        try:
            audio = self.load_audio(path)
        except Exception:
            return None

        total = len(audio)
        start = max(0, min(int(track.get('trim_start_ms') or 0), total))
        raw_end = track.get('trim_end_ms')
        end = total if raw_end in (None, '', 0) else max(start, min(int(raw_end), total))
        audio = audio[start:end]
        if len(audio) == 0:
            return None

        rate = float(track.get('speed') or 1.0)
        if rate <= 0:
            rate = 1.0
        if abs(rate - 1.0) > 1e-3:
            audio = audio._spawn(audio.raw_data,
                                 overrides={'frame_rate': int(audio.frame_rate * rate)})
            audio = audio.set_frame_rate(audio.frame_rate)

        gain = float(track.get('volume_db') or 0.0)
        if abs(gain) > 1e-3:
            audio = audio.apply_gain(gain)

        fade_in = max(0, int(track.get('fade_in_ms') or 0))
        fade_out = max(0, int(track.get('fade_out_ms') or 0))
        if fade_in:
            audio = audio.fade_in(min(fade_in, len(audio)))
        if fade_out:
            audio = audio.fade_out(min(fade_out, len(audio)))
        return audio

    @staticmethod
    def _pick_alarm_channel(events, start_ms):
        busy_until = 0
        used = set()
        for event in events:
            if not event.get('is_alarm'):
                continue
            used.add(event['channel'])
            busy_until = max(busy_until, event['end_ms'])
        for channel in ALARM_CHANNELS:
            if channel not in used:
                return channel
        for channel in ALARM_CHANNELS:
            if busy_until <= start_ms:
                return channel
        return None

    def render_alarm(self, events, alarm, start_ms, window_ms, channel):
        prepared = []
        for track in (alarm.get('tracks') or []):
            if not isinstance(track, dict):
                continue
            audio = self.render_alarm_track(track)
            if audio is None or len(audio) == 0:
                continue
            prepared.append((audio, max(0, int(track.get('start_ms') or 0)),
                             bool(track.get('loop'))))
        if not prepared:
            return 0

        loop_count = max(1, int(alarm.get('loop') or 1))
        natural = max(offset + len(audio) for audio, offset, _ in prepared)
        natural_run = natural * loop_count
        total = min(natural_run, window_ms) if window_ms > 0 else natural_run
        if total <= 0:
            return 0

        template = prepared[0][0]
        frame_rate = template.frame_rate
        channels = template.channels
        width = template.sample_width
        mixed = AudioSegment.silent(duration=total, frame_rate=frame_rate) \
            .set_channels(channels).set_sample_width(width)

        for audio, offset, track_loops in prepared:
            piece = audio.set_frame_rate(frame_rate).set_channels(channels) \
                .set_sample_width(width)
            if track_loops:
                cursor = offset
                while cursor < total:
                    chunk = piece[:total - cursor]
                    if len(chunk) == 0:
                        break
                    mixed = mixed.overlay(chunk, position=cursor)
                    cursor += len(piece)
                continue
            for repeat in range(loop_count):
                position = repeat * natural + offset
                if position >= total:
                    break
                chunk = piece[:total - position]
                if len(chunk) == 0:
                    continue
                mixed = mixed.overlay(chunk, position=position)

        events.append({
            'start_ms': start_ms,
            'end_ms': start_ms + len(mixed),
            'audio_length_ms': len(mixed),
            'channel': channel,
            'audio': mixed,
            'label': alarm.get('name') or alarm.get('id') or 'alarm',
            'spoken_words': [],
            'piece_durations_ms': [],
            'is_alarm': True,
        })
        return total

    @staticmethod
    def _clamp_alarms(events):
        speech_end = max((event['end_ms'] for event in events
                          if not event.get('is_alarm')), default=0)
        if speech_end <= 0:
            return
        kept = []
        for event in events:
            if not event.get('is_alarm'):
                kept.append(event)
                continue
            if event['start_ms'] >= speech_end:
                continue
            limit = speech_end - event['start_ms']
            if len(event['audio']) > limit:
                event['audio'] = event['audio'][:limit]
                event['audio_length_ms'] = len(event['audio'])
                event['end_ms'] = event['start_ms'] + len(event['audio'])
            if len(event['audio']) > 0:
                kept.append(event)
        events[:] = kept

    def interpret_broadcast_text(self, text, pitch=None, speed=None, enable_number_reading=None,
                                 include_bell=None, enable_special_bell=None):
        pitch = self.pitch if pitch is None else pitch
        speed = self.speed if speed is None else speed
        include_bell = self.enable_bell if include_bell is None else include_bell
        enable_special_bell = self.enable_special_bell if enable_special_bell is None else enable_special_bell
        parsed = self.parse_broadcast_text(text, enable_number_reading=enable_number_reading)
        errors = list(parsed['errors'])
        events = []
        channel_positions = {channel: 0 for channel in range(8)}
        word_count = 0

        def load_words(words):
            audio = AudioSegment.empty()
            for word in words if isinstance(words, (list, tuple)) else [words]:
                filepath = os.path.join(AUDIO_BASE_PATH, word + AUDIO_EXTENSION)
                if os.path.exists(filepath):
                    audio += self.load_audio(filepath)
            return audio if len(audio) else None

        def piece_durations_ms(words):
            spans = []
            for word in words if isinstance(words, (list, tuple)) else [words]:
                filepath = os.path.join(AUDIO_BASE_PATH, word + AUDIO_EXTENSION)
                if os.path.exists(filepath):
                    spans.append(len(self.load_audio(filepath)))
            return spans

        def compile_queue(queue, initial_channel, base_ms=0, active_channels=None):
            nonlocal word_count
            current_channel = initial_channel
            current_pitch = pitch
            active_channels = set() if active_channels is None else set(active_channels)

            for item in queue:
                item_type = item[0]
                if item_type == 'channel':
                    current_channel = initial_channel if item[1] == -1 else item[1]
                    continue
                if item_type == 'speed_all':
                    current_pitch = item[1]
                    continue
                if item_type == 'channl':
                    block_start = max(base_ms, channel_positions[current_channel])
                    block_start = max(0, block_start + round(item[1] * 1000))
                    unavailable = {
                        event['channel'] for event in events
                        if event['start_ms'] < block_start < event['end_ms']
                    }
                    candidates = [
                        channel for channel in range(8)
                        if channel != current_channel and channel not in active_channels
                        and channel not in unavailable
                        and channel_positions[channel] <= block_start
                    ]
                    if not candidates:
                        errors.append(tr('channl_no_free_channel'))
                        continue
                    block_channel = candidates[0]
                    compile_queue(item[2], block_channel, block_start,
                                  active_channels | {current_channel, block_channel})
                    continue
                if item_type == 'alert':
                    alarm = load_alarm(item[1])
                    if alarm is None:
                        errors.append(tr('alert_not_found').format(item[1]))
                        continue
                    alert_start = max(base_ms, channel_positions[current_channel])
                    compile_queue(item[2], current_channel, alert_start,
                                  active_channels | {current_channel})
                    alert_end = max(channel_positions[current_channel], alert_start)
                    alarm_channel = self._pick_alarm_channel(events, alert_start)
                    if alarm_channel is None:
                        errors.append(tr('alert_no_free_channel'))
                        continue
                    self.render_alarm(events, alarm, alert_start,
                                      alert_end - alert_start, alarm_channel)
                    continue
                if item_type in ('pause', 'gap'):
                    channel_positions[current_channel] = max(
                        base_ms, channel_positions[current_channel]) + round(item[1] * 1000)
                    continue
                if item_type not in ('word', 'number', 'stutter'):
                    continue

                word_count += 1
                position = max(base_ms, channel_positions[current_channel])
                if speed > 0 and word_count > 1:
                    position += round(speed * 50)

                word = item[1]
                word_pitch = current_pitch
                if item_type == 'word' and len(item) > 2:
                    word_pitch = item[2]
                elif item_type == 'stutter' and len(item) > 3 and item[3] is not None:
                    word_pitch = item[3]
                audio = load_words(word)
                if audio is None:
                    continue

                audio = self._prepare_audio(audio, pitch=word_pitch, speed=speed,
                                            apply_effects=False)
                if item_type == 'stutter':
                    full_audio = audio
                    short_audio = audio[:int(min(len(audio), self.stutter_duration * 1000))]
                    audio = short_audio * item[2]
                    if len(item) < 5 or item[4]:
                        audio += full_audio

                scheduled_length = len(audio)
                if not self.uses_sentence_processing():
                    audio = self.apply_broadcast_effect(audio)
                    if len(audio) == 0:
                        audio = full_audio if item_type == 'stutter' else load_words(word)

                event = {
                    'start_ms': position,
                    'end_ms': position + scheduled_length,
                    'audio_length_ms': len(audio),
                    'channel': current_channel,
                    'audio': audio,
                    'label': self.spoken_label(item_type, word),
                    'spoken_words': self.spoken_parts(item_type, word),
                    'piece_durations_ms': piece_durations_ms(word),
                }
                events.append(event)
                channel_positions[current_channel] = event['end_ms']

        compile_queue(parsed['queue'], self.word_channel)
        self._clamp_alarms(events)
        content_end = max((event['end_ms'] for event in events), default=0)
        if include_bell and events:
            lead_ms = max(0, round(self.bell_lead_time * 1000))
            for event in events:
                event['start_ms'] += lead_ms
                event['end_ms'] += lead_ms
            content_end += lead_ms
            if enable_special_bell:
                start_file = self.get_special_bell_path(self.special_bell_start, 'bell_start.wav')
                end_file = self.get_special_bell_path(self.special_bell_end, 'bell_end.wav')
                if os.path.exists(start_file):
                    audio = self.load_audio(start_file)
                    events.append({'start_ms': 0, 'end_ms': len(audio), 'channel': self.bell_channel,
                                   'audio': audio, 'label': self.special_bell_start})
                else:
                    errors.append(tr('bell_missing', item=self.special_bell_start))
                if self.bell_extra_duration > 0:
                    content_end += round(self.bell_extra_duration * 1000)
                if os.path.exists(end_file):
                    audio = self.load_audio(end_file)
                    events.append({'start_ms': content_end, 'end_ms': content_end + len(audio),
                                   'channel': self.bell_channel, 'audio': audio,
                                   'label': self.special_bell_end})
                else:
                    errors.append(tr('bell_missing', item=self.special_bell_end))
            else:
                seconds = max(4, int(content_end / 1000) + 2 + int(self.bell_extra_duration))
                bell_file = os.path.join(SOUND_BASE_PATH, 'bg_{}.wav'.format(seconds))
                if os.path.exists(bell_file):
                    audio = self.load_audio(bell_file)
                    events.append({'start_ms': 0, 'end_ms': len(audio), 'channel': self.bell_channel,
                                   'audio': audio, 'label': 'bg_{}'.format(seconds)})
                else:
                    errors.append(tr('bell_missing', item='bg_{}.wav'.format(seconds)))

        events.sort(key=lambda event: event['start_ms'])
        content_ms = max((event['end_ms'] for event in events), default=0)
        _PENDING_TIMELINE.value = None
        events = self.apply_reverb_to_events(events)
        pending = _PENDING_TIMELINE.value
        if pending is not None:
            content_ms = pending['content_ms']
            duration_ms = pending['duration_ms']
        else:
            duration_ms = max((event['start_ms']
                               + event.get('audio_length_ms', len(event['audio']))
                               for event in events), default=0)
        return {'events': events, 'errors': errors, 'word_count': word_count,
                'content_ms': int(content_ms), 'duration_ms': int(max(content_ms, duration_ms))}

    def uses_sentence_processing(self):
        return getattr(self, 'spatial_mode', 'word') == 'sentence'

    def spatial_active(self):
        return bool(self.broadcast_effect_enabled
                    and self.reverb_enabled
                    and self.reverb_wet > 0)

    PROGRESS_STAGES = ('parse', 'reverb', 'export', 'play')

    PROGRESS_SPANS = {
        'parse': (0, 8),
        'reverb': (8, 72),
        'export': (72, 80),
        'play': (80, 100),
    }

    def _progress_state(self):
        state = getattr(_PENDING_PROGRESS, 'state', None)
        if state is None:
            state = {'callback': None, 'total': 0, 'done': 0, 'stage': 'parse',
                     'percent': 0}
            _PENDING_PROGRESS.state = state
        return state

    def begin_progress(self, total_units, callback):
        state = self._progress_state()
        state['callback'] = callback
        state['total'] = max(0, int(total_units))
        state['done'] = 0
        state['stage'] = 'parse'
        state['percent'] = 0

    def set_progress_stage(self, stage, total_units=None):
        state = self._progress_state()
        state['stage'] = stage
        if total_units is not None:
            state['total'] = max(0, int(total_units))
            state['done'] = 0
        self._emit_progress()

    def _tick_progress(self):
        state = self._progress_state()
        state['done'] += 1
        self._emit_progress()

    def _set_progress_position(self, done, total):
        state = self._progress_state()
        state['done'] = int(done)
        state['total'] = max(1, int(total))
        self._emit_progress()

    def estimate_preprocess_event(self, text):
        span = self.PROGRESS_SPANS['reverb']
        if not self.spatial_active():
            return {'type': 'progress', 'stage': 'reverb', 'done': 0, 'total': 0,
                    'percent': span[0], 'estimate_ms': 0, 'estimated': True}
        words = len([part for part in str(text or '').split() if part])
        level = max(0, int(getattr(self, 'spatial_quality', 0)))
        per_word_ms = (85, 54, 35, 23, 17, 15, 11)
        unit = per_word_ms[min(level, len(per_word_ms) - 1)]
        return {'type': 'progress', 'stage': 'reverb', 'done': 0, 'total': words,
                'percent': span[0], 'estimate_ms': int(max(120, words * unit)),
                'estimated': True}

    def progress_percent(self, stage, done, total):
        start, end = self.PROGRESS_SPANS.get(stage, (0, 100))
        if total > 0:
            ratio = min(1.0, max(0.0, float(done) / float(total)))
        else:
            ratio = 0.0
        percent = int(round(start + (end - start) * ratio))
        previous = self._progress_state().get('percent', 0)
        return max(previous, percent, 0)

    def _emit_progress(self, force_percent=None):
        state = self._progress_state()
        callback = state['callback']
        if callback is None:
            return
        total = state['total']
        done = min(state['done'], total) if total else 0
        if force_percent is None:
            percent = self.progress_percent(state['stage'], done, total)
        else:
            percent = max(state.get('percent', 0), force_percent)
        state['percent'] = percent
        try:
            callback(state['stage'], done, total, percent)
        except Exception:
            traceback.print_exc()

    def end_progress(self):
        state = self._progress_state()
        state['callback'] = None
        state['total'] = 0
        state['done'] = 0
        state['stage'] = 'parse'
        state['percent'] = 0

    def _append_tail_marker(self, events, content_end, tail_end):
        if tail_end <= content_end:
            return events
        events.append({
            'start_ms': content_end,
            'end_ms': tail_end,
            'channel': self.bell_channel,
            'audio': AudioSegment.empty(),
            'label': '__tail__',
            'silent': True,
        })
        return events

    @staticmethod
    def timeline_bounds(events):
        real = [event for event in events if not event.get('silent')]
        content_end = max((event['end_ms'] for event in real), default=0)
        tail_end = max((event['start_ms'] + event.get('audio_length_ms', len(event['audio']))
                        for event in real), default=0)
        return content_end, max(content_end, tail_end)

    def apply_reverb_to_events(self, events):
        if not self.spatial_active() or not events:
            return events

        if self.uses_sentence_processing():
            return self._apply_sentence_processing(events)

        speakable = [event for event in events
                     if event['channel'] != self.bell_channel and len(event['audio']) > 0]
        if speakable:
            self.set_progress_stage('reverb', len(speakable))

        for event in events:
            if event['channel'] == self.bell_channel:
                continue
            processed = self.apply_room_reverb(event['audio'])
            if len(processed) > 0:
                event['audio'] = processed
                event['audio_length_ms'] = len(processed)
            self._tick_progress()

        content_end, tail_end = self.timeline_bounds(events)
        return self._append_tail_marker(events, content_end, tail_end)

    def _mix_channel(self, events, channel, frame_rate, total_ms):
        track = AudioSegment.silent(duration=total_ms, frame_rate=frame_rate).set_sample_width(2)
        for event in events:
            if event['channel'] != channel or len(event['audio']) == 0:
                continue
            audio = event['audio'].set_frame_rate(frame_rate)
            track = track.overlay(audio, position=int(event['start_ms']))
        return track

    def _apply_sentence_processing(self, events):
        frame_rate = int(self._audio_frame_rate(events))
        content_end = max((event['end_ms'] for event in events), default=0)
        if content_end <= 0:
            return events

        speech_channels = sorted({event['channel'] for event in events
                                  if event['channel'] != self.bell_channel})
        bell_events = [event for event in events if event['channel'] == self.bell_channel]

        content_end, _ = self.timeline_bounds(events)

        processed = []
        tail_end = content_end
        for channel in speech_channels:
            track = self._mix_channel(events, channel, frame_rate, content_end)
            if len(track) == 0:
                continue
            track = self.apply_broadcast_effect(track)
            track = self.apply_room_reverb(track)
            if len(track) == 0:
                continue
            processed.append({
                'start_ms': 0,
                'end_ms': len(track),
                'audio_length_ms': len(track),
                'channel': channel,
                'audio': track,
                'words': [piece
                          for event in events
                          if event['channel'] == channel
                          and not event.get('silent')
                          for piece in (event.get('spoken_words')
                                        or [event.get('label', '')])
                          if str(piece).strip()],
                'label': tr('sentence_label'),
            })
            tail_end = max(tail_end, len(track))

        if not processed:
            return events

        result = processed + bell_events
        result.sort(key=lambda event: event['start_ms'])
        _PENDING_TIMELINE.value = {
            'content_ms': int(content_end),
            'duration_ms': int(max(content_end, tail_end)),
        }
        return result

    @staticmethod
    def _audio_frame_rate(events):
        for event in events:
            if len(event['audio']) > 0:
                return event['audio'].frame_rate
        return 44100

    def parse_segment(self, segments, current_index):
        if not segments or current_index >= len(segments):
            return []
        segment = segments[current_index]
        if not segment:
            return []

        if segment.startswith('[speed_all:'):
            try:
                speed_all_value = float(segment[11:-1])
                if 0.1 <= speed_all_value <= 10.0:
                    return [('speed_all', speed_all_value)]
            except:
                pass
            return []

        if segment.startswith('[gap:'):
            try:
                gap_value = float(segment[5:-1])
                if gap_value >= 0:
                    return [('gap', gap_value)]
            except:
                pass
            return []

        if segment.startswith('[error:'):
            try:
                error_count = int(segment[7:-1])
                return [('error', error_count)]
            except:
                pass
            return []

        stutter_match = re.match(r'^\[stutter:(\d+)(?:,(\w+))?\](.+)$', segment)
        if stutter_match:
            stutter_count = int(stutter_match.group(1))
            full_play_str = stutter_match.group(2)
            full_play = True if full_play_str is None else full_play_str.lower() == 'true'
            actual_word = stutter_match.group(3)
            temp_segments = segments[:current_index] + [actual_word] + segments[current_index+1:]
            word_queue = self.parse_segment(temp_segments, current_index)
            if word_queue:
                if len(word_queue[0]) > 2:
                    pitch = word_queue[0][2]
                else:
                    pitch = None
                return [('stutter', word_queue[0][1], stutter_count, pitch, full_play)]
            return []

        speed_match = re.match(r'^\[speed:(\d+\.?\d*)\](.+)$', segment)
        if speed_match:
            speed_value = float(speed_match.group(1))
            actual_word = speed_match.group(2)
            if 0.1 <= speed_value <= 10.0:
                temp_segments = segments[:current_index] + [actual_word] + segments[current_index+1:]
                word_queue = self.parse_segment(temp_segments, current_index)
                if word_queue:
                    return [('word', word_queue[0][1], speed_value)]
            return []

        if segment == '.':
            return [('pause', 0.4)]
        if segment == ',':
            return [('pause', 0.2)]
        if segment == '、':
            return [('pause', 0.15)]

        if segment == 'mtf':
            return [('word', 'mobile'), ('word', 'task'), ('word', 'force')]

        if '+' in segment:
            unified = segment.replace('+', ' ')
            filepath = os.path.join(AUDIO_BASE_PATH, unified + AUDIO_EXTENSION)
            if os.path.exists(filepath):
                return [('word', unified)]

        if self.enable_number_reading and segment.replace('.', '', 1).isdigit():
            num_parts = self.process_number(segment)
            if num_parts:
                return [('number', num_parts)]

        if not self.enable_number_reading:
            if segment.isdigit():
                return [('word', d) for d in segment]

        word = segment.lower()

        if word == 'the':
            if current_index + 1 < len(segments):
                next_word = segments[current_index + 1]
                if next_word and next_word[0] in 'aeiou':
                    return [('word', 'the_vowel')]
            return [('word', 'the_consonant')]

        if word in nato_map:
            word = nato_map[word]
        elif len(word) == 1 and word.isalpha():
            word = '_' + word

        if word.endswith('ed'):
            base = word[:-2]
            base_path = os.path.join(AUDIO_BASE_PATH, base + AUDIO_EXTENSION)
            ed_path = os.path.join(AUDIO_BASE_PATH, 'ed' + AUDIO_EXTENSION)
            if os.path.exists(base_path) and os.path.exists(ed_path):
                return [('word', base), ('word', 'ed')]

        filepath = os.path.join(AUDIO_BASE_PATH, word + AUDIO_EXTENSION)
        if os.path.exists(filepath):
            return [('word', word)]

        return []

    def _word_known(self, word):
        if '+' in word:
            word = word.replace('+', ' ')
        if word.isdigit():
            return True
        if word in ('.', ',', '、'):
            return True
        if word in BARE_COMMAND_WORDS:
            return True
        if word in self.word_set:
            return True
        if word in nato_map:
            return True
        if word in ('the', 'the_vowel', 'the_consonant'):
            return True
        if word.endswith('ed') and word[:-2] in self.word_set and 'ed' in self.word_set:
            return True
        if len(word) == 1 and word.isalpha():
            if '_' + word in self.word_set:
                return True
        if word.startswith('g') and len(word) == 2 and word[1].isdigit():
            if word in self.word_set:
                return True
        return False

    def classify_token(self, segment):
        stripped = BRACKET_COMMAND_RE.sub('', segment.lower()).strip()
        if not stripped:
            return 'command'
        if stripped in BARE_COMMAND_WORDS:
            return 'command'
        if stripped in ('.', ',', '、'):
            return 'neutral'
        return 'word' if self._word_known(stripped) else 'missing'

    def check_spelling_detail(self, text):
        return [{'text': seg, 'kind': self.classify_token(seg)}
                for seg in text.strip().split()]

    def check_spelling(self, text):
        return [token['text'] for token in self.check_spelling_detail(text)
                if token['kind'] == 'missing']

    def _legacy_play_broadcast_stream(self, text):
        if self.is_playing:
            yield {"text": tr('play_busy'), "type": "error"}
            return
        if not text:
            yield {"text": tr('content_empty'), "type": "error"}
            return

        error_value = None

        while True:
            cmd_match = re.search(r'\[cd:([^\]]+)\]', text)
            if not cmd_match:
                break
            parts = cmd_match.group(1).split(',')
            if len(parts) < 2:
                yield {"text": "Error: CD command missing parameters, expected format: [cd:start,end,separator]", "type": "error"}
                text = text.replace(cmd_match.group(0), '')
                continue
            start_str = parts[0].strip()
            end_str = parts[1].strip()
            sep = parts[2] if len(parts) > 2 else ' . '
            try:
                start = int(start_str)
                end = int(end_str)
            except ValueError:
                yield {"text": "Error: CD command invalid number format", "type": "error"}
                text = text.replace(cmd_match.group(0), '')
                continue
            if start == end:
                yield {"text": "Error: CD command start value equals end value", "type": "error"}
                text = text.replace(cmd_match.group(0), '')
                continue
            if start > end:
                nums = list(range(start, end - 1, -1))
            else:
                nums = list(range(start, end + 1))
            result = str(nums[0])
            for n in nums[1:]:
                result += sep + str(n)
            text = text.replace(cmd_match.group(0), result)

        while True:
            cmd_match = re.search(r'\[mtf:([^,]+),([^,]+),([^,]+),([^,]+),([^,]+)\]', text)
            if cmd_match:
                parts = [p.strip() for p in cmd_match.groups()]
                if len(parts) < 5:
                    yield {"text": "Error: MTF command missing parameters: [mtf:word1,number1,word2,number2,scp_count]", "type": "error"}
                    text = text.replace(cmd_match.group(0), '')
                else:
                    word1 = parts[0]
                    number1_str = parts[1]
                    word2 = parts[2]
                    number2_str = parts[3]
                    scp_count_str = parts[4]
                    if not word1 or not word2:
                        yield {"text": "Error: MTF command word cannot be empty", "type": "error"}
                        text = text.replace(cmd_match.group(0), '')
                    elif not number1_str.isdigit() or not number2_str.isdigit() or not scp_count_str.isdigit():
                        yield {"text": "Error: MTF command number must be a positive integer", "type": "error"}
                        text = text.replace(cmd_match.group(0), '')
                    else:
                        number1 = int(number1_str)
                        number2 = int(number2_str)
                        scp_count = int(scp_count_str)
                        if number1 < 1 or number2 < 1 or scp_count < 1:
                            yield {"text": "Error: MTF command number must be a positive integer", "type": "error"}
                            text = text.replace(cmd_match.group(0), '')
                        else:
                            subject = 'scp+subject' if scp_count == 1 else 'scp+subjects'
                            result = f"mobile+task+force+unit {word1} {number1} designated {word2} {number2} has+entered+the+facility . all+remaining+personnel . awating+recontainment . {scp_count} {subject} . "
                            text = text.replace(cmd_match.group(0), result)
            else:
                break

        while True:
            cmd_match = re.search(r'\[backup:([^,]+)\]', text)
            if cmd_match:
                parts = [p.strip() for p in cmd_match.groups()]
                if len(parts) < 1:
                    yield {"text": "Error: BackUp command missing parameters: [backup:word]", "type": "error"}
                    text = text.replace(cmd_match.group(0), '')
                else:
                    backup_word = parts[0]
                    result = f"{backup_word} backup unit has+entered+the+facility . "
                    text = text.replace(cmd_match.group(0), result)
            else:
                break

        while True:
            cmd_match = re.search(r'\[warhead:([^,]+),([^,]+)\]', text)
            if cmd_match:
                parts = [p.strip() for p in cmd_match.groups()]
                if len(parts) < 2:
                    yield {"text": "Error: Warhead command missing parameters: [Warhead:number,type(start/cancel/erstart)]", "type": "error"}
                    text = text.replace(cmd_match.group(0), '')
                else:
                    warhead_number = parts[0]
                    warhead_type = parts[1]
                    if warhead_type == "cancelled":
                        result = f"warhead+cancelled"
                    elif warhead_type =="resume":
                        result = f"warhead+{warhead_type} [channl:-1] {warhead_number}s [channel:stop]"
                    elif warhead_type =="start":
                        result = f"warhead+{warhead_type} [channl:-1] {warhead_number}s [channel:stop]"
                    else:
                        yield {"text": "Error: Warhead command missing parameters: [Warhead:number,type(start/cancel/erstart)]", "type": "error"}
                        result = f"[speed:0.85]error"
                    text = text.replace(cmd_match.group(0), result)
            else:
                break

        while True:
            cmd_match = re.search(r'\[hostile_enter:([^,]+),([^,]+),([^,]+),([^,]+)\]', text)
            if cmd_match:
                parts = [p.strip() for p in cmd_match.groups()]
                if len(parts) < 4:
                    yield {"text": "Error: HostileEnter command missing parameters: [hostile_enter:number1,word1,word2,word3]", "type": "error"}
                    text = text.replace(cmd_match.group(0), '')
                else:
                    number1_str = parts[0]
                    word1 = parts[1]
                    word2 = parts[2]
                    word3 = parts[3]
                    if not word3:
                        word3 = "lethal force authorized"
                    if not word1 or not word2:
                        yield {"text": "Error: HostileEnter command word cannot be empty", "type": "error"}
                        text = text.replace(cmd_match.group(0), '')
                    elif not number1_str.isdigit():
                        yield {"text": "Error: HostileEnter command number must be a positive integer", "type": "error"}
                        text = text.replace(cmd_match.group(0), '')
                    else:
                        number1 = int(number1_str)
                        if number1 < 1:
                            yield {"text": "Error: HostileEnter command number must be a positive integer", "type": "error"}
                            text = text.replace(cmd_match.group(0), '')
                        else:
                            result = f"attention , all personnel . detected {number1} {word1} at {word2} . {word3} . "
                            text = text.replace(cmd_match.group(0), result)
            else:
                break

        error_match = re.search(r'\[error:(\d+)\]', text)
        if error_match:
            error_value = int(error_match.group(1))
            text = re.sub(r'\[error:\d+\]', '', text)

        text = re.sub(r'\s+', ' ', text).strip()
        segments = text.lower().split()

        self.is_playing = True

        try:
            full_queue = []

            i = 0
            while i < len(segments):
                parsed = self.parse_segment(segments, i)
                if parsed:
                    full_queue.extend(parsed)
                    i += 1
                else:
                    yield {"text": tr('not_found', item=segments[i]), "type": "error"}
                    i += 1

            if error_value and error_value > 0:
                word_indices = [i for i, item in enumerate(full_queue) if item[0] == 'word']
                if word_indices:
                    select_count = min(error_value, len(word_indices))
                    chosen = random.sample(word_indices, select_count)
                    for pos in sorted(chosen, reverse=True):
                        orig = full_queue[pos][1]
                        if random.choice([0, 1]) == 0:
                            full_queue.insert(pos, ('word', f'g{random.randint(1,9)}'))
                        else:
                            full_queue[pos] = ('stutter', orig, random.randint(1,4))

            if self.enable_bell:
                if self.enable_special_bell:
                    start_file = os.path.join(SOUND_BASE_PATH, "bell_start.wav")
                    if os.path.exists(start_file):
                        self.play_bell_audio(start_file)
                        if self.verbose_mode:
                            yield {"text": tr('bell_playing', item='bell_start'), "type": "info"}
                    else:
                        yield {"text": tr('bell_missing', item='bell_start.wav'), "type": "error"}
                else:
                    total_duration = 0
                    for item in full_queue:
                        if item[0] == 'pause':
                            total_duration += item[1]
                        elif item[0] == 'stutter':
                            filepath = os.path.join(AUDIO_BASE_PATH, item[1] + AUDIO_EXTENSION)
                            total_duration += self.get_audio_duration(filepath) * (item[2] + 1)
                        elif item[0] == 'word':
                            filepath = os.path.join(AUDIO_BASE_PATH, item[1] + AUDIO_EXTENSION)
                            total_duration += self.get_audio_duration(filepath)
                        elif item[0] == 'number':
                            total_duration += sum(
                                self.get_audio_duration(os.path.join(AUDIO_BASE_PATH, word + AUDIO_EXTENSION))
                                for word in item[1]
                            )
                    need_seconds = int(total_duration) + 2 + int(self.bell_extra_duration)
                    if need_seconds < 4:
                        need_seconds = 4
                    bell_file = os.path.join(SOUND_BASE_PATH, "bg_" + str(need_seconds) + ".wav")
                    if os.path.exists(bell_file):
                        self.play_bell_audio(bell_file)
                        if self.verbose_mode:
                            yield {"text": tr('bell_playing', item='bg_' + str(need_seconds)), "type": "info"}
                    else:
                        yield {"text": tr('bell_missing', item='bg_' + str(need_seconds) + '.wav'), "type": "error"}
                time.sleep(self.bell_lead_time)

            current_speed_all = self.pitch
            current_channel = self.word_channel
            total_words = len([item for item in full_queue if item[0] in ('word', 'number', 'stutter')])
            word_index = 0

            for item in full_queue:
                if self.stop_requested:
                    break
                if item[0] == 'channel':
                    if item[1] == -1:
                        current_channel = self.word_channel
                    else:
                        current_channel = item[1]
                    continue
                if item[0] == 'speed_all':
                    current_speed_all = item[1]
                    continue
                if item[0] == 'pause':
                    if self.verbose_mode:
                        yield {"text": tr('verbose_pause', seconds=item[1]), "type": "info"}
                    time.sleep(item[1])
                elif item[0] == 'gap':
                    time.sleep(item[1])
                elif item[0] == 'stutter':
                    word_index += 1
                    filepath = os.path.join(AUDIO_BASE_PATH, item[1] + AUDIO_EXTENSION)
                    stutter_count = item[2]
                    pitch = item[3] if len(item) > 3 and item[3] is not None else current_speed_all
                    full_play = item[4] if len(item) > 4 else True
                    if self.verbose_mode:
                        suffix = tr('verbose_stutter_full') if full_play else tr('verbose_stutter_only')
                        yield {"text": tr('verbose_stutter', index=word_index,
                                          total=total_words, word=item[1],
                                          count=stutter_count, pitch=pitch,
                                          suffix=suffix), "type": "info"}
                    self.play_stutter(filepath, stutter_count, pitch, speed=self.speed, channel=current_channel, full_play=full_play)
                elif item[0] == 'word':
                    word_index += 1
                    filepath = os.path.join(AUDIO_BASE_PATH, item[1] + AUDIO_EXTENSION)
                    pitch = item[2] if len(item) > 2 else current_speed_all
                    if self.verbose_mode:
                        yield {"text": tr('verbose_word', index=word_index,
                                          total=total_words, word=item[1],
                                          pitch=pitch), "type": "info"}
                    self.play_audio_on_channel(current_channel, filepath, pitch=pitch, speed=self.speed)
                elif item[0] == 'number':
                    word_index += 1
                    pitch = current_speed_all
                    if self.verbose_mode:
                        yield {"text": tr('verbose_number', index=word_index,
                                          total=total_words,
                                          word=' '.join(item[1])), "type": "info"}
                    self.play_number_on_channel(current_channel, item[1], pitch=pitch, speed=self.speed)

            if self.enable_bell and self.enable_special_bell:
                end_file = os.path.join(SOUND_BASE_PATH, "bell_end.wav")
                if os.path.exists(end_file):
                    self.play_bell_audio(end_file)
                    if self.verbose_mode:
                        yield {"text": tr('bell_playing', item='bell_end'), "type": "info"}
                    time.sleep(self.get_audio_duration(end_file))

            if self.verbose_mode:
                yield {"text": tr('play_done'), "type": "info"}

        finally:
            self.is_playing = False
            self.stop_requested = False

    def play_broadcast_stream(self, text, lock_acquired=False):
        owns_lock = lock_acquired
        if not owns_lock and not self.play_lock.acquire(False):
            yield {"text": tr('play_busy'), "type": "error"}
            return
        owns_lock = True

        try:
            plan = self.interpret_broadcast_text(text)
            for error in plan['errors']:
                yield {"text": error, "type": "error"}
            events = plan['events']
            if not events:
                return

            self.is_playing = True
            playable = [event for event in events if len(event['audio']) > 0]

            def log_pieces(event):
                if event.get('words'):
                    pieces = event['words']
                elif event.get('spoken_words'):
                    pieces = event['spoken_words']
                else:
                    pieces = [event.get('label', '')]
                return [str(piece) for piece in pieces if str(piece).strip()]

            schedule = []
            if self.verbose_mode:
                timeline = []
                for event in playable:
                    if event['channel'] == self.bell_channel:
                        continue
                    pieces = log_pieces(event)
                    if not pieces:
                        continue
                    start_ms = int(event['start_ms'])
                    offsets = self.spoken_offsets(event, pieces)
                    for position, piece in enumerate(pieces):
                        timeline.append((start_ms + offsets[position], piece))

                total_words = len(timeline)
                schedule = [
                    (at_ms, '[{}/{}] {}'.format(index, total_words, piece))
                    for index, (at_ms, piece) in enumerate(timeline, 1)
                ]

            playback_start = time.monotonic()
            channel_ready = {}
            cursor = 0

            def due_logs(before_ms):
                nonlocal cursor
                while cursor < len(schedule) and schedule[cursor][0] <= before_ms:
                    at_ms, text = schedule[cursor]
                    wait = playback_start + at_ms / 1000.0 - time.monotonic()
                    if wait > 0:
                        time.sleep(wait)
                    cursor += 1
                    yield {"text": text, "type": "info"}

            total_play_ms = 0
            for event in playable:
                total_play_ms = max(total_play_ms,
                                    int(event['start_ms'])
                                    + int(event.get('audio_length_ms', len(event['audio']))))
            self.set_progress_stage('play')
            span = self.PROGRESS_SPANS['play']
            yield {"type": "progress", "stage": 'play', "done": 0,
                   "total": max(1, total_play_ms // 1000),
                   "percent": span[0],
                   "duration_ms": total_play_ms,
                   "started_at": int(playback_start * 1000),
                   "is_playback": True}

            for event in playable:
                if event['channel'] != self.bell_channel:
                    continue
                if self.stop_requested:
                    break
                delay = playback_start + event['start_ms'] / 1000.0 - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
                duration = self._play_audio_segment(event['channel'], event['audio'], wait=False)
                channel_ready[event['channel']] = max(
                    channel_ready.get(event['channel'], 0), time.monotonic() + duration)

            for event in playable:
                if self.stop_requested:
                    break
                if event['channel'] == self.bell_channel:
                    for entry in due_logs(int(event['start_ms'])):
                        yield entry
                    continue
                event_start_ms = int(event['start_ms'])
                for entry in due_logs(event_start_ms):
                    yield entry

                delay = playback_start + event['start_ms'] / 1000.0 - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
                duration = self._play_audio_segment(event['channel'], event['audio'], wait=False)
                channel_ready[event['channel']] = time.monotonic() + duration
                played_ms = int(event_start_ms + duration)
                self._set_progress_position(played_ms, max(1, total_play_ms))
                self._emit_progress()
                yield {"type": "progress", "stage": 'play',
                       "done": played_ms // 1000,
                       "total": max(1, total_play_ms // 1000),
                       "percent": self.progress_percent(
                           'play', played_ms, max(1, total_play_ms)),
                       "duration_ms": total_play_ms,
                       "elapsed_ms": played_ms}

            if not self.stop_requested:
                for entry in due_logs(float('inf')):
                    yield entry

            while not self.stop_requested:
                remaining = max(channel_ready.values(),
                                default=time.monotonic()) - time.monotonic()
                if remaining <= 0:
                    break
                time.sleep(min(0.1, remaining))
            self.wait_for_channels(range(pygame.mixer.get_num_channels()),
                                   should_stop=lambda: self.stop_requested)
            if self.verbose_mode:
                yield {"text": tr('play_done'), "type": "info"}
        except Exception as error:
            traceback.print_exc()
            yield {"text": tr('play_error', error=error), "type": "error"}
        finally:
            self.stop_all_audio()
            self.is_playing = False
            self.stop_requested = False
            if owns_lock:
                self.play_lock.release()

    def export_from_queue(self, text, output_path, include_bell=False, device=None,
                          pitch=1.0, speed=-10, enable_number_reading=False,
                          enable_special_bell=False):
        if not self.play_lock.acquire(False):
            return False, tr('play_busy')
        try:
            return self._export_from_queue_unlocked(
                text, output_path, include_bell, device, pitch, speed,
                enable_number_reading, enable_special_bell)
        finally:
            self.play_lock.release()

    def _export_from_queue_unlocked(self, text, output_path, include_bell=False, device=None,
                                    pitch=1.0, speed=-10, enable_number_reading=False,
                                    enable_special_bell=False):
        if not text:
            return False, tr('nothing_to_export')
        self.set_progress_stage('parse')
        plan = self.interpret_broadcast_text(
            text, pitch=pitch, speed=speed,
            enable_number_reading=enable_number_reading,
            include_bell=include_bell, enable_special_bell=enable_special_bell)
        if not plan['events']:
            return False, '; '.join(plan['errors']) or tr('no_export_audio')

        audio_events = [event for event in plan['events'] if len(event['audio']) > 0]
        if not audio_events:
            return False, '; '.join(plan['errors']) or tr('no_export_audio')

        self.set_progress_stage('export')
        duration = max(event['end_ms'] for event in plan['events'])
        longest = max(event['start_ms'] + len(event['audio']) for event in audio_events)
        duration = max(duration, longest)
        first_audio = audio_events[0]['audio']
        output_audio = AudioSegment.silent(
            duration=duration, frame_rate=first_audio.frame_rate
        ).set_channels(first_audio.channels).set_sample_width(first_audio.sample_width)
        for event in audio_events:
            audio = event['audio'].set_frame_rate(output_audio.frame_rate)
            audio = audio.set_channels(output_audio.channels).set_sample_width(output_audio.sample_width)
            output_audio = output_audio.overlay(audio, position=event['start_ms'])
        output_audio += AudioSegment.silent(duration=1000, frame_rate=output_audio.frame_rate)

        try:
            self.export_audio(output_audio, output_path, fmt='wav')
        except Exception as error:
            return False, tr('wav_write_failed', error=error)
        self._emit_progress(force_percent=100)
        return True, output_path

    def process_audio_with_pitch(self, filepath, pitch):
        if pitch == 1.0:
            return filepath

        audio = self.load_audio(filepath)
        new_frame_rate = int(audio.frame_rate * pitch)
        audio = audio._spawn(audio.raw_data, overrides={'frame_rate': new_frame_rate})
        audio = audio.set_frame_rate(audio.frame_rate)
        export_path = os.path.join(tempfile.gettempdir(), 'temp_stutter.wav')
        self.export_audio(audio, export_path)
        return export_path

    def snapshot_settings(self):
        snapshot = {}
        for field in API_MUTABLE_FIELDS:
            snapshot[field] = getattr(self, field, SYNTHESIS_PARAM_DEFAULTS.get(field))
        return snapshot

    def merged_settings(self, overrides=None):
        snapshot = self.snapshot_settings()
        for key, value in (overrides or {}).items():
            if key in API_MUTABLE_FIELDS and value is not None:
                snapshot[key] = value
        return snapshot

    @contextlib.contextmanager
    def settings_snapshot(self, overrides=None):
        settings = self.merged_settings(overrides)
        with self.settings_lock:
            backup = self.snapshot_settings()
            try:
                for key, value in settings.items():
                    setattr(self, key, value)
                yield settings
            finally:
                for key, value in backup.items():
                    setattr(self, key, value)

    def list_words(self):
        return sorted(self.word_set)

    def list_sounds(self):
        names = set()
        for base in (SOUND_BASE_PATH, AUDIO_BASE_PATH):
            if not os.path.isdir(base):
                continue
            for name in os.listdir(base):
                if name.lower().endswith(AUDIO_EXTENSION):
                    names.add(name)
        return sorted(names)

    def library_status(self):
        words_dir = [f for f in os.listdir(AUDIO_BASE_PATH)
                     if f.lower().endswith(AUDIO_EXTENSION)] if os.path.isdir(AUDIO_BASE_PATH) else []
        sounds_dir = [f for f in os.listdir(SOUND_BASE_PATH)
                      if f.lower().endswith(AUDIO_EXTENSION)] if os.path.isdir(SOUND_BASE_PATH) else []
        return {
            'words_dir': AUDIO_BASE_PATH,
            'sounds_dir': SOUND_BASE_PATH,
            'word_files': len(words_dir),
            'sound_files': len(sounds_dir),
            'known_words': len(self.word_set),
            'special_bell_start_exists': os.path.exists(
                self.get_special_bell_path(self.special_bell_start, 'bell_start.wav')),
            'special_bell_end_exists': os.path.exists(
                self.get_special_bell_path(self.special_bell_end, 'bell_end.wav')),
            'ffmpeg_available': shutil.which('ffmpeg') is not None,
        }

    def validate_text(self, text):
        not_found = self.check_spelling(text or '')
        return {'text': text or '', 'not_found': not_found, 'ok': not not_found}

    def plan_broadcast(self, text, overrides=None):
        with self.settings_snapshot(overrides) as settings:
            started = time.monotonic()
            plan = self.interpret_broadcast_text(
                text,
                pitch=settings['pitch'],
                speed=settings['speed'],
                enable_number_reading=settings['enable_number_reading'],
                include_bell=settings['include_bell'],
                enable_special_bell=settings['enable_special_bell'],
            )
            elapsed = time.monotonic() - started
        all_events = plan['events']
        events = [event for event in all_events if not event.get('silent')]
        content_end = int(plan.get('content_ms', 0))
        tail_end = int(plan.get('duration_ms', 0))
        return {
            'text': text,
            'errors': plan['errors'],
            'word_count': plan.get('word_count', 0),
            'event_count': len(events),
            'duration_ms': tail_end,
            'content_ms': content_end,
            'tail_ms': max(0, tail_end - content_end),
            'channels_used': sorted({event['channel'] for event in events}),
            'events': [{
                'index': index,
                'channel': event['channel'],
                'label': event.get('label', ''),
                'start_ms': int(event['start_ms']),
                'end_ms': int(event['end_ms']),
                'duration_ms': int(event.get('audio_length_ms', len(event['audio']))),
                'slot_ms': int(event['end_ms'] - event['start_ms']),
                'is_alarm': bool(event.get('is_alarm')),
            } for index, event in enumerate(events)],
            'settings': settings,
            'elapsed_ms': int(elapsed * 1000),
        }

    def synthesize(self, text, output_path=None, overrides=None, filename=None):
        if not text or not text.strip():
            return False, tr('content_empty'), {}

        with self.settings_snapshot(overrides) as settings:
            started = time.monotonic()
            if output_path is None:
                handle = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
                output_path = handle.name
                handle.close()

            if not self.play_lock.acquire(False):
                return False, tr('play_busy'), {}

            try:
                ok, result = self._export_from_queue_unlocked(
                    text,
                    output_path,
                    include_bell=settings['include_bell'],
                    pitch=settings['pitch'],
                    speed=settings['speed'],
                    enable_number_reading=settings['enable_number_reading'],
                    enable_special_bell=settings['enable_special_bell'],
                )
            finally:
                self.play_lock.release()

            if not ok:
                if os.path.exists(output_path):
                    os.unlink(output_path)
                return False, result, {}

            return True, output_path, {
                'text': text,
                'filename': filename or os.path.basename(output_path),
                'size_bytes': os.path.getsize(output_path),
                'elapsed_ms': int((time.monotonic() - started) * 1000),
                'settings': settings,
            }

    def start_playback(self, text, overrides=None):
        if not text or not text.strip():
            return False, tr('content_empty')
        if self.is_playing:
            return False, tr('play_busy')

        settings = self.merged_settings(overrides)

        def run():
            try:
                with self.settings_snapshot(settings):
                    for _ in self.play_broadcast_stream(text):
                        pass
            except Exception:
                traceback.print_exc()

        thread = threading.Thread(target=run, daemon=True, name='cassie-api-playback')
        thread.start()
        return True, ''

    def stop_playback(self):
        self.stop_requested = True
        self.stop_all_audio()
        return True

    def health(self):
        status = self.library_status()
        return {
            'api_version': API_VERSION,
            'project_version': PROJECT_VERSION,
            'status': 'ok',
            'language': current_language(),
            'pid': os.getpid(),
            'started_at': getattr(self, 'started_at', None),
            'features': self.feature_flags(),
            'spatial_quality_levels': len(self.SPATIAL_QUALITY_LEVELS),
            'python': '{}.{}.{}'.format(*sys.version_info[:3]),
            'platform': sys.platform,
            'playing': bool(self.is_playing),
            'stop_requested': bool(self.stop_requested),
            'play_lock_held': bool(self.play_lock.locked()),
            'audio_device_count': pygame.mixer.get_num_channels(),
            'mixer_initialized': bool(pygame.mixer.get_init()),
            'library': status,
        }

    def feature_flags(self):
        checks = {
            'spoken_label': 'spoken_label',
            'spoken_parts': 'spoken_parts',
            'number_words': 'NUMBER_WORDS',
            'spatial_quality_tiers': 'SPATIAL_QUALITY_LEVELS',
            'sentence_mode': 'uses_sentence_processing',
            'mono_reverb': 'spatial_profile',
            'settings_persistence': 'save_settings',
            'load_audio': 'load_audio',
        }
        flags = {}
        for name, attribute in checks.items():
            owner = type(self)
            flags[name] = hasattr(self, attribute) or hasattr(owner, attribute) \
                or hasattr(sys.modules[__name__], attribute)
        return flags

    def api_documentation(self):
        return {
            'api_version': API_VERSION,
            'prefix': API_PREFIX,
            'description': tr('api_description'),
            'endpoints': sorted(
                ['{} {}'.format(method, rule) for rule in _API_ROUTES for method in _API_ROUTES[rule]]
            ),
            'parameter_defaults': SYNTHESIS_PARAM_DEFAULTS,
            'mutable_fields': list(API_MUTABLE_FIELDS),
        }

_API_ROUTES = {}

def api_route(rule, method='GET'):
    def decorator(func):
        _API_ROUTES.setdefault(rule, []).append(method.upper())
        return route(API_PREFIX + rule, method=method)(func)
    return decorator

def api_success(data=None, status=200, **extra):
    response.status = status
    payload = {'ok': True, 'api_version': API_VERSION}
    if data is not None:
        payload['data'] = data
    payload.update(extra)
    response.content_type = 'application/json; charset=UTF-8'
    return json.dumps(payload, ensure_ascii=False)

def api_error(message, code='bad_request', status=400, **extra):
    response.status = status
    response.content_type = 'application/json; charset=UTF-8'
    error = {'code': code, 'message': str(message)}
    payload = {'ok': False, 'api_version': API_VERSION, 'error': error}
    for key in ('unknown_fields',):
        if key in extra:
            error[key] = extra.pop(key)
    payload.update(extra)
    return json.dumps(payload, ensure_ascii=False)

def api_payload():
    raw = request.body.read()
    if not raw:
        return {}
    try:
        data = json.loads(raw.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None

def api_guard():
    expected = os.environ.get('CASSIE_API_KEY')
    if not expected:
        return None
    provided = request.headers.get('X-API-Key') or request.query.get('api_key') or ''
    if provided == expected:
        return None
    return api_error(tr('api_key_invalid'), code='unauthorized', status=401)

cassie = CASSIETerminal()


def safe_alarm_id(alarm_id):
    alarm_id = (alarm_id or '').strip()
    if not re.fullmatch(r'[A-Za-z0-9_\-]{1,64}', alarm_id):
        return None
    return alarm_id


def alarm_path(alarm_id):
    safe = safe_alarm_id(alarm_id)
    if safe is None:
        return None
    return os.path.join(ALARM_DIR, safe + ALARM_EXTENSION)


def list_alarm_audio():
    items = []
    if not os.path.isdir(ALARM_AUDIO_DIR):
        return items
    for name in sorted(os.listdir(ALARM_AUDIO_DIR)):
        if not name.lower().endswith(AUDIO_EXTENSION):
            continue
        if name.startswith('._'):
            continue
        try:
            duration = len(AudioSegment.from_file(os.path.join(ALARM_AUDIO_DIR, name)))
        except Exception:
            duration = 0
        items.append({'name': name, 'duration_ms': duration})
    return items


def list_alarms():
    alarms = []
    if not os.path.isdir(ALARM_DIR):
        return alarms
    for name in sorted(os.listdir(ALARM_DIR)):
        if not name.lower().endswith(ALARM_EXTENSION):
            continue
        alarm_id = name[:-len(ALARM_EXTENSION)]
        try:
            with open(os.path.join(ALARM_DIR, name), 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        alarms.append({
            'id': alarm_id,
            'name': data.get('name') or alarm_id,
            'loop': data.get('loop', 1),
            'track_count': len(data.get('tracks') or []),
            'duration_ms': data.get('duration_ms', 0),
        })
    return alarms


def load_alarm(alarm_id):
    path = alarm_path(alarm_id)
    if path is None or not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    data['id'] = safe_alarm_id(alarm_id)
    data.setdefault('name', data['id'])
    data.setdefault('tracks', [])
    data.setdefault('loop', 1)
    return data


def _api_ready():
    return api_guard()

@api_route('')
@api_route('/')
def api_index():
    guard = _api_ready()
    if guard:
        return guard
    return api_success(cassie.api_documentation())

@api_route('/health')
def api_health():
    guard = _api_ready()
    if guard:
        return guard
    return api_success(cassie.health())

@api_route('/words')
def api_words():
    guard = _api_ready()
    if guard:
        return guard
    words = cassie.list_words()
    return api_success({'count': len(words), 'words': words})

@api_route('/sounds')
def api_sounds():
    guard = _api_ready()
    if guard:
        return guard
    sounds = cassie.list_sounds()
    return api_success({'count': len(sounds), 'sounds': sounds})

@api_route('/validate', method='POST')
def api_validate():
    guard = _api_ready()
    if guard:
        return guard
    data = api_payload()
    if data is None:
        return api_error(tr('json_object_required'), code='invalid_json')
    text = data.get('text', '')
    if not isinstance(text, str):
        return api_error(tr('text_must_be_string'))
    return api_success(cassie.validate_text(text))

@api_route('/plan', method='POST')
def api_plan():
    guard = _api_ready()
    if guard:
        return guard
    data = api_payload()
    if data is None:
        return api_error(tr('json_object_required'), code='invalid_json')
    text = data.get('text', '')
    if not text or not text.strip():
        return api_error(tr('content_empty'), code='empty_text')
    overrides, bad = _api_collect_overrides(data)
    if bad:
        return api_error(tr('unknown_fields', fields=', '.join(bad)),
                         code='unknown_fields', unknown_fields=bad)
    try:
        result = cassie.plan_broadcast(text, overrides)
    except Exception as error:
        traceback.print_exc()
        return api_error(tr('plan_failed', error=error), code='plan_failed', status=500)
    return api_success(result)


@api_route('/play', method='POST')
def api_play():
    guard = _api_ready()
    if guard:
        return guard
    data = api_payload()
    if data is None:
        return api_error(tr('json_object_required'), code='invalid_json')
    text = data.get('text', '')
    if not text or not text.strip():
        return api_error(tr('content_empty'), code='empty_text')
    overrides, bad = _api_collect_overrides(data)
    if bad:
        return api_error(tr('unknown_fields', fields=', '.join(bad)),
                         code='unknown_fields', unknown_fields=bad)
    started, message = cassie.start_playback(text, overrides)
    if not started:
        return api_error(message, code='playback_rejected', status=409)
    return api_success({'playing': True, 'text': text}, status=202)

@api_route('/stop', method='POST')
def api_stop():
    guard = _api_ready()
    if guard:
        return guard
    cassie.stop_playback()
    return api_success({'playing': False, 'stop_requested': True})

@api_route('/status')
def api_status():
    guard = _api_ready()
    if guard:
        return guard
    return api_success({
        'playing': bool(cassie.is_playing),
        'stop_requested': bool(cassie.stop_requested),
        'play_lock_held': bool(cassie.play_lock.locked()),
    })

@api_route('/settings')
def api_get_settings():
    guard = _api_ready()
    if guard:
        return guard
    return api_success({
        'settings': cassie.snapshot_settings(),
        'defaults': SYNTHESIS_PARAM_DEFAULTS,
        'mutable_fields': list(API_MUTABLE_FIELDS),
    })

_API_FIELD_ALIASES = {
    'enable_bell': 'include_bell',
    'bell': 'include_bell',
    'special_bell': 'enable_special_bell',
    'number_reading': 'enable_number_reading',
    'spatial': 'broadcast_effect_enabled',
}


def _api_collect_overrides(data):
    overrides = {}
    bad = []
    for key, value in data.items():
        if key in ('text', 'filename', 'download', 'base64', 'reset'):
            continue
        name = _API_FIELD_ALIASES.get(key, key)
        if name in API_MUTABLE_FIELDS:
            overrides[name] = value
        else:
            bad.append(key)
    return overrides, sorted(bad)


@api_route('/settings', method='POST')
@api_route('/settings', method='PUT')
def api_set_settings():
    guard = _api_ready()
    if guard:
        return guard
    data = api_payload()
    if data is None:
        return api_error(tr('json_object_required'), code='invalid_json')

    reset = bool(data.get('reset'))
    fields = {key: value for key, value in data.items() if key != 'reset'}

    unknown = sorted(key for key in fields if key not in API_MUTABLE_FIELDS)
    if unknown:
        return api_error(tr('unknown_fields', fields=', '.join(unknown)),
                         code='unknown_fields', unknown_fields=unknown)

    if reset:
        applied = dict(SYNTHESIS_PARAM_DEFAULTS)
    else:
        applied = {key: value for key, value in fields.items() if key in API_MUTABLE_FIELDS}

    if not applied:
        return api_error(tr('no_fields'), code='no_fields')

    if 'spatial_quality' in applied:
        applied['spatial_quality'] = CASSIETerminal.quality_profile(
            applied['spatial_quality'])['level']
    if 'spatial_mode' in applied:
        mode = str(applied['spatial_mode']).lower()
        if mode not in CASSIETerminal.SPATIAL_MODES:
            return api_error(
                tr('spatial_mode_invalid',
                   modes=language_join(CASSIETerminal.SPATIAL_MODES)),
                code='invalid_value')
        applied['spatial_mode'] = mode

    with cassie.settings_lock:
        for key, value in applied.items():
            setattr(cassie, key, value)
        cassie._reverb_cache.clear()
        cassie.save_settings()

    return api_success({'applied': applied, 'settings': cassie.snapshot_settings()})


@hook('after_request')
def apply_cors_headers():
    response.set_header('Access-Control-Allow-Origin', '*')
    response.set_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
    response.set_header('Access-Control-Allow-Headers',
                        'Content-Type, X-API-Key, X-Cassie-Lang')


@hook('before_request')
def cors_preflight():
    if request.method == 'OPTIONS':
        raise HTTPResponse(status=204, headers={
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type, X-API-Key, X-Cassie-Lang',
            'Access-Control-Max-Age': '600',
        })


if __name__ == '__main__':
    _health = cassie.health()
    _missing = [name for name, present in _health['features'].items() if not present]
    _library = _health['library']

    if not _library['word_files']:
        print()
        print('=' * 68)
        print(tr('assets_missing_title'))
        print(tr('assets_missing_where', path=_library['words_dir']))
        print(tr('assets_missing_how'))
        print(tr('assets_missing_how2', url=ASSETS_DOWNLOAD_URL))
        print(tr('assets_missing_after'))
        print('=' * 68)
        print()

    print(tr('startup_open_browser', port=port))
    run(host=API_HOST, port=port, server='cheroot', debug=False)
