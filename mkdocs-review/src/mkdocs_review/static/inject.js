// Injected into every page of both sites. Talks to the review UI (the parent
// window) with postMessage; it never changes the page beyond overlays.
(() => {
  const script = document.currentScript || document.querySelector('script[data-side]');
  const side = script.dataset.side;
  const origin = location.origin;
  const post = (msg) => window.parent.postMessage({ ...msg, side }, origin);

  let suppressUntil = 0;
  const suppress = (ms = 200) => { suppressUntil = Date.now() + ms; };

  const blockEl = (i) => document.querySelector(`[data-mr-block="${i}"]`);

  // Overlay layer for the "+" button and draft badges, in page coordinates.
  const overlay = document.createElement('div');
  overlay.className = 'mr-overlay';
  const plus = document.createElement('div');
  plus.className = 'mr-plus';
  plus.textContent = '+';
  plus.title = 'Comment on this block';
  overlay.appendChild(plus);

  const ready = () => {
    document.body.appendChild(overlay);
    post({ type: 'ready', title: document.title });
  };

  const pageRect = (el) => {
    const r = el.getBoundingClientRect();
    return { top: r.top + window.scrollY, left: r.left + window.scrollX, width: r.width, height: r.height };
  };

  let hovered = null;
  document.addEventListener('mouseover', (e) => {
    if (e.target === plus) return;
    const block = e.target.closest && e.target.closest('[data-mr-block]');
    if (!block || block === hovered) return;
    hovered = block;
    const r = pageRect(block);
    plus.style.top = `${r.top}px`;
    plus.style.left = `${Math.max(2, r.left - 28)}px`;
    plus.classList.add('visible');
  });
  plus.addEventListener('click', (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (!hovered) return;
    const copy = hovered.cloneNode(true);
    copy.querySelectorAll('.headerlink, [data-mr-block]').forEach((el) => el.remove());
    post({
      type: 'comment',
      block: Number(hovered.dataset.mrBlock),
      quote: copy.textContent.replace(/\s+/g, ' ').trim().slice(0, 400),
    });
  });

  // Scroll sync: report the first visible paired block and its offset.
  let ticking = false;
  window.addEventListener('scroll', () => {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(() => {
      ticking = false;
      if (Date.now() < suppressUntil) return;
      const paired = document.querySelectorAll('[data-mr-pair]');
      for (const el of paired) {
        const r = el.getBoundingClientRect();
        if (r.bottom > 0) {
          post({ type: 'scroll', pair: el.dataset.mrPair, offset: r.top, atTop: window.scrollY === 0 });
          return;
        }
      }
    });
  }, { passive: true });

  let badges = [];
  const renderDrafts = (items) => {
    badges.forEach((b) => b.remove());
    badges = [];
    const byBlock = new Map();
    for (const item of items) {
      if (!byBlock.has(item.block)) byBlock.set(item.block, []);
      byBlock.get(item.block).push(item.id);
    }
    for (const [block, ids] of byBlock) {
      const el = blockEl(block);
      if (!el) continue;
      const r = pageRect(el);
      const badge = document.createElement('div');
      badge.className = 'mr-badge';
      badge.textContent = `💬 ${ids.length}`;
      badge.style.top = `${r.top - 10}px`;
      badge.style.left = `${r.left + r.width - 40}px`;
      badge.addEventListener('click', () => post({ type: 'openDraft', id: ids[0] }));
      overlay.appendChild(badge);
      badges.push(badge);
    }
  };
  let lastDrafts = [];
  window.addEventListener('resize', () => renderDrafts(lastDrafts));

  window.addEventListener('message', (e) => {
    if (e.origin !== origin || e.source !== window.parent) return;
    const msg = e.data || {};
    if (msg.type === 'scrollTo') {
      if (msg.atTop) { suppress(); window.scrollTo(0, 0); return; }
      const el = document.querySelector(`[data-mr-pair="${msg.pair}"]`);
      if (!el) return;
      suppress();
      window.scrollBy(0, el.getBoundingClientRect().top - msg.offset);
    } else if (msg.type === 'goto') {
      document.querySelectorAll('.mr-current').forEach((el) => el.classList.remove('mr-current'));
      const group = msg.hunk == null ? [] : document.querySelectorAll(`[data-mr-hunk="${msg.hunk}"]`);
      group.forEach((el) => el.classList.add('mr-current'));
      const target = msg.block == null ? null : blockEl(msg.block);
      if (!target) return;
      suppress(600);
      target.scrollIntoView({ block: 'center', behavior: msg.smooth ? 'smooth' : 'auto' });
      if (!group.length) {
        target.classList.add('mr-flash');
        setTimeout(() => target.classList.remove('mr-flash'), 1200);
      }
    } else if (msg.type === 'drafts') {
      lastDrafts = msg.items || [];
      renderDrafts(lastDrafts);
    }
  });

  // Keep navigation inside the review: links switch both panes to the page.
  document.addEventListener('click', (e) => {
    const a = e.target.closest && e.target.closest('a[href]');
    if (!a || e.defaultPrevented || e.metaKey || e.ctrlKey || e.shiftKey) return;
    const url = new URL(a.getAttribute('href'), location.href);
    if (url.origin !== origin) {
      a.target = '_blank';
      a.rel = 'noopener';
      return;
    }
    if (url.pathname === location.pathname) return; // in-page anchor
    e.preventDefault();
    let path = url.pathname.replace(/^\/site\/(base|head)\//, '').replace(/^\//, '');
    if (path === '' || path.endsWith('/')) path += 'index.html';
    post({ type: 'navigate', path, hash: url.hash });
  }, true);

  document.addEventListener('keydown', (e) => {
    const t = e.target;
    if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if ('jknp'.includes(e.key)) {
      e.preventDefault();
      post({ type: 'key', key: e.key });
    }
  });

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ready);
  else ready();
})();
