const toast = document.getElementById('toast');
let toastTimer;
function say(msg, isErr) {
  toast.textContent = msg;
  toast.className = isErr ? 'err' : '';
  toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (toast.hidden = true), isErr ? 8000 : 3500);
}

async function post(url) {
  const r = await fetch(url, { method: 'POST' });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.error || body.detail || r.statusText);
  return body;
}

document.addEventListener('click', async (e) => {
  const btn = e.target.closest('button');
  if (!btn) return;
  try {
    if (btn.dataset.display) {
      btn.disabled = true;
      say('Sending to TV… (large images can take a minute)');
      const crop = btn.dataset.crop || (window.getCrop && window.getCrop());
      await post('/api/display/' + btn.dataset.display + (crop ? '?crop=' + crop : ''));
      say('Now showing on the TV ✓');
    } else if (btn.dataset.fav) {
      const { favorite } = await post('/api/favorite/' + btn.dataset.fav);
      if (!btn.closest('.card')) btn.textContent = favorite ? '★ Favorited' : '☆ Favorite';
      say(favorite ? 'Added to favorites' : 'Removed from favorites');
    } else if (btn.id === 'pair') {
      btn.disabled = true;
      say('Contacting TV — press Allow on the TV if prompted…');
      await post('/api/pair');
      say('Paired ✓');
      setTimeout(() => location.reload(), 800);
    }
  } catch (err) {
    say(err.message, true);
  } finally {
    if (btn.dataset.display || btn.id === 'pair') btn.disabled = false;
  }
});

// Framing editor on the detail page. The artwork sits in the frame's opening and is dragged/zoomed
// behind the frame overlay. Same math as imaging.prepare_for_tv: (cx, cy) = image point at the
// opening's center, zoom relative to "cover" (1 fills the opening; below 1 shows the whole image).
(function () {
  const stage = document.getElementById('stage');
  if (!stage) return;
  const frames = JSON.parse(document.getElementById('frames-data').textContent);
  const art = document.getElementById('art');
  const aperture = document.getElementById('aperture');
  const overlay = document.getElementById('frame-overlay');
  const zoomEl = document.getElementById('zoom');
  const chips = [...document.querySelectorAll('.chip')];
  const MAX_ZOOM = 8, PAD = 2; // PAD: clip the art 2px past the opening so it tucks under the frame edge

  let frame = 'none', cx = 0.5, cy = 0.5, zoom = null; // zoom null = fit whole image
  const init = (stage.dataset.initial || '').split(',');
  if (init.length === 4 && frames[init[0]]) {
    frame = init[0]; cx = +init[1]; cy = +init[2]; zoom = init[3] === 'fit' ? null : +init[3];
  }

  function geom() {
    const W = stage.clientWidth, H = W * 9 / 16;
    const [a0, b0, a1, b1] = frames[frame].ap;
    const aw = (a1 - a0) * W, ah = (b1 - b0) * H;
    const r = art.naturalWidth / art.naturalHeight; // image width, in units of its height
    const cover = Math.max(aw / r, ah), fit = Math.min(aw / r, ah);
    return { ax: a0 * W, ay: b0 * H, aw, ah, r, cover, zfit: fit / cover };
  }
  const axis = (c, view, size) => {
    const half = view / 2 / size;
    return Math.min(Math.max(c, Math.min(half, 1 - half)), Math.max(half, 1 - half));
  };
  const curZoom = (g) => Math.min(Math.max(zoom ?? g.zfit, g.zfit), MAX_ZOOM);

  function layout() {
    if (!art.naturalWidth) return;
    const g = geom();
    const z = curZoom(g), s = g.cover * z, iw = g.r * s, ih = s;
    cx = axis(cx, g.aw, iw); cy = axis(cy, g.ah, ih);
    Object.assign(aperture.style, {
      left: g.ax - PAD + 'px', top: g.ay - PAD + 'px', width: g.aw + 2 * PAD + 'px', height: g.ah + 2 * PAD + 'px',
    });
    Object.assign(art.style, {
      width: iw + 'px', height: ih + 'px',
      left: g.aw / 2 - cx * iw + PAD + 'px', top: g.ah / 2 - cy * ih + PAD + 'px',
    });
    zoomEl.value = g.zfit >= MAX_ZOOM ? 0 : Math.round(1000 * Math.log(z / g.zfit) / Math.log(MAX_ZOOM / g.zfit));
  }

  function setFrame(id) {
    frame = id;
    overlay.src = '/frames/' + id + '.png?w=1920';
    chips.forEach((c) => c.classList.toggle('on', c.dataset.frame === id));
    layout();
  }
  chips.forEach((c) => c.addEventListener('click', () => setFrame(c.dataset.frame)));

  zoomEl.addEventListener('input', () => {
    const g = geom();
    zoom = g.zfit * Math.pow(MAX_ZOOM / g.zfit, zoomEl.value / 1000);
    layout();
  });
  document.getElementById('zoom-fit').addEventListener('click', () => { zoom = null; cx = cy = 0.5; layout(); });
  document.getElementById('zoom-fill').addEventListener('click', () => { zoom = 1; cx = cy = 0.5; layout(); });

  stage.addEventListener('wheel', (e) => {
    e.preventDefault();
    zoom = curZoom(geom()) * Math.exp(-e.deltaY * 0.0015);
    layout();
  }, { passive: false });

  let drag = null;
  stage.addEventListener('pointerdown', (e) => { drag = { x: e.clientX, y: e.clientY, cx, cy }; stage.setPointerCapture(e.pointerId); });
  stage.addEventListener('pointermove', (e) => {
    if (!drag) return;
    const g = geom(), s = g.cover * curZoom(g);
    cx = drag.cx - (e.clientX - drag.x) / (g.r * s);
    cy = drag.cy - (e.clientY - drag.y) / s;
    layout();
  });
  stage.addEventListener('pointerup', () => (drag = null));
  stage.addEventListener('pointercancel', () => (drag = null));
  new ResizeObserver(layout).observe(stage);
  art.addEventListener('load', layout);

  // For the Display button: "frame,cx,cy,zoom", or null for the default (whole image, no frame).
  window.getCrop = () => {
    const g = geom();
    if (frame === 'none' && zoom === null && Math.abs(cx - 0.5) < 1e-3 && Math.abs(cy - 0.5) < 1e-3) return null;
    return [frame, cx.toFixed(4), cy.toFixed(4), zoom === null ? 'fit' : curZoom(g).toFixed(4)].join(',');
  };

  setFrame(frame);
})();

// Infinite scroll on the browse page, with off-screen thumbnails unloaded to keep memory flat.
(function () {
  const sentinel = document.getElementById('sentinel');
  const grid = document.querySelector('.grid');
  if (!sentinel || !grid) return;

  // 1x1 transparent GIF: keeps the <img> (and its aspect-ratio box) while freeing the decoded bitmap.
  const BLANK = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7';
  const unloader = new IntersectionObserver((entries) => {
    for (const e of entries) {
      const img = e.target.querySelector('img');
      if (!img || !img.dataset.src) continue;
      if (e.isIntersecting) {
        if (img.src !== img.dataset.src) img.src = img.dataset.src;
      } else if (img.complete) {
        img.src = BLANK;
      }
    }
  }, { rootMargin: '2500px 0px' }); // keep ~2.5 screens each way loaded

  // Cards arrive as placeholders (just an id); details are looked up only for cards near the viewport,
  // a few at a time, so scrolling past results costs the museum's API nothing.
  const queue = [];
  let active = 0;
  const hydrator = new IntersectionObserver((entries) => {
    for (const e of entries) {
      const i = queue.indexOf(e.target);
      if (e.isIntersecting && i < 0) queue.push(e.target);
      else if (!e.isIntersecting && i >= 0) queue.splice(i, 1); // scrolled past before its turn
    }
    pump();
  }, { rootMargin: '600px 0px' });

  function pump() {
    while (active < 4 && queue.length) {
      const card = queue.shift();
      hydrator.unobserve(card);
      active++;
      hydrate(card).finally(() => { active--; pump(); });
    }
  }
  async function hydrate(card, attempt = 0) {
    try {
      const r = await fetch('/card/' + card.dataset.source + '/' + card.dataset.id);
      if (r.status === 404) { card.remove(); return; } // not Open Access / no image
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const d = await r.json();
      const img = card.querySelector('img');
      card.querySelector('strong').textContent = (d.fav ? '★ ' : '') + d.title;
      card.querySelector('span').textContent = d.artist;
      img.alt = d.title;
      img.dataset.src = '/img/' + card.dataset.source + '/' + card.dataset.id;
      img.src = img.dataset.src;
      card.classList.remove('pending', 'failed');
    } catch (err) {
      if (attempt < 2) { // back off: the museum may be throttling
        await new Promise((res) => setTimeout(res, 3000 * (attempt + 1)));
        return hydrate(card, attempt + 1);
      }
      card.classList.add('failed');
    }
  }

  function adopt(root) {
    root.querySelectorAll('.card').forEach((c) => {
      unloader.observe(c);
      if (c.classList.contains('pending')) hydrator.observe(c);
    });
  }
  adopt(grid);

  let next = +sentinel.dataset.next;
  let loading = false;
  let done = sentinel.hidden;
  const base = new URLSearchParams(sentinel.dataset.qs);
  base.set('partial', 1);
  const key = 'artbuff:' + location.search;

  async function loadMore() {
    if (loading || done) return false;
    loading = true;
    try {
      const r = await fetch('/?' + base + '&page=' + next);
      if (!r.ok) throw new Error('Load failed (' + r.status + ')');
      const html = (await r.text()).trim();
      if (!html) { done = true; sentinel.hidden = true; return false; }
      const tpl = document.createElement('template');
      tpl.innerHTML = html;
      const frag = tpl.content;
      const added = [...frag.querySelectorAll('.card')];
      grid.appendChild(frag);
      added.forEach((c) => { unloader.observe(c); if (c.classList.contains('pending')) hydrator.observe(c); });
      next++;
      sentinel.textContent = 'Loading more…';
      return true;
    } catch (err) {
      sentinel.textContent = err.message + ' — scroll to retry';
      return false;
    } finally {
      loading = false;
    }
  }

  const loader = new IntersectionObserver((entries) => {
    if (!entries[0].isIntersecting) return;
    // Re-observe afterwards: the observer only fires on changes, and the sentinel may still be in range.
    loadMore().then((ok) => { if (ok) { loader.unobserve(sentinel); loader.observe(sentinel); } });
  }, { rootMargin: '1500px 0px' });
  loader.observe(sentinel);

  // Remember how far we scrolled so Back from a detail page lands where you were.
  document.addEventListener('click', (e) => {
    if (e.target.closest('.card')) {
      try { sessionStorage.setItem(key, JSON.stringify({ next, y: scrollY })); } catch (_) {}
    }
  });
  (async function restore() {
    let saved;
    try { saved = JSON.parse(sessionStorage.getItem(key) || 'null'); sessionStorage.removeItem(key); } catch (_) {}
    if (!saved || performance.getEntriesByType('navigation')[0]?.type !== 'back_forward') return;
    while (next < saved.next && (await loadMore())) {}
    scrollTo(0, saved.y);
  })();
})();

// Shuffle button: submit the search form with a fresh random seed.
(function () {
  const btn = document.getElementById('shuffle-btn');
  if (!btn) return;
  btn.addEventListener('click', () => {
    const form = btn.closest('form');
    form.elements.shuffle.value = Math.random().toString(36).slice(2, 8);
    form.submit();
  });
})();

// Discovery controls (shown only for providers that offer them).
(function () {
  const form = document.getElementById('search-form');
  if (!form) return;
  const dept = document.getElementById('dept');
  if (dept) dept.addEventListener('change', () => { form.elements.shuffle.value = ''; form.submit(); });
  document.querySelectorAll('.era').forEach((b) => b.addEventListener('click', () => {
    form.elements['from'].value = b.dataset.from;
    form.elements['to'].value = b.dataset.to;
    form.elements.shuffle.value = '';
    form.submit();
  }));
  // Typing a new search term means the "match tags"/"match artist" flags from a link no longer apply.
  const q = form.elements.q;
  if (q && form.elements.tags) q.addEventListener('input', () => { form.elements.tags.value = ''; form.elements.artist.value = ''; });
})();
