const CACHE='iroya-shell-v15';
const SHELL=['/','/static/css/app.css','/static/js/app.js','/static/manifest.json','/static/brand/iroya-logo.svg'];
const PRIVATE_PREFIXES=['/api/','/reservation/','/partner','/account','/notifications','/book','/invite/','/payment/'];

function isPrivatePath(pathname){
  return PRIVATE_PREFIXES.some(function(prefix){
    return pathname===prefix||pathname.startsWith(prefix);
  });
}

function mayCacheResponse(response){
  if(!response||!response.ok)return false;
  const cacheControl=(response.headers.get('cache-control')||'').toLowerCase();
  return !cacheControl.includes('private')&&!cacheControl.includes('no-store');
}

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
        return Promise.all(
          keys.filter(function(key){return key!==CACHE;})
            .map(function(key){return caches.delete(key);})
        );
      })
      .then(function(){return self.clients.claim();})
  );
});

self.addEventListener('fetch',function(event){
  const request=event.request;
  if(request.method!=='GET')return;

  const url=new URL(request.url);
  if(url.origin!==self.location.origin)return;
  if(isPrivatePath(url.pathname))return;

  if(request.mode==='navigate'){
    event.respondWith(
      fetch(request)
        .then(function(response){
          if(mayCacheResponse(response)){
            const copy=response.clone();
            caches.open(CACHE).then(function(cache){cache.put(request,copy);});
          }
          return response;
        })
        .catch(function(){
          return caches.match(request).then(function(hit){
            return hit||caches.match('/');
          });
        })
    );
    return;
  }

  if(url.pathname.startsWith('/static/')){
    event.respondWith(
      caches.match(request).then(function(hit){
        const network=fetch(request)
          .then(function(response){
            if(mayCacheResponse(response)){
              const copy=response.clone();
              caches.open(CACHE).then(function(cache){cache.put(request,copy);});
            }
            return response;
          })
          .catch(function(){return hit;});
        return hit||network;
      })
    );
  }
});
