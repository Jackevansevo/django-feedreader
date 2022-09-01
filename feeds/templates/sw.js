const addResourcesToCache = async (resources) => {
  const cache = await caches.open("v1");
  await cache.addAll(resources);
};

self.addEventListener("install", (event) => {
  event.waitUntil(
    addResourcesToCache([])
  );
});

const putInCache = async (request, response) => {
  const cache = await caches.open("v1");
  await cache.put(request, response);
};

const cacheFirst = async (request) => {
	let url = new URL(request.url);
	if (url.pathname.includes('/media/') || url.hostname.includes("digitaloceanspaces")) {
		const responseFromCache = await caches.match(url.pathname);
		if (responseFromCache) {
			console.log('serving cached response for', request.url)
			return responseFromCache;
		}
	}

  const responseFromNetwork = await fetch(request);
	if (responseFromNetwork.ok) {
		if (url.pathname.includes('/media/') || url.hostname.includes("digitaloceanspaces")) {
			console.log('caching', request.url)
			putInCache(url.pathname, responseFromNetwork.clone());
		}
	}
  return responseFromNetwork;
};

self.addEventListener("fetch", (event) => {
  event.respondWith(cacheFirst(event.request));
});
