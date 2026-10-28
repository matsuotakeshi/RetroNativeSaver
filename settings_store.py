"""Small, lossless-in-values editor for the existing configuration document."""
from ui_text import tr as _tr
from copy import deepcopy
from dataclasses import dataclass
import datetime
import json
import math
import os
from pathlib import Path
import re
import tempfile
import uuid


@dataclass(frozen=True)
class Field:
    path: tuple
    label: str
    default: object
    kind: str = 'number'
    minimum: float = 0
    maximum: float | None = None

    def parse(self, value):
        if self.kind == 'language':
            from ui_text import LANGUAGES
            if value not in LANGUAGES:
                raise ValueError(_tr('言語を一覧から選択してください。'))
            return value
        try:
            if self.kind in ('text', 'path'):
                if not isinstance(value, str) or any(c in value for c in ('\0', '\r', '\n')):
                    raise ValueError()
                if self.kind == 'path' and '"' in value:
                    raise ValueError()
                return value.strip()
            if self.kind == 'bool':
                if type(value) is not bool:
                    raise ValueError()
                return value
            if self.kind == 'color':
                value = str(value).strip()
                if not re.fullmatch(r'#[0-9a-fA-F]{6}', value):
                    raise ValueError()
                return value
            if isinstance(value, bool):
                raise ValueError()
            number = float(value)
            if (not math.isfinite(number) or number < self.minimum
                    or (self.maximum is not None and number > self.maximum)
                    or (self.kind == 'int' and not number.is_integer())):
                raise ValueError()
            return int(number) if self.kind == 'int' else number
        except (ValueError, TypeError, OverflowError):
            if self.kind in ('text', 'path'):
                rule = _tr('改行・引用符を含まないパス') if self.kind == 'path' else _tr('改行を含まない文字列')
            elif self.kind == 'color':
                rule = _tr('#RRGGBB 形式（例: #909090）')
            elif self.kind == 'bool':
                rule = _tr('オンまたはオフ')
            else:
                rule = _tr('{v0:g}以上', v0=self.minimum) + (_tr('、{v0:g}以下', v0=self.maximum) if self.maximum is not None else '')
                rule += _tr('の整数') if self.kind == 'int' else _tr('の数値')
            raise ValueError(_tr('「{v0}」は{v1}を指定してください。', v0=_tr(self.label), v1=rule)) from None


GENERAL = (
    Field(('ui_language',), 'Language / 言語', 'auto', 'language'),
    Field(('retroarch_path',), 'RetroArchのEXE（空欄で自動検出）', '', 'path'),
    Field(('multi_monitor',), '複数モニターに表示する', True, 'bool'),
    Field(('tile_rows',), '縦タイル数（0:従来の自動配置、1:各画面に1枠）', 0, 'int', 0, 64),
    Field(('tile_resize_keys_enabled',), 'PageUp／PageDownで全画面の縦タイル数を変更・保存する', True, 'bool'),
    Field(('independent_slots_enabled',), '枠ごとに非同期で入れ替える', False, 'bool'),
    Field(('cycle_seconds',), '共通の表示時間（秒）', 240, minimum=1),
    Field(('independent_jitter_seconds',), '表示時間のランダム幅（±秒）', 60),
    Field(('independent_max_fps',), '非同期表示の上限 FPS', 30, minimum=1),
    Field(('max_slots_per_monitor',), '従来の通常自動配置の枠数上限／モニター', 16, 'int', 1),
    Field(('fade_enabled',), 'フェードする', True, 'bool'),
    Field(('fade_duration_ms',), 'フェード時間（ミリ秒）', 800, 'int'),
    Field(('mouse_exit_threshold',), 'マウスで終了する移動量（px）', 12, 'int'),
    Field(('saver_controls_enabled',), '矢印・Insert・Delete・Enter操作を使う', False, 'bool'),
    Field(('log_output_enabled',), 'ログを出力する', False, 'bool'),
)
TITLE = (
    Field(('overlay', 'enabled'), '機種名・タイトルを表示する', True, 'bool'),
    Field(('overlay', 'scroll_enabled'), '1行でスクロールする', True, 'bool'),
    Field(('overlay', 'system_font_size'), '機種名／スクロールの文字サイズ（px）', 12, 'int', 8),
    Field(('overlay', 'game_font_size'), '固定表示のタイトル文字サイズ（px）', 16, 'int', 8),
    Field(('overlay', 'scroll_speed'), 'スクロール速度（px／秒、0で停止）', 24, maximum=200),
    Field(('overlay', 'scroll_pause_seconds'), 'スクロール前の待ち時間（秒）', 2, maximum=60),
    Field(('overlay', 'scroll_gap'), '繰り返しの間隔（px）', 48, 'int', 0, 4096),
    Field(('overlay', 'system_color'), '機種名の色', '#909090', 'color'),
    Field(('overlay', 'game_color'), 'タイトルの色', '#B8B8B8', 'color'),
    Field(('overlay', 'background_alpha'), '背景の濃さ（0:透明、255:黒）', 112, 'int', 0, 255),
    Field(('overlay', 'margin'), '画面端からの余白（px）', 6, 'int'),
    Field(('overlay', 'padding'), '文字まわりの余白（px）', 4, 'int'),
)
GROUP = (
    Field(('single_system_mode', 'enabled'), 'グループ表示を抽選に含める', False, 'bool'),
    Field(('single_system_mode', 'normal_weight'), '通常表示の割合', 50),
    Field(('single_system_mode', 'grouped_weight'), 'グループ表示の割合', 50),
    Field(('single_system_mode', 'max_fps'), 'グループ表示の上限 FPS', 25, minimum=1),
)
FIELDS = {field.path: field for field in (*GENERAL, *TITLE, *GROUP)}
WEIGHTS = (GROUP[1].path, GROUP[2].path)
DISABLED = ('single_system_mode', 'disabled_systems')


def get_value(config, field):
    if field.path == ('tile_resize_keys_enabled',) and 'tile_resize_keys_enabled' not in config:
        from tile_layout import resize_keys_enabled
        return resize_keys_enabled(config)
    value = config
    for key in field.path:
        if not isinstance(value, dict):
            raise ValueError(_tr('{v0} はJSONオブジェクトにしてください。', v0=" / ".join(field.path[:-1])))
        if key not in value:
            return field.default
        value = value[key]
    return value


def group_options(config):
    options = config.get('single_system_mode', {})
    if not isinstance(options, dict):
        raise ValueError(_tr('single_system_mode はJSONオブジェクトにしてください。'))
    return options


def display_values(config):
    values = {path: get_value(config, field) for path, field in FIELDS.items()}
    options = group_options(config)
    if 'normal_weight' not in options and 'grouped_weight' not in options:
        from single_system_mode import presentation_probability
        probability = presentation_probability(options)
        values[WEIGHTS[0]], values[WEIGHTS[1]] = (1 - probability) * 100, probability * 100
    return values


def group_rows(config):
    """Keep explicit membership and legacy singleton groups, including disabled IDs."""
    from single_system_mode import DEFAULT_GROUPS, configured_groups
    options = group_options(config)
    configured_groups(options)  # Validate without saving its normalized result.
    return deepcopy(options.get('groups', [[s] for s in options['systems']]
                    if 'systems' in options else [list(g) for g in DEFAULT_GROUPS]))


def updated_config(config, changes):
    result = deepcopy(config)
    for path, raw in changes.items():
        if path == DISABLED:
            from single_system_mode import configured_groups
            configured_groups({'disabled_systems': raw})
            value = deepcopy(raw)
        else:
            value = FIELDS[path].parse(raw)
        parent = result
        for key in path[:-1]:
            parent = parent.setdefault(key, {})
            if not isinstance(parent, dict):
                raise ValueError(_tr('{v0} はJSONオブジェクトにしてください。', v0=key))
        parent[path[-1]] = value
    if any(path in changes for path in WEIGHTS):
        from single_system_mode import presentation_probability
        try:
            presentation_probability(result['single_system_mode'])
        except ValueError:
            raise ValueError(_tr('表示の割合は両方を指定し、少なくとも片方を0より大きくしてください。')) from None
    return result


class SettingsDocument:
    def __init__(self, path, update=updated_config):
        self.path = Path(path).resolve()
        self.update = update
        self.original = self.path.read_bytes()
        self.data = json.loads(self.original.decode('utf-8'))
        if not isinstance(self.data, dict):
            raise ValueError(_tr('設定ファイルの最上位はJSONオブジェクトにしてください。'))

    def check_changes(self, changes):
        """Preflight a set of documents before the first file is written."""
        if not changes:
            return None
        result = self.update(self.data, changes)
        if result == self.data:
            return None
        if self.path.read_bytes() != self.original:
            raise ValueError(_tr('設定ファイルが別の操作で変更されています。画面を閉じて開き直してください。'))
        # Reject non-serializable/non-finite data during preflight, not midway through a batch.
        json.dumps(result, ensure_ascii=False, allow_nan=False)
        return result

    def save(self, changes):
        if self.check_changes(changes) is None:
            return None
        from file_transaction import file_locks
        with file_locks(self.path):
            result = self.check_changes(changes)
            if result is None:
                return None
            newline = '\r\n' if b'\r\n' in self.original else '\n'
            payload = (json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n').replace('\n', newline).encode('utf-8')
            backup = self.path.with_name(self.path.name + '.bak-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8])
            fd, name = tempfile.mkstemp(prefix=self.path.name + '.', suffix='.tmp', dir=self.path.parent)
            temporary = Path(name)
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                with backup.open('xb') as stream:
                    stream.write(self.original)
                    stream.flush()
                    os.fsync(stream.fileno())
                if self.path.read_bytes() != self.original:
                    raise ValueError(_tr('保存中に設定ファイルが変更されました。画面を開き直してください。'))
                from file_transaction import replace_checked
                replace_checked(temporary, self.path, self.original)
            finally:
                temporary.unlink(missing_ok=True)
            self.original, self.data = payload, result
            return backup
