"""Install the four visible digit fields in the existing portfolio login page."""
from pathlib import Path
import re
import shutil

root = Path('/opt/chenwj-portfolio/public')
page = root/'login.html'
shutil.copy2(page, Path('/opt/game-support-deploy/login-before-four.html'))
text = page.read_text(encoding='utf-8')
text = text.replace('id="login-form"','id="visitor-login-form"').replace('手机号的后 6 位','手机号的后四位').replace('for="password"','for="pin-1"')
fields = '<fieldset class="pin-fields" aria-label="手机号后四位">' + ''.join(
    f'<input class="pin-digit" id="pin-{i}" name="digit-{i}" type="text" inputmode="numeric" pattern="[0-9]" maxlength="1" required autocomplete="off" aria-label="密码第 {i} 位" aria-describedby="login-error">'
    for i in range(1,5)) + '</fieldset>'
text = re.sub(r'<div class="password-field">.*?</div>',fields,text,flags=re.S)
text = re.sub(r'<p class="login-policy">.*?</p>','',text)
text = re.sub(r'<link[^>]*href="/portfolio-assets/login-four.css[^>]*>|<script[^>]*src="/portfolio-assets/login-four.js[^>]*></script>','',text)
text = text.replace('</head>', '<link rel="stylesheet" href="/portfolio-assets/login-four.css?v=20261005a"><script defer src="/portfolio-assets/login-four.js?v=20261005a"></script></head>')
page.write_text(text,encoding='utf-8')
for name in ('login-four.css','login-four.js'):
    target = root/'portfolio-assets'/name
    shutil.copy2(Path(__file__).with_name(name),target)
    target.chmod(0o644)
