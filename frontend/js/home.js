/* Home screen: the stats strip, the category cards and the tracking box. */

const Home = (() => {
  const { el, ar, clear, moment, hours, percent } = Fmt;

  function renderStats(stats) {
    const within = stats.sla.percent.within + stats.sla.percent.near;
    const cells = [
      [ar(stats.total), 'شكوى مستلمة هذا العام'],
      [percent(within), 'نسبة الحل خلال المهلة'],
      [hours(stats.avg_resolution_hours), 'متوسط زمن المعالجة'],
      [`${ar(stats.departments.length)} دائرة`, 'جهة مرتبطة بالمنصة'],
    ];
    const host = clear(document.getElementById('home-stats'));
    cells.forEach(([value, label]) =>
      host.append(el('div', { class: 'statstrip-item' }, [
        el('span', { class: 'statstrip-value', text: value }),
        el('span', { class: 'statstrip-label', text: label }),
      ])));
  }

  function renderCategories(types) {
    const host = clear(document.getElementById('cat-grid'));
    types.forEach((type) =>
      host.append(el('button', {
        class: 'cat-card',
        type: 'button',
        onclick: () => App.go('submit', { type: type.value }),
      }, [
        el('span', { class: 'cat-code', text: type.code }),
        el('span', { class: 'cat-name', text: type.ar }),
        el('span', { class: 'cat-desc', text: type.description }),
        el('span', {
          class: 'cat-dept',
          text: `الدائرة المسؤولة: ${type.department ? type.department.name_ar : '—'}`,
        }),
      ])));
  }

  async function track(event) {
    event.preventDefault();
    const reference = document.getElementById('track-input').value.trim();
    const result = document.getElementById('track-result');
    const error = document.getElementById('track-error');
    if (!reference) return;

    result.hidden = true;
    error.hidden = true;
    try {
      const complaint = await API.track(reference);
      document.getElementById('track-status').textContent = App.statusLabel(complaint.status);
      document.getElementById('track-dept').textContent =
        complaint.department ? complaint.department.name_ar : '—';
      document.getElementById('track-date').textContent = moment(complaint.updated_at);
      result.hidden = false;
    } catch (err) {
      error.textContent = err.status === 404
        ? 'لا توجد شكوى بهذا الرقم المرجعي. تأكد من الرقم كما ورد في الرسالة القصيرة.'
        : err.message;
      error.hidden = false;
    }
  }

  function init() {
    document.getElementById('track-form').addEventListener('submit', track);
  }

  return { init, renderStats, renderCategories };
})();
