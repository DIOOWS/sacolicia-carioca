const body = document.body;
const menuButton = document.querySelector('.menu-button');
const sidebar = document.querySelector('.sidebar');

function closeMenu() {
  body.classList.remove('menu-open');
  menuButton?.setAttribute('aria-expanded', 'false');
}

menuButton?.setAttribute('aria-expanded', 'false');
menuButton?.addEventListener('click', event => {
  event.stopPropagation();
  const opening = !body.classList.contains('menu-open');
  body.classList.toggle('menu-open', opening);
  menuButton.setAttribute('aria-expanded', String(opening));
});

document.addEventListener('click', event => {
  if (!body.classList.contains('menu-open')) return;
  if (sidebar?.contains(event.target) || menuButton?.contains(event.target)) return;
  closeMenu();
});

sidebar?.querySelectorAll('a').forEach(link => link.addEventListener('click', closeMenu));
document.addEventListener('keydown', event => {
  if (event.key === 'Escape') closeMenu();
});

const search = document.querySelector('.search');
search?.addEventListener('input', () => {
  const query = search.value.toLowerCase();
  document.querySelectorAll('.product').forEach(card => {
    card.hidden = !card.dataset.search.includes(query);
  });
});

function showLoading() {
  body.classList.add('page-loading');
}

document.querySelectorAll('a[href]').forEach(link => {
  link.addEventListener('click', event => {
    const href = link.getAttribute('href');
    if (!href || href.startsWith('#') || link.target === '_blank' || event.ctrlKey || event.metaKey) return;
    const destination = new URL(link.href, window.location.href);
    if (destination.origin === window.location.origin && destination.href !== window.location.href) showLoading();
  });
});

document.querySelectorAll('form').forEach(form => {
  form.addEventListener('submit', () => {
    if (form.checkValidity()) showLoading();
  });
});

window.addEventListener('pageshow', () => body.classList.remove('page-loading'));

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => navigator.serviceWorker.register('/service-worker.js'));
}
