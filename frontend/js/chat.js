/* The citizen assistant: a small chat panel over the knowledge base.

   The launcher only appears once the backend confirms the assistant is
   actually reachable. Offering a chat button that then apologises is worse
   than not offering one, so availability is checked before anything is shown. */

const Chat = (() => {
  const { el, clear } = Fmt;

  // Sent back with each question so follow-ups keep their thread. Trimmed
  // hard — the model has a small context window and the retrieved passages
  // matter more than old turns.
  const MAX_HISTORY = 8;

  const GREETING =
    'مرحباً بك. أنا المساعد الذكي لمنصة الشكاوى، أجيب عن أسئلتك حول تقديم '
    + 'الشكوى ومتابعتها من دليل المنصة الرسمي. كيف يمكنني مساعدتك؟';

  const SUGGESTIONS = [
    'كيف أقدّم شكوى؟',
    'كم تستغرق معالجة الشكوى؟',
    'كيف أتتبع شكواي؟',
    'كيف تُحدَّد الأولوية؟',
  ];

  let history = [];
  let busy = false;
  let opened = false;

  /* ------------------------------------------------------------ rendering */

  function bubble(role, text, modifier = '') {
    const node = el('div', {
      class: `chat-msg is-${role}${modifier ? ` ${modifier}` : ''}`,
      text,
    });
    document.getElementById('chat-log').append(node);
    scrollToEnd();
    return node;
  }

  function sourcesLine(sources) {
    if (!sources.length) return;
    const names = sources.slice(0, 3).map((s) => s.title).join(' · ');
    document.getElementById('chat-log').append(
      el('div', { class: 'chat-sources', text: `المصدر: ${names}` }));
    scrollToEnd();
  }

  function typingIndicator() {
    const node = el('div', { class: 'chat-typing' }, [
      el('span'), el('span'), el('span'),
    ]);
    document.getElementById('chat-log').append(node);
    scrollToEnd();
    return node;
  }

  function scrollToEnd() {
    const log = document.getElementById('chat-log');
    log.scrollTop = log.scrollHeight;
  }

  function renderSuggestions() {
    const host = clear(document.getElementById('chat-suggestions'));
    // Only offered at the start; once a conversation is going they are noise.
    if (history.length) return;
    SUGGESTIONS.forEach((question) =>
      host.append(el('button', {
        type: 'button',
        class: 'chat-suggestion',
        text: question,
        onclick: () => ask(question),
      })));
  }

  /* --------------------------------------------------------------- asking */

  async function ask(question) {
    question = (question || '').trim();
    if (!question || busy) return;

    busy = true;
    const input = document.getElementById('chat-input');
    const send = document.getElementById('chat-send');
    input.value = '';
    send.disabled = true;

    bubble('user', question);
    history.push({ role: 'user', content: question });
    renderSuggestions();
    const typing = typingIndicator();

    try {
      const reply = await API.chat(question, history.slice(0, -1).slice(-MAX_HISTORY));
      typing.remove();
      bubble('bot', reply.answer);
      if (reply.grounded) sourcesLine(reply.sources || []);
      history.push({ role: 'assistant', content: reply.answer });
      // Keep the thread bounded; the server trims again on its side.
      if (history.length > MAX_HISTORY * 2) {
        history = history.slice(-MAX_HISTORY * 2);
      }
    } catch (error) {
      typing.remove();
      bubble('bot', `تعذّر الوصول إلى المساعد. ${error.message}`, 'is-error');
    } finally {
      busy = false;
      send.disabled = false;
      input.focus();
    }
  }

  /* ------------------------------------------------------------ open/close */

  function open() {
    const panel = document.getElementById('chat-panel');
    panel.hidden = false;
    document.getElementById('chat-launcher').setAttribute('aria-expanded', 'true');
    if (!opened) {
      opened = true;
      bubble('bot', GREETING);
      renderSuggestions();
    }
    document.getElementById('chat-input').focus();
  }

  function close() {
    document.getElementById('chat-panel').hidden = true;
    const launcher = document.getElementById('chat-launcher');
    launcher.setAttribute('aria-expanded', 'false');
    launcher.focus();
  }

  function toggle() {
    if (document.getElementById('chat-panel').hidden) open();
    else close();
  }

  /* ----------------------------------------------------------------- init */

  async function init() {
    document.getElementById('chat-launcher').addEventListener('click', toggle);
    document.getElementById('chat-close').addEventListener('click', close);
    document.getElementById('chat-form').addEventListener('submit', (event) => {
      event.preventDefault();
      ask(document.getElementById('chat-input').value);
    });
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && !document.getElementById('chat-panel').hidden) {
        close();
      }
    });

    // Show the launcher only when the assistant can actually answer.
    try {
      const health = await API.aiHealth();
      if (health.enabled && health.available && health.indexed_chunks > 0) {
        document.getElementById('chat-launcher').hidden = false;
      }
    } catch {
      // Backend unreachable or the route is absent — leave the launcher hidden.
    }
  }

  return { init, ask, open, close };
})();
