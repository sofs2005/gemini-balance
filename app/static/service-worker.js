const CACHE_NAME = 'gbalance-cache-v1';
const urlsToCache = [
  '/',
  '/static/manifest.json',
  '/static/icons/icon-192x192.png'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => {
        console.log('Opened cache');
        return cache.addAll(urlsToCache);
      })
  );
});

self.addEventListener('fetch', event => {
  event.respondWith(
    caches.open(CACHE_NAME).then(cache => {
      // 1. 尝试从缓存获取
      return cache.match(event.request).then(responseFromCache => {
        // 2. 同时从网络获取 (后台进行)
        const fetchPromise = fetch(event.request).then(responseFromNetwork => {
          // 3. 网络请求成功，更新缓存
          cache.put(event.request, responseFromNetwork.clone());
          return responseFromNetwork;
        }).catch(err => {
          // 网络请求失败时，可以选择记录错误或不执行任何操作
          console.error('Network fetch failed:', err);
          // 确保即使网络失败，如果缓存存在，我们仍然返回缓存
          // 如果缓存也不存在，则此 Promise 会 reject
          throw err;
        });

        // 4. 如果缓存存在，立即返回缓存；否则等待网络响应
        //    后台的网络请求仍在进行，用于更新缓存
        return responseFromCache || fetchPromise;
      });
    })
  );
});

self.addEventListener('activate', event => {
  const cacheWhitelist = [CACHE_NAME];
  event.waitUntil(
    caches.keys().then(cacheNames => {
      return Promise.all(
        cacheNames.map(cacheName => {
          if (cacheWhitelist.indexOf(cacheName) === -1) {
            return caches.delete(cacheName);
          }
        })
      );
    })
  );
});
