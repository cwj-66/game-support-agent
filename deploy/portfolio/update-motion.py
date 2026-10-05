"""Add shared entrance effects to existing portfolio pages, with backups.

Upload player-chat/src/motion.js alongside this script as motion-core.js;
entrance.js loads that same module used by the React frontend.
"""
from pathlib import Path
from datetime import datetime, timezone
import shutil
import re

root = Path('/opt/chenwj-portfolio/public')
source = Path(__file__).parent
backup = Path('/opt/game-support-deploy') / ('motion-' + datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S'))
backup.mkdir()
for name in ('entrance.js', 'motion-core.js', 'motion-fix.css'):
    target = root / 'portfolio-assets' / name
    if target.exists():
        shutil.copy2(target, backup / name)
    shutil.copy2(source / name, target)
    target.chmod(0o644)
for page in root.glob('*.html'):
    text = page.read_text(encoding='utf-8')
    if '</head>' not in text:
        continue
    shutil.copy2(page, backup / page.name)
    text = re.sub(r'(/portfolio-assets/app\.js)(?:\?[^"\']*)?', r'\1?v=20261005c', text)
    text = re.sub(r'\s*<script\b[^>]*src=["\']/portfolio-assets/entrance\.js[^>]*></script>', '', text)
    text = re.sub(r'\s*<link\b[^>]*href=["\']/portfolio-assets/motion-fix\.css[^>]*>', '', text)
    text = text.replace('</head>', '<link rel="stylesheet" href="/portfolio-assets/motion-fix.css?v=20261005c">\n<script type="module" src="/portfolio-assets/entrance.js?v=20261005c"></script>\n</head>', 1)
    page.write_text(text, encoding='utf-8')
app = root / 'portfolio-assets/app.js'
shutil.copy2(app, backup / 'app.js')
js = app.read_text(encoding='utf-8')
# Switch directly between visible slides, without a fade-out/blank interval.
js = js.replace('await new Promise((resolve) => setTimeout(resolve, 220));', '')
app.write_text(js, encoding='utf-8')
print('Motion installed; backup:', backup)
