(() => {
  const entries = [...document.querySelectorAll('.entry')];
  const indexLinks = [...document.querySelectorAll('[data-entry-link]')];
  const search = document.querySelector('#entry-search');
  const topic = document.querySelector('#tag-filter');
  const status = document.querySelector('.search-status');
  const empty = document.querySelector('.empty-search');
  const disclosure = document.querySelector('.index-disclosure');
  const mobile = window.matchMedia('(max-width: 720px)');
  const searchable = new Map(entries.map(entry => [entry.id, entry.textContent.toLocaleLowerCase()]));
  document.querySelector('.search-controls').hidden = false;
  const syncDisclosure = () => { disclosure.open = !mobile.matches; };
  syncDisclosure();
  mobile.addEventListener('change', syncDisclosure);

  const markCurrent = id => {
    indexLinks.forEach(link => {
      if (link.hash === `#${id}`) link.setAttribute('aria-current', 'location');
      else link.removeAttribute('aria-current');
    });
  };

  const filterEntries = () => {
    const query = search.value.trim().toLocaleLowerCase();
    let count = 0;
    entries.forEach(entry => {
      const matches = searchable.get(entry.id).includes(query) &&
        (!topic.value || JSON.parse(entry.dataset.tags).includes(topic.value));
      entry.hidden = !matches;
      if (matches) count++;
    });
    indexLinks.forEach(link => {
      link.closest('li').hidden = document.getElementById(link.hash.slice(1)).hidden;
    });
    document.querySelectorAll('.index-month').forEach(month => {
      month.hidden = [...month.querySelectorAll('li')].every(item => item.hidden);
    });
    status.hidden = !query && !topic.value;
    status.textContent = `${count} ${count === 1 ? 'entry' : 'entries'} found`;
    empty.hidden = count !== 0;
    markCurrent(entries.find(entry => !entry.hidden)?.id);
  };
  search.addEventListener('input', filterEntries);
  topic.addEventListener('change', filterEntries);
  document.querySelector('#clear-search').addEventListener('click', () => {
    search.value = '';
    topic.value = '';
    filterEntries();
    search.focus();
  });

  const revealHash = () => {
    const entry = entries.find(item => `#${item.id}` === window.location.hash);
    if (!entry) return;
    if (entry.hidden) {
      search.value = '';
      topic.value = '';
      filterEntries();
    }
    markCurrent(entry.id);
    entry.scrollIntoView();
  };
  window.addEventListener('hashchange', revealHash);
  indexLinks.forEach(link => link.addEventListener('click', () => {
    if (mobile.matches) disclosure.open = false;
  }));
  markCurrent(entries[0]?.id);
  if (window.location.hash) revealHash();

  if ('IntersectionObserver' in window) {
    const observer = new IntersectionObserver(items => {
      const visible = items.filter(item => item.isIntersecting && !item.target.hidden);
      if (visible.length) markCurrent(visible[0].target.id);
    }, { rootMargin: '-5% 0px -65% 0px', threshold: 0 });
    entries.forEach(entry => observer.observe(entry));
  }
  document.querySelectorAll('.pdf-preview').forEach(preview => {
    preview.addEventListener('toggle', () => {
      const frame = preview.querySelector('iframe');
      if (preview.open && !frame.hasAttribute('src')) frame.src = frame.dataset.src;
    });
  });
})();
