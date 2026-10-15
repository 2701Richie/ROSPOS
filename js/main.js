// main.js: starts the app and refreshes the Sell tab every 15 seconds
boot();
setInterval(async()=>{if(ME&&tab==='sell'&&$('#pm').hidden&&$('#md').hidden){const r=await load();if(!r.error){clampCart();drawGrid();drawLines()}}},15000);
