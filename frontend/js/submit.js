/* Submit screen: the complaint form, its attachments, and the receipt. */

const Submit = (() => {
  const { el, ar, clear, fileSize, toast } = Fmt;

  const MAX_FILES = 5;
  const MAX_BYTES = 5 * 1024 * 1024; // matches the "٥ ميغابايت" the form promises

  let priority = 'medium';
  let files = [];

  /* ------------------------------------------------------------- render */

  function fillOptions(meta) {
    const type = clear(document.getElementById('f-type'));
    meta.types.forEach((t) => type.append(el('option', { value: t.value, text: t.ar })));

    const gov = clear(document.getElementById('f-gov'));
    meta.governorates.forEach((g) => gov.append(el('option', { value: g, text: g })));

    const row = clear(document.getElementById('pri-row'));
    meta.priorities.forEach((p) =>
      row.append(el('button', {
        type: 'button',
        class: `chip${p.value === priority ? ' is-active' : ''}`,
        dataset: { priority: p.value },
        text: p.ar,
        onclick: () => setPriority(p.value),
      })));
  }

  function setPriority(value) {
    priority = value;
    document.querySelectorAll('#pri-row .chip').forEach((chip) =>
      chip.classList.toggle('is-active', chip.dataset.priority === value));
  }

  function renderFiles() {
    const host = clear(document.getElementById('file-list'));
    files.forEach((file, index) =>
      host.append(el('div', { class: 'file-row' }, [
        el('span', { text: file.name }),
        el('span', { class: 'file-actions' }, [
          el('span', { class: 'size', text: fileSize(file.size) }),
          el('button', {
            type: 'button',
            title: 'إزالة المرفق',
            'aria-label': 'إزالة المرفق',
            text: '✕',
            onclick: () => { files.splice(index, 1); renderFiles(); },
          }),
        ]),
      ])));
  }

  function addFiles(incoming) {
    for (const file of incoming) {
      if (files.length >= MAX_FILES) {
        toast(`الحد الأقصى ${ar(MAX_FILES)} مرفقات.`, true);
        break;
      }
      if (file.size > MAX_BYTES) {
        toast(`الملف «${file.name}» يتجاوز ٥ ميغابايت.`, true);
        continue;
      }
      files.push(file);
    }
    renderFiles();
  }

  /* --------------------------------------------------------- validation */

  const RULES = {
    citizen_name: (v) => (v.trim().length < 2 ? 'الرجاء إدخال الاسم الكامل.' : ''),
    citizen_phone: (v) => {
      if (!v.trim()) return 'الرجاء إدخال رقم الموبايل.';
      return /^[0-9+\-() ]{6,}$/.test(v.trim()) ? '' : 'رقم الموبايل غير صالح.';
    },
    citizen_email: (v) =>
      (!v.trim() || /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(v.trim())
        ? '' : 'البريد الإلكتروني غير صالح.'),
    title: (v) => (v.trim().length < 3 ? 'الرجاء إدخال عنوان مختصر للشكوى.' : ''),
    description: (v) =>
      (v.trim().length < 10 ? 'الرجاء وصف المشكلة بما لا يقل عن ١٠ أحرف.' : ''),
  };

  function showError(field, message) {
    const input = document.querySelector(`[name="${field}"]`);
    const slot = document.querySelector(`[data-error-for="${field}"]`);
    if (input) input.classList.toggle('is-invalid', Boolean(message));
    if (slot) {
      slot.textContent = message || '';
      slot.hidden = !message;
    }
  }

  function validate(values) {
    let firstBad = null;
    for (const [field, rule] of Object.entries(RULES)) {
      const message = rule(values[field] || '');
      showError(field, message);
      if (message && !firstBad) firstBad = field;
    }
    return firstBad;
  }

  /* ------------------------------------------------------------- submit */

  function readForm() {
    return {
      citizen_name: document.getElementById('f-name').value,
      citizen_phone: document.getElementById('f-phone').value,
      citizen_email: document.getElementById('f-email').value,
      governorate: document.getElementById('f-gov').value,
      location_detail: document.getElementById('f-location').value,
      title: document.getElementById('f-title').value,
      description: document.getElementById('f-desc').value,
      type: document.getElementById('f-type').value,
      priority,
    };
  }

  async function send(event) {
    event.preventDefault();
    const values = readForm();

    const firstBad = validate(values);
    if (firstBad) {
      const input = document.querySelector(`[name="${firstBad}"]`);
      if (input) input.focus();
      toast('الرجاء تصحيح الحقول المؤشّرة.', true);
      return;
    }

    const button = document.getElementById('submit-btn');
    button.disabled = true;
    button.textContent = 'جارٍ الإرسال…';

    try {
      const payload = { ...values };
      if (!payload.citizen_email) delete payload.citizen_email;
      if (!payload.location_detail) delete payload.location_detail;
      const result = await API.create(payload, files);
      showReceipt(result);
      App.refreshDashboard();
    } catch (error) {
      // Surface server-side validation next to the offending field.
      const perField = API.fieldErrors(error);
      if (Object.keys(perField).length) {
        Object.entries(perField).forEach(([field, message]) => showError(field, message));
        toast('الرجاء تصحيح الحقول المؤشّرة.', true);
      } else {
        toast(error.message, true);
      }
    } finally {
      button.disabled = false;
      button.textContent = 'إرسال الشكوى';
    }
  }

  function showReceipt(result) {
    const complaint = result.complaint;
    document.getElementById('receipt-ref').textContent = complaint.reference_no;
    document.getElementById('receipt-type').textContent = App.typeLabel(complaint.type);
    document.getElementById('receipt-dept').textContent =
      complaint.department ? complaint.department.name_ar : '—';
    const dupes = document.getElementById('receipt-dupes');
    if (result.possible_duplicates.length) {
      const refs = result.possible_duplicates.map((d) => d.reference_no).join(' · ');
      dupes.textContent =
        `تنبيه: وردت شكوى مشابهة سابقاً بالرقم ${refs}. ستُراجع الدائرة الحالتين معاً.`;
      dupes.hidden = false;
    } else {
      dupes.hidden = true;
    }

    const form = document.getElementById('submit-form-wrap');
    const receipt = document.getElementById('receipt');
    form.hidden = true;
    receipt.hidden = false;
    window.scrollTo({ top: 0, behavior: 'smooth' });

    // The one genuine moment of achievement in the citizen flow, so the
    // receipt is allowed a little overshoot where nothing else in the form is.
    const paint = (t) => {
      receipt.style.transform =
        `translate3d(0, ${((1 - t) * 14).toFixed(2)}px, 0) scale(${Motion.lerp(0.98, 1, t).toFixed(4)})`;
      receipt.style.opacity = t.toFixed(3);
    };
    paint(0);
    Motion.spring({ from: 0, precision: 0.001, onUpdate: paint })
      .to(1, { preset: 'sheet' });
  }

  function reset() {
    document.getElementById('complaint-form').reset();
    files = [];
    renderFiles();
    setPriority('medium');
    document.getElementById('desc-count').textContent = ar(0);
    Object.keys(RULES).forEach((field) => showError(field, ''));
    document.getElementById('receipt').hidden = true;
    document.getElementById('submit-form-wrap').hidden = false;
  }

  /* Preselects the type when the citizen arrived by clicking a category card. */
  function preselect(type) {
    if (type) document.getElementById('f-type').value = type;
  }

  /* --------------------------------------------------------------- init */

  function init() {
    document.getElementById('complaint-form').addEventListener('submit', send);
    document.getElementById('receipt-again').addEventListener('click', reset);

    const description = document.getElementById('f-desc');
    description.addEventListener('input', () => {
      document.getElementById('desc-count').textContent = ar(description.value.length);
    });

    // Clear a field's error as soon as the citizen starts fixing it.
    Object.keys(RULES).forEach((field) => {
      const input = document.querySelector(`[name="${field}"]`);
      if (input) input.addEventListener('input', () => showError(field, ''));
    });

    const dropzone = document.getElementById('dropzone');
    const input = document.getElementById('file-input');
    dropzone.addEventListener('click', () => input.click());
    dropzone.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); }
    });
    input.addEventListener('change', () => { addFiles(input.files); input.value = ''; });

    ['dragenter', 'dragover'].forEach((type) =>
      dropzone.addEventListener(type, (e) => {
        e.preventDefault();
        dropzone.classList.add('is-over');
      }));
    ['dragleave', 'drop'].forEach((type) =>
      dropzone.addEventListener(type, (e) => {
        e.preventDefault();
        dropzone.classList.remove('is-over');
      }));
    dropzone.addEventListener('drop', (e) => addFiles(e.dataTransfer.files));
  }

  return { init, fillOptions, preselect, reset };
})();
