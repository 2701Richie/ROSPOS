// main.js: starts the app and refreshes the Sell tab every 15 seconds
boot();
setInterval(async()=>{if(!ME||!$('#pm').hidden||!$('#md').hidden)return;if(tab==='sell'){const r=await load();if(!r.error){clampCart();drawGrid();drawLines()}}else if(tab==='live'){await refreshLive()}},5000);
