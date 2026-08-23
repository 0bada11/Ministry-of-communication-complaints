/* Presentation helpers: Arabic-Indic numerals, dates, labels and DOM building.

   The design writes every count and date in Arabic-Indic digits, so numbers go
   through ar() on the way to the screen. Reference numbers stay Latin — they
   are identifiers the citizen copies and retypes. */

const Fmt = (() => {
  const ARABIC_DIGITS = '٠١٢٣٤٥٦٧٨٩';
  const MONTHS = [
    'كانون الثاني', 'شباط', 'آذار', 'نيسان', 'أيار', 'حزيران',
    'تموز', 'آب', 'أيلول', 'تشرين الأول', 'تشرين الثاني', 'كانون الأول',
  ];

  const ar = (value) =>
    String(value).replace(/[0-9]/g, (d) => ARABIC_DIGITS[Number(d)]);

  const pad = (n) => String(n).padStart(2, '0');

  /* Timestamps arrive as UTC ISO strings; render them in the viewer's zone. */
  const parse = (iso) => new Date(iso.endsWith('Z') || iso.includes('+') ? iso : `${iso}Z`);

  function time(date) {
    return ar(`${pad(date.getHours())}:${pad(date.getMinutes())}`);
  }

  /* "اليوم ٠٩:١٥" / "أمس ١٧:٤٠" / "٢٠ آب ٠٨:٥٥" — the three shapes the design uses. */
  function moment(iso) {
    if (!iso) return '—';
    const date = parse(iso);
    const today = new Date();
    const midnight = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
    const days = Math.round((midnight(today) - midnight(date)) / 86400000);

    if (days === 0) return `اليوم ${time(date)}`;
    if (days === 1) return `أمس ${time(date)}`;
    return `${ar(date.getDate())} ${MONTHS[date.getMonth()]} ${time(date)}`;
  }

  function shortDate(iso) {
    const date = parse(iso);
    return `${ar(date.getDate())} ${MONTHS[date.getMonth()]}`;
  }

  function fileSize(bytes) {
    if (bytes < 1024) return `${ar(bytes)} بايت`;
    if (bytes < 1024 * 1024) return `${ar((bytes / 1024).toFixed(1)).replace('.', '٫')} ك.ب`;
    return `${ar((bytes / (1024 * 1024)).toFixed(1)).replace('.', '٫')} م.ب`;
  }

  /* "٤١ ساعة" for long spans, "٣٫٥ ساعة" for short ones. */
  function hours(value) {
    if (value === null || value === undefined) return '—';
    const rounded = value >= 10 ? Math.round(value) : Number(value.toFixed(1));
    return `${ar(String(rounded).replace('.', '٫'))} ساعة`;
  }

  function percent(value) {
    return `${ar(Math.round(value))}٪`;
  }

  function signed(value, suffix = '٪') {
    const sign = value > 0 ? '+' : value < 0 ? '−' : '';
    return `${sign}${ar(Math.abs(Math.round(value)))}${suffix}`;
  }

  /* Tiny element builder — keeps the render functions readable without a
     framework. Children may be nodes or strings. */
  function el(tag, props = {}, children = []) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(props)) {
      if (value === null || value === undefined || value === false) continue;
      if (key === 'class') node.className = value;
      else if (key === 'text') node.textContent = value;
      else if (key === 'html') node.innerHTML = value;
      else if (key === 'style') node.setAttribute('style', value);
      else if (key.startsWith('on')) node.addEventListener(key.slice(2).toLowerCase(), value);
      else if (key === 'dataset') Object.assign(node.dataset, value);
      else node.setAttribute(key, value);
    }
    for (const child of [].concat(children)) {
      if (child === null || child === undefined || child === false) continue;
      node.append(child);
    }
    return node;
  }

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
    return node;
  }

  function toast(message, isError = false) {
    document.querySelectorAll('.toast').forEach((t) => t.remove());
    const node = el('div', { class: `toast${isError ? ' is-error' : ''}`, text: message });
    document.body.append(node);

    // Rises into place and sinks back out along the same path, so it reads as
    // one object arriving and leaving rather than two separate effects.
    const paint = (t) => {
      node.style.transform = `translate3d(0, ${((1 - t) * 20).toFixed(2)}px, 0)`;
      node.style.opacity = t.toFixed(3);
    };
    const spring = Motion.spring({ from: 0, precision: 0.001, onUpdate: paint });
    paint(0);
    spring.to(1, { preset: 'ui' });

    setTimeout(() => {
      spring.onRest = () => node.remove();
      spring.to(0, { preset: 'ui' });
    }, isError ? 6000 : 3500);
  }

  return { ar, moment, shortDate, fileSize, hours, percent, signed, el, clear, toast };
})();
