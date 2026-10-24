// main.js: bootstrap and lightweight background refreshes for the active tab.
boot();

const SELL_REFRESH_INTERVAL_MS = 5000;
let refreshBusy = false;
let sellProductSnapshot = null;
let sellCartSnapshot = null;

function sellSnapshot() {
  return JSON.stringify(S.p || []);
}

async function refreshSell() {
  const beforeCart = JSON.stringify(cart);
  const response = await load();
  if (response.error || response.notModified || !ME || tab !== 'sell') return;

  const products = sellSnapshot();
  const productsChanged = products !== sellProductSnapshot;
  sellProductSnapshot = products;

  // Only re-render catalog tiles if product details (including stock) changed.
  if (productsChanged) drawGrid();

  clampCart();
  const cartState = JSON.stringify(cart);
  if (productsChanged || cartState !== beforeCart || cartState !== sellCartSnapshot) {
    drawLines();
  }
  sellCartSnapshot = cartState;
}

async function refreshActiveTab() {
  if (refreshBusy || !ME || !$('#pm').hidden || !$('#md').hidden) return;
  if (typeof document !== 'undefined' && document.hidden) return;

  const active = document.activeElement;
  // Never replace the cart while a quantity is being edited.
  if (active && active.classList && active.classList.contains('qn')) return;
  if (tab !== 'sell' && tab !== 'live') return;

  refreshBusy = true;
  try {
    if (tab === 'sell') await refreshSell();
    else if (tab === 'live') await refreshLive();
  } finally {
    refreshBusy = false;
  }
}

setInterval(refreshActiveTab, SELL_REFRESH_INTERVAL_MS);
