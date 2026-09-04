const CACHE_NAME = 'mediocare-v5';
const STATIC_ASSETS = [
  '/static/style.css',
  '/static/logo.png',
  '/marketer',
  '/marketer/report',
  '/my-places'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(STATIC_ASSETS))
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(cacheNames => {
      return Promise.all(
        cacheNames.filter(name => name !== CACHE_NAME).map(name => caches.delete(name))
      );
    })
  );
});

self.addEventListener('fetch', event => {
  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request).catch(() => caches.match(event.request))
    );
    return;
  }
  event.respondWith(
    caches.match(event.request).then(response => response || fetch(event.request))
  );
});

// Background sync for offline reports
self.addEventListener('sync', event => {
  if (event.tag === 'sync-reports') {
    event.waitUntil(syncReports());
  }
});

async function syncReports() {
  const queue = await getQueuedReports();
  for (const report of queue) {
    try {
      await fetch('/marketer/report', {
        method: 'POST',
        headers: {'Content-Type': 'application/x-www-form-urlencoded'},
        body: new URLSearchParams(report).toString()
      });
      await removeQueuedReport(report.id);
    } catch (e) {
      console.error('Sync failed for report', report, e);
    }
  }
}

// Helper functions for offline report queue (used by report form if extended)
async function getQueuedReports() {
  const db = await openDB();
  const tx = db.transaction('offlineReports', 'readonly');
  const store = tx.objectStore('offlineReports');
  return await store.getAll();
}

async function removeQueuedReport(id) {
  const db = await openDB();
  const tx = db.transaction('offlineReports', 'readwrite');
  const store = tx.objectStore('offlineReports');
  await store.delete(id);
  await tx.complete;
}

function openDB() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open('MediocareOffline', 1);
    request.onupgradeneeded = (event) => {
      const db = event.target.result;
      if (!db.objectStoreNames.contains('offlineReports')) {
        db.createObjectStore('offlineReports', { keyPath: 'id', autoIncrement: true });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}
