// mkdocs-review UI: page list, two synced panes, hunk navigation, comments.
(() => {
  const $ = (sel) => document.querySelector(sel);
  const frames = { base: $('#frame-base'), head: $('#frame-head') };
  const other = { base: 'head', head: 'base' };

  const app = {
    state: null,
    drafts: [],
    anchors: new Map(), // draft id -> anchor or null
    page: null, // current page summary
    hunk: -1, // index into page.hunks
    pendingHunk: null, // hunk to show once both panes load
    loaded: { base: false, head: false },
    composing: null,
    focusedDraft: null,
  };

  const api = async (method, path, body) => {
    const res = await fetch(path, {
      method,
      headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `${res.status}`);
    return data;
  };

  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
  const short = (sha) => sha.slice(0, 10);
  const byPath = (path) => app.state.pages.find((p) => p.path === path);
  const changedPages = () => app.state.pages.filter((p) => p.status !== 'unchanged');
  const send = (side, msg) => frames[side].contentWindow && frames[side].contentWindow.postMessage(msg, location.origin);

  // ---- page list -------------------------------------------------------
  const BADGE = { added: 'A', removed: 'D', modified: 'M', unchanged: '·' };

  const renderPages = () => {
    const showAll = $('#show-all').checked;
    const pages = showAll ? app.state.pages : changedPages();
    $('#pages-heading').textContent = showAll ? `All pages (${pages.length})` : `Changed pages (${pages.length})`;
    const draftsPer = new Map();
    app.drafts.forEach((d) => draftsPer.set(d.page, (draftsPer.get(d.page) || 0) + 1));
    $('#pages').innerHTML = pages.map((p) => {
      const c = p.counts;
      const stats = [
        c.added ? `<span class="a">+${c.added}</span>` : '',
        c.removed ? `<span class="r">−${c.removed}</span>` : '',
        c.changed ? `<span class="c">~${c.changed}</span>` : '',
        draftsPer.get(p.path) ? `<span class="drafts-dot">💬${draftsPer.get(p.path)}</span>` : '',
      ].join(' ');
      return `<li data-path="${esc(p.path)}" class="${app.page && app.page.path === p.path ? 'active' : ''}">
        <span class="badge ${p.status}" title="${p.status}">${BADGE[p.status]}</span>
        <span class="title" title="${esc(p.title)}">${esc(p.title)}</span>
        <span class="stats">${stats}</span>
        <span class="path">${esc(p.source || p.path)}</span>
      </li>`;
    }).join('') || '<li class="muted">No rendered changes.</li>';
  };

  $('#pages').addEventListener('click', (e) => {
    const li = e.target.closest('li[data-path]');
    if (li) openPage(li.dataset.path, { hunk: 0 });
  });
  $('#show-all').addEventListener('change', renderPages);

  // ---- panes -------------------------------------------------------------
  const openPage = (path, { hunk = null, hash = '' } = {}) => {
    const page = byPath(path);
    if (!page) return;
    if (app.page && app.page.path === path) {
      if (hunk !== null) gotoHunk(hunk);
      return;
    }
    app.page = page;
    app.hunk = -1;
    app.pendingHunk = hunk !== null && page.hunks.length ? hunk : null;
    app.loaded = { base: false, head: false };
    for (const side of ['base', 'head']) frames[side].src = `/site/${side}/${path}${hash}`;
    history.replaceState(null, '', `#${path}`);
    renderPages();
    updateHunkPos();
  };

  const updateHunkPos = () => {
    const n = app.page ? app.page.hunks.length : 0;
    $('#hunk-pos').textContent = n ? `change ${Math.max(app.hunk + 1, 0)}/${n}` : 'no changes';
  };

  const gotoHunk = (i, smooth = false) => {
    const hunks = app.page.hunks;
    if (!hunks.length) return;
    app.hunk = Math.max(0, Math.min(i, hunks.length - 1));
    const h = hunks[app.hunk];
    send('base', { type: 'goto', block: h.base, hunk: h.id, smooth });
    send('head', { type: 'goto', block: h.head, hunk: h.id, smooth });
    updateHunkPos();
  };

  // Move through changes, continuing onto the next/previous changed page.
  const step = (dir) => {
    if (!app.page) return;
    const hunks = app.page.hunks;
    const next = app.hunk + dir;
    if (next >= 0 && next < hunks.length) return gotoHunk(next, true);
    const pages = changedPages();
    const idx = pages.findIndex((p) => p.path === app.page.path);
    const target = pages[idx + dir];
    if (!target) return;
    openPage(target.path, { hunk: dir > 0 ? 0 : Math.max(target.hunks.length - 1, 0) });
  };
  $('#next').addEventListener('click', () => step(1));
  $('#prev').addEventListener('click', () => step(-1));

  const onKey = (key) => {
    if ($('#composer').open) return;
    if (key === 'j') step(1);
    else if (key === 'k') step(-1);
    else if (key === 'n' || key === 'p') {
      const pages = changedPages();
      const idx = pages.findIndex((p) => app.page && p.path === app.page.path);
      const target = pages[idx + (key === 'n' ? 1 : -1)];
      if (target) openPage(target.path, { hunk: 0 });
    }
  };
  document.addEventListener('keydown', (e) => {
    const t = e.target;
    if (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) || e.metaKey || e.ctrlKey || e.altKey) return;
    if ('jknp'.includes(e.key)) { e.preventDefault(); onKey(e.key); }
  });

  // ---- messages from the panes ----------------------------------------------
  window.addEventListener('message', (e) => {
    if (e.origin !== location.origin) return;
    const side = Object.keys(frames).find((s) => frames[s].contentWindow === e.source);
    if (!side) return;
    const msg = e.data || {};
    switch (msg.type) {
      case 'ready':
        app.loaded[side] = true;
        pushDraftMarkers(side);
        if (app.pendingHunk !== null && app.loaded.base && app.loaded.head) {
          const h = app.pendingHunk;
          app.pendingHunk = null;
          gotoHunk(h);
        }
        break;
      case 'scroll':
        if ($('#sync').checked) send(other[side], { type: 'scrollTo', pair: msg.pair, offset: msg.offset, atTop: msg.atTop });
        break;
      case 'comment':
        openComposer({ page: app.page.path, side, block: msg.block, quote: msg.quote });
        break;
      case 'navigate':
        if (byPath(msg.path)) openPage(msg.path, { hash: msg.hash });
        break;
      case 'key':
        onKey(msg.key);
        break;
      case 'openDraft':
        openDrawer();
        focusDraft(msg.id);
        break;
    }
  });

  // ---- drafts ----------------------------------------------------------------
  const pushDraftMarkers = (side) => {
    if (!app.page) return;
    const items = app.drafts
      .filter((d) => d.page === app.page.path && d.side === side)
      .map((d) => ({ id: d.id, block: d.block }));
    send(side, { type: 'drafts', items });
  };

  let anchorTimer = null;
  const refreshAnchors = () => {
    clearTimeout(anchorTimer);
    anchorTimer = setTimeout(async () => {
      if (!app.drafts.length) return;
      try {
        const result = await api('POST', '/api/anchors', app.drafts);
        result.forEach((r) => app.anchors.set(r.id, r.anchor));
        renderDrafts();
      } catch (err) {
        console.error('anchor preview failed', err);
      }
    }, 150);
  };

  const saveDrafts = async () => {
    await api('PUT', '/api/drafts', app.drafts);
    $('#draft-count').textContent = app.drafts.length;
    renderDrafts();
    renderPages();
    pushDraftMarkers('base');
    pushDraftMarkers('head');
    refreshAnchors();
  };

  const anchorText = (d) => {
    if (!app.anchors.has(d.id)) return '<div class="anchor muted">locating source line…</div>';
    const a = app.anchors.get(d.id);
    if (!a) return '<div class="anchor loose" title="No matching line in the diff">→ review body (no matching diff line)</div>';
    return `<div class="anchor muted">→ ${esc(a.path)}:${a.line}${a.side === 'LEFT' ? ' (old)' : ''}</div>`;
  };

  const renderDrafts = () => {
    const pageTitle = (path) => (byPath(path) || { title: path }).title;
    $('#draft-list').innerHTML = app.drafts.map((d) => `
      <li data-id="${esc(d.id)}" class="${app.focusedDraft === d.id ? 'focused' : ''}">
        <div class="where"><span>${esc(pageTitle(d.page))}</span><span>${d.side}</span></div>
        <blockquote>${esc(d.quote || '')}</blockquote>
        <div class="body">${esc(d.body)}</div>
        ${anchorText(d)}
        <div class="actions"><button data-act="edit">Edit</button><button data-act="delete">Delete</button></div>
      </li>`).join('') || '<li class="muted">No comments yet.</li>';
  };

  const focusDraft = (id) => {
    app.focusedDraft = id;
    renderDrafts();
    const li = $(`#draft-list li[data-id="${CSS.escape(id)}"]`);
    if (li) li.scrollIntoView({ block: 'nearest' });
  };

  $('#draft-list').addEventListener('click', async (e) => {
    const li = e.target.closest('li[data-id]');
    if (!li) return;
    const draft = app.drafts.find((d) => d.id === li.dataset.id);
    const act = e.target.dataset.act;
    if (act === 'delete') {
      app.drafts = app.drafts.filter((d) => d !== draft);
      await saveDrafts();
    } else if (act === 'edit') {
      openComposer(draft);
    } else {
      focusDraft(draft.id);
      const page = byPath(draft.page);
      const show = () => send(draft.side, { type: 'goto', block: draft.block, smooth: true });
      if (app.page && app.page.path === draft.page) show();
      else if (page) {
        openPage(draft.page);
        const wait = setInterval(() => { if (app.loaded[draft.side]) { clearInterval(wait); show(); } }, 100);
        setTimeout(() => clearInterval(wait), 5000);
      }
    }
  });

  // ---- composer --------------------------------------------------------------
  const composer = $('#composer');
  const openComposer = (draft) => {
    app.composing = draft;
    $('#composer-where').textContent = `${byPath(draft.page).title} · ${draft.side}`;
    $('#composer-quote').textContent = draft.quote || '';
    $('#composer-body').value = draft.body || '';
    composer.showModal();
    $('#composer-body').focus();
  };
  $('#composer-body').addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); composer.close('save'); }
  });
  composer.addEventListener('close', async () => {
    const draft = app.composing;
    app.composing = null;
    const body = $('#composer-body').value.trim();
    if (composer.returnValue !== 'save' || !draft || !body) return;
    if (draft.id) {
      draft.body = body;
    } else {
      app.drafts.push({ ...draft, id: `d${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`, body, created: new Date().toISOString() });
    }
    openDrawer();
    await saveDrafts();
  });

  // ---- drawer & submit ---------------------------------------------------------
  const openDrawer = () => $('#layout').classList.add('drawer-open');
  $('#drawer-toggle').addEventListener('click', () => $('#layout').classList.toggle('drawer-open'));
  $('#drawer-close').addEventListener('click', () => $('#layout').classList.remove('drawer-open'));

  let confirmTimer = null;
  const submitButton = $('#submit');
  const status = $('#submit-status');
  submitButton.addEventListener('click', async () => {
    if (!submitButton.dataset.confirm) {
      const anchored = app.drafts.filter((d) => app.anchors.get(d.id)).length;
      submitButton.dataset.confirm = '1';
      submitButton.textContent = `Post ${app.drafts.length} comment(s) to PR #${app.state.pr.number}?`;
      status.className = 'muted';
      status.textContent = `${anchored} on diff lines, ${app.drafts.length - anchored} in the review body. Click again to confirm.`;
      clearTimeout(confirmTimer);
      confirmTimer = setTimeout(resetSubmit, 6000);
      return;
    }
    clearTimeout(confirmTimer);
    submitButton.disabled = true;
    status.textContent = 'Submitting…';
    try {
      const res = await api('POST', '/api/submit', { summary: $('#summary').value });
      app.drafts = [];
      app.anchors.clear();
      $('#summary').value = '';
      await saveDrafts();
      status.className = 'muted';
      status.innerHTML = res.url ? `Review posted. <a href="${esc(res.url)}" target="_blank" rel="noopener">Open on GitHub</a>` : 'Review posted.';
    } catch (err) {
      status.className = 'error';
      status.textContent = `Submit failed: ${err.message}`;
    } finally {
      resetSubmit();
    }
  });
  const resetSubmit = () => {
    delete submitButton.dataset.confirm;
    submitButton.textContent = 'Submit review';
    submitButton.disabled = !app.state.can_submit;
  };

  // ---- boot ----------------------------------------------------------------------
  const boot = async () => {
    const [state, drafts] = await Promise.all([api('GET', '/api/state'), api('GET', '/api/drafts')]);
    app.state = state;
    app.drafts = drafts;
    const link = $('#target-link');
    link.textContent = state.label;
    if (state.pr) link.href = state.pr.url; else link.removeAttribute('href');
    document.title = `${state.label} · mkdocs-review`;
    $('#base-sha').textContent = short(state.base);
    $('#head-sha').textContent = short(state.head);
    $('#draft-count').textContent = drafts.length;
    resetSubmit();
    if (!state.can_submit) status.textContent = 'Comments stay local: submitting needs a pull request and the gh CLI.';
    renderPages();
    renderDrafts();
    refreshAnchors();
    if (drafts.length) openDrawer();
    const fromHash = decodeURIComponent(location.hash.slice(1));
    const first = byPath(fromHash) || changedPages()[0] || state.pages[0];
    if (first) openPage(first.path, { hunk: 0 });
  };
  boot().catch((err) => {
    document.body.innerHTML = `<p style="padding:16px">Failed to load the review: ${esc(err.message)}</p>`;
  });
})();
