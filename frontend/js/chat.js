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

  /* A message that simply appears is easy to miss in a log you are already
     reading. A short rise draws the eye to the new line without animating the
     whole transcript. */
  function enter(node, distance = 8) {
    const paint = (t) => {
      node.style.transform = `translate3d(0, ${((1 - t) * distance).toFixed(2)}px, 0)`;
      node.style.opacity = t.toFixed(3);
    };
    paint(0);
    Motion.spring({ from: 0, precision: 0.001, onUpdate: paint }).to(1, { preset: 'ui' });
    return node;
  }

  function bubble(role, text, modifier = '') {
    const node = el('div', {
      class: `chat-msg is-${role}${modifier ? ` ${modifier}` : ''}`,
      text,
    });
    document.getElementById('chat-log').append(node);
    enter(node);
    scrollToEnd();
    return node;
  }

  function sourcesLine(sources) {
    if (!sources.length) return;
    const names = sources.slice(0, 3).map((s) => s.title).join(' · ');
    const node = el('div', { class: 'chat-sources', text: `المصدر: ${names}` });
    document.getElementById('chat-log').append(node);
    enter(node, 5);
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

  /* One spring drives the whole open/close. The panel scales out of the
     launcher — both are anchored to the same corner with the same
     transform-origin — while the launcher itself recedes, so it reads as one
     object becoming another rather than two things swapping places.

     Retargeting the spring rather than restarting it is what makes a rapid
     click-click-click follow the pointer instead of queueing: the reverse
     starts from wherever the panel currently is, at its current speed. */
  let openness = 0;

  const openSpring = Motion.spring({
    from: 0,
    precision: 0.001,
    onUpdate: (value) => { openness = value; paintPanel(); },
    onRest: () => {
      const { panel, launcher } = shell();
      panel.classList.remove('is-animating');
      launcher.classList.remove('is-animating');
      if (openness < 0.01) {
        panel.hidden = true;
        launcher.focus();
      }
    },
  });

  function shell() {
    return {
      panel: document.getElementById('chat-panel'),
      launcher: document.getElementById('chat-launcher'),
    };
  }

  function paintPanel() {
    const { panel, launcher } = shell();
    // Rises the last few pixels as it scales up, so it arrives rather than
    // simply inflating in place.
    const lift = (1 - openness) * 12;
    panel.style.transform =
      `translate3d(0, ${lift.toFixed(2)}px, 0) scale(${Motion.lerp(0.9, 1, openness).toFixed(4)})`;
    panel.style.opacity = openness.toFixed(3);

    launcher.style.transform = `scale(${Motion.lerp(1, 0.86, openness).toFixed(4)})`;
    launcher.style.opacity = (1 - openness).toFixed(3);
    // Stops the fading launcher swallowing clicks meant for the open panel.
    launcher.style.pointerEvents = openness > 0.5 ? 'none' : '';
  }

  function open() {
    const { panel, launcher } = shell();
    panel.hidden = false;
    panel.classList.add('is-animating');
    launcher.classList.add('is-animating');
    launcher.setAttribute('aria-expanded', 'true');

    if (!opened) {
      opened = true;
      bubble('bot', GREETING);
      renderSuggestions();
    }
    paintPanel();
    // Clicked open, so no momentum to express: settle without overshoot.
    openSpring.to(1, { preset: 'ui' });
    document.getElementById('chat-input').focus();
  }

  function close() {
    const { panel, launcher } = shell();
    if (panel.hidden) return;
    panel.classList.add('is-animating');
    launcher.classList.add('is-animating');
    launcher.setAttribute('aria-expanded', 'false');
    // Leaves the way it came: back down into the launcher.
    openSpring.to(0, { preset: 'ui' });
  }

  function toggle() {
    // Reads the spring, not the `hidden` flag: mid-close the panel is still
    // visible, and a click then should reverse it rather than do nothing.
    if (openSpring.target >= 0.5) close();
    else open();
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
