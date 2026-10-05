const form = document.querySelector('#visitor-login-form');
if (form) {
  const digits = [...form.querySelectorAll('.pin-digit')];
  const error = form.querySelector('#login-error');
  const submit = form.querySelector('[type="submit"]');
  digits.forEach((input, index) => {
    input.addEventListener('input', () => {
      input.value = input.value.replace(/\D/g, '').slice(-1);
      if (input.value && index < 3) digits[index + 1].focus();
    });
    input.addEventListener('focus', () => input.select());
    input.addEventListener('keydown', event => {
      if (event.key === 'Backspace' && !input.value && index > 0) digits[index - 1].focus();
      if (event.key === 'ArrowLeft' && index > 0) digits[index - 1].focus();
      if (event.key === 'ArrowRight' && index < 3) digits[index + 1].focus();
    });
    input.addEventListener('paste', event => {
      event.preventDefault();
      const value = event.clipboardData.getData('text').replace(/\D/g, '').slice(0,4);
      if (!value) return;
      digits.forEach((digit, i) => { digit.value = value[i] || ''; });
      digits[Math.min(value.length,3)].focus();
    });
  });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (submit.disabled) return;
    const password = digits.map(input => input.value).join('');
    if (!/^\d{4}$/.test(password)) { error.textContent='请填写完整的四位访问密码。'; return; }
    submit.disabled = true; error.textContent='';
    try {
      const response = await fetch('/auth/login', {method:'POST',headers:{'Content-Type':'application/json','X-Portfolio-Request':'1'},body:JSON.stringify({password})});
      const data = await response.json();
      if (!response.ok) {
        if (response.status === 403) {
          digits.forEach(input => { input.disabled = true; });
          submit.dataset.blocked = '1';
        }
        throw new Error(data.error || '登录失败，请稍后再试。');
      }
      location.replace('/');
    } catch (reason) { error.textContent=reason.message || '暂时无法连接，请稍后再试。'; }
    finally { if (!submit.dataset.blocked) submit.disabled=false; }
  });
}
