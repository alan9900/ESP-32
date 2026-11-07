(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const ids = ['screen','status-dot','status','page-title','page-clock','page-codex','clock-time','clock-date','clock-weekday','weather-icon','weather-city','weather-condition','weather-temperature','weather-high','weather-low','weather-humidity','weather-updated','five-value','five-reset','five-bar','five-countdown','weekly-value','weekly-reset','weekly-bar','weekly-countdown','updated','endpoint','api-token','source','last-update','live'];
  const el = Object.fromEntries(ids.map(id => [id, $(id)]));
  const tz = 'Asia/Shanghai';
  const validDate = value => value == null ? null : Number.isFinite(new Date(value).getTime()) ? new Date(value) : null;
  const formatTime = value => { const d = validDate(value); return d ? new Intl.DateTimeFormat('zh-CN',{timeZone:tz,month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(d) : '--'; };
  const toISO = ms => new Date(ms).toISOString();
  const conditions = {Clear:['晴','☀'],Cloudy:['多云','☁'],Fog:['雾','☁'],Drizzle:['毛毛雨','☂'],Rain:['雨','☂'],Snow:['雪','❄'],Thunder:['雷雨','ϟ'],Unknown:['天气未知','—']};
  function makeMock(type) {
    const now = Date.now();
    return {mode:'mock',updated_at:toISO(now),codex:{five_hour:{remaining_percent:type === 'low' ? 9 : 76,resets_at:toISO(now+2.7*3600000)},weekly:{remaining_percent:type === 'partial' ? null : type === 'low' ? 18 : 58,resets_at:type === 'partial' ? null : toISO(now+3*86400000)},error:type === 'partial' ? '周额度暂不可用' : null},weather:{city:'Changsha',condition:'Cloudy',temperature_c:24,high_c:27,low_c:19,humidity_percent:68,updated_at:toISO(now),error:null}};
  }
  let mode = 'live', cached = null, currentScenario = 'normal', lastError = null, currentPage = 0, requestSeq = 0, activeRequest = null, lastState = 'offline';
  const initialEndpoint = location.protocol.startsWith('http') ? new URL('/api/status',location.href).href : 'http://127.0.0.1:8787/api/status';
  el.endpoint.value = initialEndpoint;
  const pages = [el['page-clock'],el['page-codex']];
  function showPage(index) {
    currentPage = Math.max(0, Math.min(1, index));
    pages.forEach((page,i) => { page.hidden = i !== currentPage; });
    el['page-title'].textContent = ['桌面','Codex'][currentPage];
    document.querySelectorAll('[data-page]').forEach(button => {
      const active = Number(button.dataset.page) === currentPage;
      button.classList.toggle('active',active);
      if (button.classList.contains('page-dot')) { if (active) button.setAttribute('aria-current','page'); else button.removeAttribute('aria-current'); }
    });
  }
  function fit() { el.screen.style.transform = `scale(${el.screen.parentElement.clientWidth / 480})`; }
  window.addEventListener('resize',fit); fit();
  function clock() {
    const d = new Date();
    el['clock-time'].textContent = new Intl.DateTimeFormat('zh-CN',{timeZone:tz,hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(d);
    el['clock-date'].textContent = new Intl.DateTimeFormat('zh-CN',{timeZone:tz,month:'long',day:'numeric'}).format(d);
    el['clock-weekday'].textContent = new Intl.DateTimeFormat('zh-CN',{timeZone:tz,weekday:'long'}).format(d);
    if (cached) { renderWindow(cached?.codex?.five_hour,'five'); renderWindow(cached?.codex?.weekly,'weekly'); }
  }
  function countdown(value) {
    const d = validDate(value); if (!d) return '还剩 --';
    const minutes = Math.ceil((d.getTime() - Date.now()) / 60000);
    if (minutes <= 0) return '等待额度更新';
    const days = Math.floor(minutes / 1440), hours = Math.floor((minutes % 1440) / 60), mins = minutes % 60;
    return `还剩 ${days ? days + '天' : ''}${hours ? hours + '小时' : ''}${days ? '' : mins + '分'}`;
  }
  function renderWindow(item,prefix) {
    const n = item?.remaining_percent, valid = typeof n === 'number' && Number.isFinite(n) && n >= 0 && n <= 100;
    el[`${prefix}-value`].textContent = valid ? (Number.isInteger(n) ? n : n.toFixed(1)) : '--';
    el[`${prefix}-bar`].style.width = valid ? `${n}%` : '0%';
    el[`${prefix}-bar`].classList.toggle('low',valid && n <= 20);
    el[`${prefix}-value`].parentElement.classList.toggle('low',valid && n <= 20);
    el[`${prefix}-reset`].textContent = validDate(item?.resets_at) ? `重置 ${formatTime(item.resets_at)}` : '重置时间 --';
    el[`${prefix}-countdown`].textContent = countdown(item?.resets_at);
  }
  function render(data,state) {
    lastState = state;
    const partial = !!(data?.codex?.error || data?.weather?.error);
    const stamp = validDate(data?.updated_at), stale = stamp && Date.now()-stamp.getTime() > 120000;
    const mock = state === 'demo' || state === 'mockbackend' || data?.mode === 'mock';
    el.status.textContent = state === 'offline' ? (mock ? '离线 · 模拟' : '离线') : mock ? '模拟数据' : partial ? '部分异常' : stale ? '数据过期' : '已连接';
    el['status-dot'].className = `dot${state === 'offline' ? ' off' : (partial || stale || mock) ? ' warn' : ''}`;
    renderWindow(data?.codex?.five_hour,'five'); renderWindow(data?.codex?.weekly,'weekly');
    const weather = data?.weather, wt = validDate(weather?.updated_at), weatherStale = state === 'offline' || !!weather?.error || !wt || Date.now()-wt.getTime() > 30*60000;
    const displayCondition = conditions[weather?.condition] || ['--','—'];
    el['weather-city'].textContent = weather?.city === 'Changsha' ? '长沙' : weather?.city || '天气未配置';
    el['weather-condition'].textContent = displayCondition[0]; el['weather-icon'].textContent = displayCondition[1];
    const temp = weather?.temperature_c;
    el['weather-temperature'].textContent = typeof temp === 'number' && Number.isFinite(temp) ? `${Math.round(temp)}°C` : '--';
    const formatTemp = value => typeof value === 'number' && Number.isFinite(value) ? `${Math.round(value)}°` : '--';
    el['weather-high'].textContent = formatTemp(weather?.high_c);
    el['weather-low'].textContent = formatTemp(weather?.low_c);
    const humidity = weather?.humidity_percent;
    el['weather-humidity'].textContent = typeof humidity === 'number' && Number.isFinite(humidity) && humidity >= 0 && humidity <= 100 ? `${Math.round(humidity)}%` : '--';
    el['weather-updated'].textContent = wt ? `天气 ${weatherStale ? '上次更新' : '更新'} ${formatTime(wt)}${weatherStale ? ' · 可能已过期' : ''}` : '天气数据不可用';
    el['weather-updated'].classList.toggle('stale',!!weatherStale);
    el.updated.textContent = stamp ? `更新 ${formatTime(stamp)}` : '等待数据';
    document.querySelectorAll('.page-update').forEach(node => { node.textContent = stamp ? `更新 ${formatTime(stamp)}` : '等待数据'; });
    el['last-update'].textContent = stamp ? `${formatTime(stamp)} 北京时间` : '--';
    el.source.textContent = state === 'demo' ? `模拟 · ${currentScenario}` : state === 'mockbackend' ? '电脑端模拟数据' : state === 'offline' ? (cached ? '连接失败 · 上次结果' : '连接失败 · 无数据') : '电脑端服务';
    el.status.title = [lastError,data?.codex?.error,data?.weather?.error].filter(Boolean).join(' / ');
  }
  async function refresh() {
    const request = ++requestSeq;
    if (activeRequest) activeRequest.abort();
    if (mode === 'demo') { cached = makeMock(currentScenario); render(cached,currentScenario === 'offline' ? 'offline' : 'demo'); return; }
    el.status.textContent = '更新中';
    const controller = new AbortController(); activeRequest = controller;
    const timer = setTimeout(() => controller.abort(),8000);
    try {
      const url = new URL(el.endpoint.value);
      if (!['http:','https:'].includes(url.protocol)) throw new Error('仅支持 HTTP(S) 地址');
      const headers = {}; if (el['api-token'].value) headers.Authorization = `Bearer ${el['api-token'].value}`;
      const response = await fetch(url,{headers,signal:controller.signal,cache:'no-store'});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      if (!data || typeof data !== 'object' || !data.codex) throw new Error('数据格式不正确');
      if (request !== requestSeq) return;
      cached = data; lastError = null; render(data,data.mode === 'mock' ? 'mockbackend' : 'live');
    } catch (e) {
      if (request !== requestSeq) return;
      lastError = e.name === 'AbortError' ? '请求超时' : e.message; render(cached,'offline');
    } finally { clearTimeout(timer); if (activeRequest === controller) activeRequest = null; }
  }
  el.live.addEventListener('click',() => { mode='live'; lastError=null; document.querySelectorAll('.scenario').forEach(b => b.classList.remove('active')); refresh(); });
  document.querySelectorAll('.scenario').forEach(button => button.addEventListener('click',() => { mode='demo'; currentScenario=button.dataset.scenario; lastError=null; document.querySelectorAll('.scenario').forEach(x => x.classList.toggle('active',x===button)); refresh(); }));
  document.querySelectorAll('[data-page]').forEach(button => button.addEventListener('click',e => { e.stopPropagation(); showPage(Number(button.dataset.page)); }));
  let pointer = null;
  el.screen.addEventListener('pointerdown',e => { if (e.target.closest('button')) return; pointer={id:e.pointerId,x:e.clientX,y:e.clientY}; el.screen.setPointerCapture(e.pointerId); });
  el.screen.addEventListener('pointerup',e => { if (!pointer || pointer.id !== e.pointerId) return; const dx=e.clientX-pointer.x,dy=e.clientY-pointer.y; pointer=null; const threshold=35*el.screen.getBoundingClientRect().width/480; if (Math.abs(dx)>threshold && Math.abs(dx)>Math.abs(dy)) showPage(currentPage+(dx<0?1:-1)); else if (Math.abs(dx)<10 && Math.abs(dy)<10) refresh(); });
  el.screen.addEventListener('pointercancel',() => { pointer=null; });
  el.screen.addEventListener('keydown',e => { if (e.target.closest('button')) return; if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') { e.preventDefault(); showPage(currentPage+(e.key === 'ArrowRight'?1:-1)); } else if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); refresh(); } });
  setInterval(clock,1000); setInterval(() => { if(mode === 'live') refresh(); else if(cached) render(cached,lastState); },30000);
  showPage(0); clock(); refresh();
})();
