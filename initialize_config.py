"""Create local settings from examples; never replace existing settings."""
from pathlib import Path
import shutil


def initialize(root):
    root=Path(root)
    for name in ('systems','state','metadata'):
        (root/name).mkdir(exist_ok=True)
    pairs=[(root/'config.example.json',root/'config.json'),
           (root/'favorites.example.json',root/'favorites.json'),
           (root/'persistent_rom_whitelist.default.json',root/'state/persistent_rom_whitelist.json')]
    pairs.extend((p,root/'systems'/p.name) for p in sorted((root/'systems.example').glob('*.json')))
    for source,destination in pairs:
        if destination.exists():
            continue
        with source.open('rb') as src, destination.open('xb') as dst:
            shutil.copyfileobj(src,dst)


if __name__=='__main__':
    initialize(Path(__file__).resolve().parent)
    print('Local settings are ready. Existing files were preserved.')
