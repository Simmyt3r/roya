const CACHE='iroya-shell-v5';
const SHELL=[
  '/',
  '/static/css/app.css',
  '/static/js/app.js',
  '/static/manifest.json',
  '/static/brand/iroya-logo.svg'
];

self.addEventListener('install',function(event){
  event.waitUntil(
    caches.open(CACHE)
      .then(function(cache){return cache.addAll(SHELL);})
      .then(function(){return self.skipWaiting();})
  );
});

self.addEventListener('activate',function(event){
  event.waitUntil(
    caches.keys()
      .then(function(keys){
        return Promise.all(keys.filter(function(key){return key!==CACHE;}).map(function(key){return caches.delete(key);}));
      })
      .then(function(){return self.clients.claim();})
  );
});

self.addEventListener('fetch',function(event){
  const request=event.request;
  if(request.method!=='GET')return;

  const url=new URL(request.url);
  if(url.origin!==self.location.origin)return;
  if(url.pathname.startsWith('/api/') || url.pathname.startsWith('/reservation/') || url.pathname.startsWith('/partner'))return;

  if(request.mode==='navigate'){
    event.respondWith(
      fetch(request)
        .then(function(response){
          const copy=response.clone();
          if(response.ok)caches.open(CACHE).then(function(cache){cache.put(request,copy);});
          return response;
        })
        .catch(function(){
          return caches.match(request).then(function(hit){return hit||caches.match('/');});
        })
    );
    return;
  }

  if(url.pathname.startsWith('/static/')){
    event.respondWith(
      caches.match(request).then(function(hit){
        const network=fetch(request).then(function(response){
          if(response.ok){
            const copy=response.clone();
            caches.open(CACHE).then(function(cache){cache.put(request,copy);});
          }
          return response;
        }).catch(function(){return hit;});
        return hit||network;
      })
    );
  }
});
