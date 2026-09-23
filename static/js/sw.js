const CACHE='roya-shell-v1';
const STATIC=['/static/css/app.css','/static/js/app.js','/static/manifest.json'];
self.addEventListener('install',function(e){e.waitUntil(caches.open(CACHE).then(function(c){return c.addAll(STATIC);}));});
self.addEventListener('fetch',function(e){if(e.request.method!=='GET')return;if(e.request.url.includes('/api/')||e.request.url.includes('/hotels/'))return;e.respondWith(caches.match(e.request).then(function(r){return r||fetch(e.request);}));});
