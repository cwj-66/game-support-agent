"""Install shared controls without replacing other portfolio pages."""
from pathlib import Path
from datetime import datetime, timezone
import shutil
import re

root = Path('/opt/chenwj-portfolio/public')
backup = Path('/opt/game-support-deploy') / ('controls-' + datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S'))
backup.mkdir()
css = root / 'portfolio-assets/controls.css'
if css.exists():
    shutil.copy2(css, backup / 'controls.css')
shutil.copy2(Path(__file__).with_name('controls.css'), css)
css.chmod(0o644)
link = '<link rel="stylesheet" href="/portfolio-assets/controls.css?v=20261005b">'
for page in root.glob('*.html'):
    source = page.read_text(encoding='utf-8')
    if '</head>' not in source:
        continue
    shutil.copy2(page, backup / page.name)
    source = re.sub(r'\s*<link\b[^>]*href=["\']/portfolio-assets/controls\.css[^>]*>', '', source)
    page.write_text(source.replace('</head>', link + '\n</head>', 1), encoding='utf-8')
print('Shared controls installed; backup:', backup)
