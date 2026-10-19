// fullscreen.js: header button that toggles full screen (hidden where the browser cannot do it)
(function(){const b=$('#fsb'),el=document.documentElement;
const req=el.requestFullscreen||el.webkitRequestFullscreen,ex=document.exitFullscreen||document.webkitExitFullscreen;
if(!req||!ex){b.style.display='none';return}
const on=()=>!!(document.fullscreenElement||document.webkitFullscreenElement);
const lab=()=>{const t=on()?'Exit full screen':'Full screen';b.textContent=t;b.title=t};
b.onclick=()=>{try{const r=on()?ex.call(document):req.call(el);if(r&&r.catch)r.catch(()=>{})}catch(e){}};
['fullscreenchange','webkitfullscreenchange'].forEach(n=>document.addEventListener(n,lab));lab()})();
