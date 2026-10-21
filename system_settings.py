"""Editable system settings; never import a core or normalize unedited JSON."""
from ui_text import tr as _tr
from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path
import re

from settings_store import Field, SettingsDocument

REMOVE = object()


@dataclass(frozen=True)
class SystemField(Field):
    section: str = '基本'
    inherit: bool = False
    choices: tuple = ()
    browse: str = ''
    only: tuple = ()

    def parse(self, value):
        if self.kind in ('extensions', 'lines'):
            if not isinstance(value, str) or '\0' in value:
                raise ValueError(_tr('「{v0}」の入力を確認してください。', v0=_tr(self.label)))
            values = [v.strip() for v in (re.split(r'[,;\s]+', value) if self.kind == 'extensions' else value.splitlines()) if v.strip()]
            if self.kind == 'extensions':
                values = [v if v.startswith('.') else '.' + v for v in values]
                if any(not re.fullmatch(r'\.[A-Za-z0-9]+', v) for v in values):
                    raise ValueError(_tr('「{v0}」は .zip, .chd のように指定してください。', v0=_tr(self.label)))
            return values
        result = super().parse(value)
        if self.choices and result not in self.choices:
            raise ValueError(_tr('「{v0}」は候補から選択してください。', v0=_tr(self.label)))
        return result


FIELDS = (
    SystemField(('enabled',), 'この機種を使用する', True, 'bool'),
    SystemField(('name',), '表示名', '', 'text'),
    SystemField(('core',), 'libretroコア（DLL）', '', 'path', browse='core'),
    SystemField(('rom_dir',), 'ROMフォルダー', '', 'path', browse='directory'),
    SystemField(('system_dir',), 'BIOSフォルダー', '', 'path', inherit=True, browse='directory'),
    SystemField(('save_dir',), 'セーブフォルダー', '', 'path', inherit=True, browse='directory'),
    SystemField(('assets_dir',), 'アセットフォルダー', '', 'path', inherit=True, browse='directory'),
    SystemField(('isolated_save_dir',), '一時セーブ領域を使う（終了時に破棄）', False, 'bool'),
    SystemField(('cycle_seconds',), '表示時間（秒）', 240, minimum=1, section='表示・負荷', inherit=True),
    SystemField(('independent_jitter_seconds',), '表示時間のランダム幅（±秒）', 60, section='表示・負荷', inherit=True),
    SystemField(('max_concurrent',), '通常表示の同時起動数（0で起動なし）', 999, 'int', section='表示・負荷'),
    SystemField(('resource_group',), '負荷グループ（空欄で制限対象外）', '', 'text', section='表示・負荷'),
    SystemField(('resource_weight',), '1枠あたりの負荷（weight）', 1, 'int', section='表示・負荷'),
    SystemField(('render_backend',), '描画方式', 'software', 'text', section='表示・負荷', choices=('software', 'opengl', 'glcore')),
    SystemField(('hw_context_width',), 'OpenGL描画領域の幅', 640, 'int', 1, section='表示・負荷'),
    SystemField(('hw_context_height',), 'OpenGL描画領域の高さ', 480, 'int', 1, section='表示・負荷'),
    SystemField(('extensions',), 'ROM拡張子（カンマ区切り）', [], 'extensions', section='ROM・起動'),
    SystemField(('content_extensions',), '展開後の拡張子（カンマ区切り）', [], 'extensions', section='ROM・起動', inherit=True),
    SystemField(('recursive',), 'サブフォルダーも検索する', False, 'bool', section='ROM・起動'),
    SystemField(('archive_mode',), 'アーカイブの扱い', 'auto', 'text', section='ROM・起動', choices=('auto', 'extract', 'passthrough')),
    SystemField(('validate_archive_contents',), '一覧作成時にアーカイブ内容を検査する', False, 'bool', section='ROM・起動'),
    SystemField(('exclude_name_contains',), 'ファイル名で除外する文字列（1行に1件）', [], 'lines', section='ROM・起動'),
    SystemField(('disk_boot_mode',), '複数ディスクの起動方式', '', 'text', section='ROM・起動', choices=('', 'pc88_two_drives', 'computer_two_drives')),
    SystemField(('startup_start_twice',), '起動後にStartを2回送る', True, 'bool', section='ROM・起動', only=('megacd', 'pcenginecd', 'neocd')),
    SystemField(('mame_machine',), 'MAMEの機種名（autoで自動）', 'auto', 'text', section='ROM・起動', only=('fm7',)),
    SystemField(('mame_bios_dir',), 'MAMEのBIOS ZIPフォルダー', '', 'path', section='ROM・起動', inherit=True, browse='directory', only=('fm7',)),
    SystemField(('process_recycle_required',), '周期終了時にプロセスを作り直す', False, 'bool', section='詳細'),
    SystemField(('provide_log_interface',), 'コアへログ用インターフェースを提供する', True, 'bool', section='詳細'),
    SystemField(('provide_perf_interface',), 'コアへ性能情報インターフェースを提供する', True, 'bool', section='詳細'),
    SystemField(('frame_rebind_context',), '毎フレーム描画コンテキストを再設定する', True, 'bool', section='詳細'),
    SystemField(('require_title_db_match',), 'タイトル一覧にあるROMだけを使う', False, 'bool', section='詳細'),
    SystemField(('title_db',), 'タイトル情報ファイル', '', 'path', section='詳細', browse='json'),
    SystemField(('title_sources',), 'タイトル情報の参照元（1行に1件）', [], 'lines', section='詳細'),
    SystemField(('title_core_names',), 'タイトル照合用コア名（1行に1件）', [], 'lines', section='詳細'),
    SystemField(('title_path_roots',), 'タイトル照合用ROMルート（1行に1件）', [], 'lines', section='詳細'),
)
BY_PATH = {f.path: f for f in FIELDS}


def fields_for(data):
    return [f for f in FIELDS if not f.only or data.get('id') in f.only or f.path[0] in data]


def update_system(data, changes):
    result = deepcopy(data)
    for path, value in changes.items():
        if len(path) == 2 and path[0] == 'core_options':
            name = path[1]
            if not isinstance(name, str) or not name.strip() or any(c in name for c in ('\0', '\n', '\r')):
                raise ValueError(_tr('コアオプション名を確認してください。'))
            options = result.setdefault('core_options', {})
            if not isinstance(options, dict):
                raise ValueError(_tr('core_options はJSONオブジェクトにしてください。'))
            if value is REMOVE:
                options.pop(name, None)
            else:
                if not isinstance(value, str) or any(c in value for c in ('\0', '\n', '\r')):
                    raise ValueError(_tr('コアオプション「{v0}」の値を確認してください。', v0=name))
                options[name] = value
            continue
        field = BY_PATH[path]  # IDs and unknown fields cannot be modified by this editor.
        if value is REMOVE:
            if not field.inherit:
                raise ValueError(_tr('{v0} は省略できません。', v0=_tr(field.label)))
            result.pop(path[0], None)
        else:
            parsed = field.parse(value)
            if path[0] in ('name', 'core', 'rom_dir') and not parsed:
                raise ValueError(_tr('「{v0}」は空欄にできません。', v0=_tr(field.label)))
            if field.inherit and field.kind == 'path' and not parsed:
                raise ValueError(_tr('「{v0}」を省略する場合は「共通／既定」を選んでください。', v0=_tr(field.label)))
            result[path[0]] = parsed
    return result


def default_value(field, data, common):
    key = field.path[0]
    if key == 'name':
        return data.get('id', '')
    if key == 'system_dir':
        return common.get(key, r'C:\RetroArch-win64\system')
    if key == 'save_dir':
        return common.get(key) or 'save'
    if key == 'assets_dir':
        return common.get(key, r'C:\RetroArch-win64\downloads')
    if key in ('cycle_seconds', 'independent_jitter_seconds'):
        return common.get(key, field.default)
    if key == 'content_extensions':
        return data.get('extensions', [])
    if key == 'mame_bios_dir':
        return data.get('rom_dir', '')
    return field.default


def display_value(field, raw):
    if field.kind == 'bool':
        return bool(raw)
    if field.kind in ('extensions', 'lines') and isinstance(raw, list) and all(isinstance(v, str) for v in raw):
        return (', ' if field.kind == 'extensions' else '\n').join(raw)
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return format(raw, '.15g')
    return str(raw)


class SystemDraft:
    def __init__(self, path, common):
        self.document = SettingsDocument(path, update=update_system)
        data = self.document.data
        if not isinstance(data.get('id'), str) or not data['id'].strip():
            raise ValueError(_tr('機種IDがありません。'))
        self.fields = fields_for(data)
        self.values = {f.path: display_value(f, data.get(f.path[0], default_value(f, data, common))) for f in self.fields}
        self.inherited = {f.path: f.path[0] not in data for f in self.fields if f.inherit}
        self.options = deepcopy(data.get('core_options', {}))
        self.accept_saved()

    def accept_saved(self):
        self.initial = deepcopy(self.values)
        self.initial_inherited = dict(self.inherited)
        self.initial_options = deepcopy(self.options)

    def changes(self):
        changes = {}
        for field in self.fields:
            path = field.path
            if field.inherit and self.inherited[path]:
                if not self.initial_inherited[path]:
                    changes[path] = REMOVE
            elif (self.values[path] != self.initial[path]
                  or (field.inherit and self.inherited[path] != self.initial_inherited[path])):
                changes[path] = self.values[path]
        if isinstance(self.options, dict) and isinstance(self.initial_options, dict):
            for key in self.initial_options.keys() | self.options.keys():
                if key not in self.options:
                    changes[('core_options', key)] = REMOVE
                elif key not in self.initial_options or self.options[key] != self.initial_options[key]:
                    changes[('core_options', key)] = self.options[key]
        return changes


def load_drafts(app_dir, common):
    """Bad files remain visible as errors; they never prevent editing valid files."""
    directory = Path(app_dir) / common.get('systems_dir', 'systems')
    entries = []
    if not directory.is_dir():
        return directory, entries
    for path in sorted(directory.glob('*.json')):
        try:
            draft = SystemDraft(path, common)
            data = draft.document.data
            label = f"{data.get('name', data['id'])} ({data['id']}) — {path.name}"
            entries.append((label, draft, None))
        except (OSError, ValueError, TypeError) as exc:
            entries.append((_tr('読み込みエラー — {v0}', v0=path.name), None, str(exc)))
    return directory, entries
