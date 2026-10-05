"""Update the home introduction and restore the current Agent detail page."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import shutil


root = Path('/opt/chenwj-portfolio/public')
source = Path(__file__).resolve().parent
home = (source / 'index.html').read_text(encoding='utf-8')
game = (source / 'game.html').read_text(encoding='utf-8')
assert home.count('<article>') == 12
assert 'milestone-row' not in home
assert 'RAG 置信度与回答准确性' in home
assert 'id="architecture"' in game and 'id="reliability"' in game
assert '演示暂未启动' not in game
for asset in ('agent.css', 'controls.css', 'motion-fix.css', 'entrance.js', 'motion-core.js'):
    assert (root / 'portfolio-assets' / asset).is_file(), asset
stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
backup = Path('/opt/game-support-deploy') / ('home-six-restore-' + stamp)
backup.mkdir(mode=0o700)
for name in ('index.html', 'game.html'):
    shutil.copy2(root / name, backup / name)
    staged = root / (name + '.home-six.tmp')
    shutil.copyfile(source / name, staged)
    staged.chmod(0o644)
    staged.replace(root / name)
    assert (root / name).read_bytes() == (source / name).read_bytes()
    print(name, hashlib.sha256((root / name).read_bytes()).hexdigest())
print('Backup:', backup)
