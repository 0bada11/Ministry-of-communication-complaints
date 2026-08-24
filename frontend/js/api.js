/* Thin wrapper over the FastAPI backend. Every network call goes through here. */

const API = (() => {
  // Same origin when served by FastAPI; falls back to the dev port otherwise.
  const BASE = location.port === '5500' || location.protocol === 'file:'
    ? 'http://127.0.0.1:8000'
    : '';

  async function request(path, options = {}) {
    const response = await fetch(BASE + path, options);
    if (response.status === 204) return null;

    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      throw Object.assign(new Error(errorMessage(payload, response.status)), {
        status: response.status,
        detail: payload && payload.detail,
      });
    }
    return payload;
  }

  /* FastAPI reports validation failures as a list of per-field problems and
     everything else as a plain string, so unpack both shapes here. */
  function errorMessage(payload, status) {
    const detail = payload && payload.detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail) && detail.length) {
      return detail.map((d) => d.msg).join(' · ');
    }
    return `تعذّر إتمام الطلب (${status})`;
  }

  /* Turns FastAPI's 422 body into { field: message } for inline form errors. */
  function fieldErrors(error) {
    if (!Array.isArray(error.detail)) return {};
    const out = {};
    for (const item of error.detail) {
      const field = (item.loc || []).filter((p) => p !== 'body').join('.');
      if (field) out[field] = item.msg;
    }
    return out;
  }

  function query(params) {
    const search = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value === null || value === undefined || value === '') continue;
      if (Array.isArray(value)) value.forEach((v) => search.append(key, v));
      else search.append(key, value);
    }
    const string = search.toString();
    return string ? `?${string}` : '';
  }

  return {
    base: BASE,
    fieldErrors,
    meta: () => request('/api/meta'),
    stats: (days = 14) => request(`/api/stats?days=${days}`),
    list: (params) => request(`/api/complaints${query(params)}`),
    get: (id) => request(`/api/complaints/${id}`),
    track: (reference) => request(`/api/track/${encodeURIComponent(reference)}`),
    csvUrl: (params) => `${BASE}/api/complaints.csv${query(params)}`,
    aiHealth: () => request('/api/ai/health'),
    chat: (message, history = []) => request('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, history }),
    }),

    create: (body, files) => {
      // Attachments force multipart; without them JSON keeps validation richer.
      if (!files || !files.length) {
        return request('/api/complaints', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
      }
      const form = new FormData();
      for (const [key, value] of Object.entries(body)) {
        if (value !== null && value !== undefined && value !== '') form.append(key, value);
      }
      files.forEach((file) => form.append('files', file));
      return request('/api/complaints/upload', { method: 'POST', body: form });
    },

    update: (id, body) => request(`/api/complaints/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  };
})();
