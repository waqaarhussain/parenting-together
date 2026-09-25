var state = { me: null, page: "home", cache: {}, chat: null, unread: 0, calendarCursor: new Date(), theme: localStorage.getItem("pt-theme") || "system" };
var liveTimer = null;
var liveBusy = false;
var typingLastSent = 0;
var typingActive = false;

var icons = {
  home:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M3 10.5 12 3l9 7.5v9a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 19.5z"/><path d="M9 21v-7h6v7"/></svg>',
  chat:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M21 12a8 8 0 0 1-8 8H6l-4 2 1.5-4.5A9 9 0 1 1 21 12z"/></svg>',
  calendar:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v4M17 3v4M3 10h18"/></svg>',
  swap:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M7 7h13l-3-3m3 3-3 3M17 17H4l3 3m-3-3 3-3"/></svg>',
  check:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="m5 12 4 4L19 6"/></svg>',
  wallet:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><rect x="3" y="5" width="18" height="15" rx="3"/><path d="M16 11h5v5h-5a2.5 2.5 0 0 1 0-5zM3 9h15"/></svg>',
  shield:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M12 3 20 6v6c0 5-3.4 8-8 9-4.6-1-8-4-8-9V6z"/><path d="m8 12 2.5 2.5L16 9"/></svg>',
  rules:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M6 4h12M6 10h12M6 16h8M4 4h.01M4 10h.01M4 16h.01"/></svg>',
  search:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></svg>',
  sun:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>',
  moon:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M20 15.2A8 8 0 0 1 8.8 4 8 8 0 1 0 20 15.2z"/></svg>',
  send:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="m22 2-7 20-4-9-9-4zM22 2 11 13"/></svg>',
  plus:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M12 5v14M5 12h14"/></svg>'
};

var pages = [
  ["home","Home","Overview",icons.home],
  ["messages","Messages","Family chat",icons.chat],
  ["calendar","Calendar","Shared plans",icons.calendar],
  ["handovers","Handovers","Pickups & drop-offs",icons.swap],
  ["decisions","Decisions","Clear approvals",icons.check],
  ["expenses","Expenses","Shared costs",icons.wallet],
  ["evidence","Evidence","Timeline & exports",icons.shield],
  ["rules","Rules","Agreement rules",icons.rules],
  ["search","Search","Everything at once",icons.search]
];

function esc(v) {
  return String(v == null ? "" : v).replace(/[&<>"']/g, function(c) {
    return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[c];
  });
}
function fmt(v) {
  if (!v) return "Not set";
  var d = new Date(v);
  if (isNaN(d)) return v;
  return d.toLocaleString([], {day:"numeric",month:"short",hour:"2-digit",minute:"2-digit"});
}
function fmtDate(v) {
  if (!v) return "";
  var d = new Date(v);
  if (isNaN(d)) return v;
  return d.toLocaleDateString([], {day:"numeric",month:"short",year:"numeric"});
}
function initials(name) {
  return (name || "?").split(/\s+/).slice(0,2).map(function(x){return x[0] || "";}).join("").toUpperCase();
}
function money(p) { return "£" + ((Number(p)||0)/100).toFixed(2); }
function status(s) { return '<span class="status '+esc(s)+'">'+esc(s)+'</span>'; }
function isFutureEvent(startAt) {
  return new Date(startAt).getTime() > Date.now();
}

function applyTheme() {
  document.documentElement.setAttribute("data-theme", state.theme);
  localStorage.setItem("pt-theme", state.theme);
  var label = state.theme === "dark" ? "Dark" : state.theme === "light" ? "Light" : "System";
  var icon = state.theme === "dark" ? icons.moon : icons.sun;
  document.querySelectorAll(".theme-toggle").forEach(function(b){ b.innerHTML = icon; });
  var sb = document.getElementById("sidebar-theme");
  if (sb) sb.textContent = label + " theme";
}
function cycleTheme() {
  state.theme = state.theme === "system" ? "light" : state.theme === "light" ? "dark" : "system";
  applyTheme();
}

async function api(url, options) {
  options = options || {};
  options.headers = options.headers || {};
  if (state.me && state.me.csrf && options.method && options.method !== "GET") options.headers["X-CSRF-Token"] = state.me.csrf;
  if (options.json !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(options.json);
    delete options.json;
  }
  var r = await fetch(url, options);
  var ct = r.headers.get("content-type") || "";
  var data = ct.includes("application/json") ? await r.json() : await r.text();
  if (!r.ok) throw new Error((data && data.error) || "Something went wrong.");
  return data;
}

function toast(msg, type) {
  var el = document.getElementById("toast");
  el.textContent = msg;
  el.className = "toast " + (type || "");
  setTimeout(function(){ el.classList.add("hidden"); }, 3300);
}

function openModal(html, onReady) {
  document.getElementById("modal-content").innerHTML = html;
  document.getElementById("modal").classList.remove("hidden");
  if (onReady) onReady();
}
function closeModal() { document.getElementById("modal").classList.add("hidden"); }

function setAuthTab(tab) {
  document.querySelectorAll(".auth-tab").forEach(function(b){ b.classList.toggle("active", b.dataset.authTab === tab); });
  document.getElementById("login-form").classList.toggle("hidden", tab !== "login");
  document.getElementById("register-form").classList.toggle("hidden", tab !== "register");
}

async function bootstrap() {
  applyTheme();
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/static/sw.js").catch(function(){});
  try {
    var me = await api("/api/me");
    if (!me.authenticated) return showAuth();
    state.me = me;
    showApp();
    await render();
  } catch (e) {
    showAuth();
    toast(e.message, "error");
  }
}

function showAuth() {
  state.me = null;
  state.chat = null;
  if (liveTimer) clearInterval(liveTimer);
  liveTimer = null;
  document.getElementById("auth-view").classList.remove("hidden");
  document.getElementById("app-view").classList.add("hidden");
}
function showApp() {
  document.getElementById("auth-view").classList.add("hidden");
  document.getElementById("app-view").classList.remove("hidden");
  document.getElementById("user-avatar").textContent = initials(state.me.user.name);
  document.getElementById("family-card").innerHTML = '<strong>'+esc(state.me.family.name)+'</strong><span>'+state.me.members.length+' parent'+(state.me.members.length===1?"":"s")+' · '+state.me.children.length+' child profile'+(state.me.children.length===1?"":"s")+'</span>';
  renderNav();
  applyTheme();
  if (!liveTimer) liveTimer = setInterval(refreshLiveState, 2500);
  refreshLiveState();
}

function renderNav() {
  var desktop = document.getElementById("desktop-nav");
  desktop.innerHTML = pages.map(function(p){
    return '<button class="nav-button '+(state.page===p[0]?"active":"")+'" data-page="'+p[0]+'">'+p[3]+'<span>'+p[1]+'</span>'+(p[0]==="messages"?'<span class="unread-badge hidden"></span>':'')+'</button>';
  }).join("");
  desktop.querySelectorAll("[data-page]").forEach(function(b){ b.onclick=function(){ navigate(b.dataset.page); }; });
  var mobileKeys = ["home","messages","calendar","evidence","search"];
  document.getElementById("mobile-nav").innerHTML = mobileKeys.map(function(k){
    var p = pages.find(function(x){return x[0]===k;});
    return '<button class="'+(state.page===k?"active":"")+'" data-page="'+k+'">'+p[3]+'<span>'+p[1]+'</span>'+(k==="messages"?'<span class="unread-badge hidden"></span>':'')+'</button>';
  }).join("");
  document.querySelectorAll("#mobile-nav [data-page]").forEach(function(b){ b.onclick=function(){ navigate(b.dataset.page); }; });
  updateUnreadBadges();
}
function updateUnreadBadges() {
  document.querySelectorAll('[data-page="messages"] .unread-badge').forEach(function(badge){
    badge.textContent = state.unread > 99 ? "99+" : String(state.unread);
    badge.classList.toggle("hidden", state.unread === 0);
  });
}
async function refreshLiveState() {
  if (liveBusy || !state.me || document.hidden) return;
  liveBusy = true;
  try {
    if (state.page === "messages" && state.chat) await pollChat();
    var status = await api("/api/messages/status");
    state.unread = status.unread;
    updateUnreadBadges();
    if (state.page === "messages" && state.chat) {
      var indicator = document.getElementById("typing-indicator");
      if (indicator) {
        indicator.textContent = status.typing_name ? status.typing_name + " is typing…" : "";
        indicator.classList.toggle("hidden", !status.typing_name);
      }
      Object.keys(status.reads).forEach(function(id){
        var item = state.chat.messages.find(function(message){return String(message.id) === id;});
        if (item && item.read_at !== status.reads[id]) {
          item.read_at = status.reads[id];
          var meta = document.querySelector('[data-message-id="'+id+'"] .message-meta');
          if (meta) meta.textContent = messageMeta(item);
        }
      });
    }
  } catch (e) {
    if (e.message === "Sign in required") {
      showAuth();
      toast("Your session ended. Sign in again.", "error");
    }
  } finally {
    liveBusy = false;
  }
}
async function navigate(page) {
  if (state.page === "messages" && page !== "messages") stopTyping();
  if (page !== "messages") state.chat = null;
  state.page = page;
  renderNav();
  await render();
  window.scrollTo({top:0,behavior:"smooth"});
}
function setHeading() {
  var p = pages.find(function(x){ return x[0] === state.page; }) || pages[0];
  document.getElementById("page-title").textContent = p[1];
  document.getElementById("page-eyebrow").textContent = p[2];
}

async function render() {
  setHeading();
  var page = document.getElementById("page");
  page.innerHTML = '<div class="empty"><strong>Loading</strong>Pulling your family space together…</div>';
  try {
    if (state.page === "home") return await renderHome();
    if (state.page === "messages") return await renderMessages();
    if (state.page === "calendar") return await renderCalendar();
    if (state.page === "handovers") return await renderHandovers();
    if (state.page === "decisions") return await renderDecisions();
    if (state.page === "expenses") return await renderExpenses();
    if (state.page === "evidence") return await renderEvidence();
    if (state.page === "rules") return await renderRules();
    if (state.page === "search") return await renderSearch();
  } catch (e) {
    page.innerHTML = '<div class="empty"><strong>Could not load this page</strong>'+esc(e.message)+'</div>';
  }
}

async function getAll() {
  var data = await Promise.all([
    api("/api/handovers"), api("/api/decisions"), api("/api/expenses"),
    api("/api/timeline?limit=20"), api("/api/rules")
  ]);
  return {handovers:data[0],decisions:data[1],expenses:data[2],timeline:data[3],rules:data[4]};
}

async function renderHome() {
  var d = await getAll();
  var pending = d.handovers.filter(function(x){return x.status==="pending";}).length + d.decisions.filter(function(x){return x.status==="pending";}).length + d.expenses.filter(function(x){return x.status==="pending";}).length;
  var connected = state.me.members.length > 1;
  document.getElementById("page").innerHTML =
    '<div class="page-grid">'+
      '<section class="card welcome-card span-8"><p class="eyebrow">YOUR FAMILY SPACE</p><h3>Hi '+esc(state.me.user.name.split(" ")[0])+'.</h3><p>'+ (connected ? 'Everything shared between both parents stays organised, timestamped and easy to find.' : 'You are in solo mode. Start organising now, then connect the other parent whenever you are ready.') +'</p><div class="quick-actions"><button class="quick-action" id="qa-invite">'+(connected?'Family code':'Connect co-parent')+'</button><button class="quick-action" id="qa-child">Add child</button></div></section>'+
      '<section class="metric-card span-4"><div class="metric-label">Open items</div><div class="metric-value">'+pending+'</div><div class="metric-note">Handovers, decisions and expenses awaiting action.</div></section>'+
      '<section class="metric-card span-6"><div class="metric-label">Children</div><div class="metric-value">'+state.me.children.length+'</div><div class="metric-note">'+(state.me.children.length?state.me.children.map(function(c){return esc(c.name);}).join(" · "):"Add profiles to personalise the family space.")+'</div></section>'+
      '<section class="metric-card span-6"><div class="metric-label">Evidence records</div><div class="metric-value">'+d.timeline.length+(d.timeline.length===20?"+":"")+'</div><div class="metric-note">Recent activity saved in the family record.</div></section>'+
      '<section class="card span-12"><div class="card-head"><div><h3>Recent activity</h3><p>Newest activity first.</p></div><button class="tiny-button" id="home-evidence">View all</button></div>'+timelineHtml(d.timeline.slice(0,6))+'</section>'+
    '</div>';
  document.getElementById("qa-invite").onclick=openInviteModal;
  document.getElementById("qa-child").onclick=openChildModal;
  document.getElementById("home-evidence").onclick=function(){navigate("evidence");};
}

function listEvents(items) {
  if (!items.length) return '<div class="empty"><strong>Nothing coming up</strong>Add school runs, appointments, clubs or holidays.</div>';
  return '<div class="list">'+items.map(function(e){
    return '<div class="list-item"><div class="list-main"><div class="list-title">'+esc(e.title)+'</div><div class="list-sub">'+fmt(e.start_at)+' · '+esc(e.category)+'</div></div><span class="status">'+esc(e.category)+'</span></div>';
  }).join("")+'</div>';
}

function openInviteModal() {
  var connected = state.me.members.length>1;
  openModal('<h3>'+(connected?'Family connection':'Connect your co-parent')+'</h3><p>Share this invite code with the other parent. Their records will then join this family space.</p><div class="card" style="text-align:center;margin:18px 0"><div class="invite-code">'+esc(state.me.family.invite_code)+'</div></div><button class="primary-button wide" id="copy-code">Copy invite code</button>' + (!connected ? '<div style="height:18px"></div><p>Already received a code from the other parent?</p><form id="join-family" class="form-stack"><div class="field"><label>Their invite code</label><input name="invite_code" required placeholder="AB12CD34"></div><button class="soft-button" type="submit">Join their family space</button></form>' : ''), function(){
    document.getElementById("copy-code").onclick=function(){navigator.clipboard.writeText(state.me.family.invite_code);toast("Invite code copied","success");};
    var form=document.getElementById("join-family");
    if(form) form.onsubmit=async function(e){e.preventDefault();try{var fd=new FormData(form);var r=await api("/api/family/join",{method:"POST",json:{invite_code:fd.get("invite_code")}});state.me=r;closeModal();showApp();await render();toast("Family spaces connected","success");}catch(err){toast(err.message,"error");}};
  });
}

function openChildModal() {
  openModal('<h3>Add child profile</h3><p>This keeps plans and records centred around the children, without making them participants in adult conversations.</p><form id="child-form" class="form-stack"><div class="field"><label>Name</label><input name="name" required></div><div class="field"><label>Birthday <span style="font-weight:400">(optional)</span></label><input name="birthday" type="date"></div><button class="primary-button" type="submit">Add child</button></form>',function(){
    document.getElementById("child-form").onsubmit=async function(e){e.preventDefault();var fd=new FormData(e.target);try{await api("/api/children",{method:"POST",json:{name:fd.get("name"),birthday:fd.get("birthday")}});var me=await api("/api/me");state.me=me;closeModal();showApp();render();toast("Child profile added","success");}catch(err){toast(err.message,"error");}};
  });
}

function messageMeta(message) {
  var mine = message.sender_id === state.me.user.id;
  return fmt(message.created_at) + (mine ? (message.read_at ? " · Read " + fmt(message.read_at) : " · Sent") : "");
}
function messageHtml(message) {
  var mine = message.sender_id === state.me.user.id;
  return '<div class="message-row '+(mine?"mine":"")+'" data-message-id="'+message.id+'"><div class="bubble-wrap">'+
    (!mine?'<div class="message-sender">'+esc(message.sender_name)+'</div>':'')+
    '<div class="bubble">'+esc(message.body)+'</div><div class="message-meta">'+esc(messageMeta(message))+'</div></div></div>';
}
async function pollChat(force) {
  var chat = state.chat;
  var box = document.getElementById("messages");
  if (!chat || !box || chat.polling || state.page !== "messages") return;
  if (!force && box.scrollHeight - box.scrollTop - box.clientHeight > 100) return;
  chat.polling = true;
  try {
    do {
      var lastId = chat.messages.length ? chat.messages[chat.messages.length-1].id : 0;
      var next = await api("/api/messages?after="+lastId);
      if (state.chat !== chat || state.page !== "messages") return;
      if (!next.length) break;
      var empty = box.querySelector(".empty");
      if (empty) empty.remove();
      chat.messages.push.apply(chat.messages, next);
      box.insertAdjacentHTML("beforeend", next.map(messageHtml).join(""));
      box.scrollTop = box.scrollHeight;
      if (next.length < 50) break;
    } while (true);
  } finally {
    chat.polling = false;
  }
}
async function loadOlderMessages() {
  var chat = state.chat;
  var box = document.getElementById("messages");
  if (!chat || !box || chat.loadingOlder || !chat.hasOlder || !chat.messages.length) return;
  chat.loadingOlder = true;
  try {
    var older = await api("/api/messages?before="+chat.messages[0].id);
    if (state.chat !== chat || state.page !== "messages") return;
    chat.hasOlder = older.length === 50;
    document.getElementById("load-older").classList.toggle("hidden", !chat.hasOlder);
    if (older.length) {
      var previousHeight = box.scrollHeight;
      chat.messages = older.concat(chat.messages);
      document.getElementById("history-trigger").insertAdjacentHTML("afterend", older.map(messageHtml).join(""));
      box.scrollTop += box.scrollHeight - previousHeight;
      refreshLiveState();
    }
  } catch (e) {
    toast(e.message, "error");
  } finally {
    chat.loadingOlder = false;
  }
}
function stopTyping() {
  if (!typingActive || !state.me) return;
  typingActive = false;
  typingLastSent = 0;
  api("/api/messages/typing", {method:"POST", json:{typing:false}}).catch(function(){});
}
async function renderMessages() {
  var messages = await api("/api/messages");
  var verify = await api("/api/messages/verify");
  if (state.page !== "messages") return;
  state.chat = {messages:messages, hasOlder:messages.length===50, loadingOlder:false, polling:false};
  document.getElementById("page").innerHTML =
    '<div class="chat-shell"><div class="chat-header"><div><strong>Family messages</strong><br><span>Sent messages cannot be edited or deleted.</span><span id="typing-indicator" class="typing-indicator hidden"></span></div><span class="integrity"><i class="integrity-dot"></i>'+(verify.verified?"Records checked":"Record check failed")+'</span></div>'+
    '<div id="messages" class="messages"><div id="history-trigger"><button id="load-older" class="tiny-button'+(messages.length===50?'':' hidden')+'" type="button">Load earlier messages</button></div>'+
    (messages.length?messages.map(messageHtml).join(""):'<div class="empty"><strong>No messages yet</strong>Start the conversation. Sent messages stay in the family record.</div>')+'</div>'+
    '<form id="message-form" class="chat-compose"><textarea name="body" maxlength="5000" placeholder="Write a message…" required></textarea><button class="send-button" aria-label="Send">'+icons.send+'</button></form></div>';
  var box = document.getElementById("messages");
  box.scrollTop = box.scrollHeight;
  box.addEventListener("scroll", function(){
    if (box.scrollTop < 50) loadOlderMessages();
    if (box.scrollHeight - box.scrollTop - box.clientHeight < 100) refreshLiveState();
  });
  document.getElementById("load-older").onclick = loadOlderMessages;
  var form = document.getElementById("message-form");
  var input = form.elements.namedItem("body");
  input.addEventListener("keydown", function(e){
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      form.requestSubmit();
    }
  });
  input.addEventListener("input", function(){
    if (!input.value.trim()) { stopTyping(); return; }
    if (Date.now() - typingLastSent > 2500) {
      typingLastSent = Date.now();
      typingActive = true;
      api("/api/messages/typing", {method:"POST", json:{typing:true}}).catch(function(){});
    }
  });
  input.addEventListener("blur", stopTyping);
  form.onsubmit = async function(e){
    e.preventDefault();
    var body = input.value.trim();
    if (!body || form.querySelector("button").disabled) return;
    form.querySelector("button").disabled = true;
    stopTyping();
    try {
      await api("/api/messages", {method:"POST", json:{body:body}});
      input.value = "";
      await pollChat(true);
    } catch (err) {
      toast(err.message, "error");
    } finally {
      form.querySelector("button").disabled = false;
    }
  };
  refreshLiveState();
}

async function renderCalendar() {
  var events=await api("/api/events");
  var cur=state.calendarCursor;
  var y=cur.getFullYear(),m=cur.getMonth();
  var first=new Date(y,m,1), start=new Date(y,m,1-first.getDay());
  var today=new Date();
  var cells="";
  for(var i=0;i<42;i++){
    var d=new Date(start);d.setDate(start.getDate()+i);
    var key=d.getFullYear()+"-"+String(d.getMonth()+1).padStart(2,"0")+"-"+String(d.getDate()).padStart(2,"0");
    var ev=events.filter(function(x){return String(x.start_at).slice(0,10)===key;});
    var cls="day"+(d.getMonth()!==m?" other":"")+(d.toDateString()===today.toDateString()?" today":"");
    cells+='<div class="'+cls+'"><div class="day-num">'+d.getDate()+'</div>'+ev.slice(0,3).map(function(x){return '<span class="event-chip">'+esc(x.title)+'</span>';}).join("")+'</div>';
  }
  var upcoming=events.filter(function(x){return isFutureEvent(x.start_at);}).slice(0,8);
  document.getElementById("page").innerHTML='<div class="calendar-wrap"><section class="calendar-card"><div class="calendar-head"><button class="tiny-button" id="cal-prev">‹</button><strong>'+cur.toLocaleDateString([],{month:"long",year:"numeric"})+'</strong><button class="tiny-button" id="cal-next">›</button></div><div class="calendar-grid">'+["Sun","Mon","Tue","Wed","Thu","Fri","Sat"].map(function(x){return '<div class="weekday">'+x+'</div>';}).join("")+cells+'</div></section><section class="card"><div class="card-head"><div><h3>Upcoming events</h3><p>School, appointments, clubs and holidays.</p></div><button class="tiny-button primary" id="cal-add">+ Add</button></div>'+listEvents(upcoming)+'</section></div>';
  document.getElementById("cal-prev").onclick=function(){state.calendarCursor=new Date(y,m-1,1);renderCalendar();};
  document.getElementById("cal-next").onclick=function(){state.calendarCursor=new Date(y,m+1,1);renderCalendar();};
  document.getElementById("cal-add").onclick=openEventModal;
}

function openEventModal() {
  openModal('<h3>Add shared plan</h3><p>Plans are timestamped and appear in both the calendar and evidence timeline.</p><form id="event-form" class="form-stack"><div class="field"><label>Title</label><input name="title" required placeholder="School pickup"></div><div class="field"><label>Type</label><select name="category"><option value="general">General</option><option value="school">School</option><option value="handover">Handover</option><option value="appointment">Appointment</option><option value="club">Club</option><option value="holiday">Holiday</option></select></div><div class="field"><label>Starts</label><input type="datetime-local" name="start_at" required></div><div class="field"><label>Notes</label><textarea name="notes" placeholder="Anything both parents need to know"></textarea></div><button class="primary-button" type="submit">Add to calendar</button></form>',function(){
    document.getElementById("event-form").onsubmit=async function(e){e.preventDefault();var fd=new FormData(e.target);try{var r=await api("/api/events",{method:"POST",json:{title:fd.get("title"),category:fd.get("category"),start_at:fd.get("start_at"),notes:fd.get("notes")}});closeModal();render();if(r.warnings&&r.warnings.length)toast(r.warnings[0],"error");else toast("Plan added","success");}catch(err){toast(err.message,"error");}};
  });
}

async function renderHandovers() {
  var items=await api("/api/handovers");
  var uid=state.me.user.id;
  document.getElementById("page").innerHTML='<div class="page-grid"><section class="card span-12"><div class="card-head"><div><h3>Handover record</h3><p>Make pickups and drop-offs explicit, not buried inside chat.</p></div><button class="primary-button" id="add-handover">New handover</button></div>'+(items.length?'<div class="list">'+items.map(function(x){return '<div class="list-item"><div class="list-main"><div class="list-title">'+esc(x.title)+'</div><div class="list-sub">'+fmt(x.scheduled_at)+(x.location?' · '+esc(x.location):'')+' · requested by '+esc(x.creator_name)+(x.response_note?' · '+esc(x.response_note):'')+'</div></div><div class="inline-actions">'+status(x.status)+(x.status==="pending"&&x.creator_id!==uid?'<button class="tiny-button" data-hresp="'+x.id+'" data-status="accepted">Accept</button><button class="tiny-button" data-hresp="'+x.id+'" data-status="declined">Decline</button><button class="tiny-button" data-hresp="'+x.id+'" data-status="countered">Counter</button>':'')+(x.status==="accepted"?'<button class="tiny-button primary" data-complete="'+x.id+'">Mark complete</button>':'')+'</div></div>';}).join("")+'</div>':'<div class="empty"><strong>No handovers yet</strong>Create a structured pickup or drop-off request.</div>')+'</section></div>';
  document.getElementById("add-handover").onclick=function(){openSimpleCreate("handover");};
  document.querySelectorAll("[data-hresp]").forEach(function(b){b.onclick=function(){respondItem("handover",b.dataset.hresp,b.dataset.status);};});
  document.querySelectorAll("[data-complete]").forEach(function(b){b.onclick=async function(){try{await api("/api/handovers/"+b.dataset.complete+"/complete",{method:"POST",json:{}});renderHandovers();toast("Handover completion recorded","success");}catch(e){toast(e.message,"error");}};});
}

async function renderDecisions() {
  var items=await api("/api/decisions"),uid=state.me.user.id;
  document.getElementById("page").innerHTML='<section class="card"><div class="card-head"><div><h3>Structured decisions</h3><p>School trips, clubs, passports and other choices get a clear answer and permanent history.</p></div><button class="primary-button" id="add-decision">New decision</button></div>'+(items.length?'<div class="list">'+items.map(function(x){return '<div class="list-item"><div class="list-main"><div class="list-title">'+esc(x.title)+'</div><div class="list-sub">'+esc(x.details||"No details")+(x.deadline?' · Reply by '+fmtDate(x.deadline):'')+(x.response_note?' · '+esc(x.response_note):'')+'</div></div><div class="inline-actions">'+status(x.status)+(x.status==="pending"&&x.creator_id!==uid?'<button class="tiny-button" data-dresp="'+x.id+'" data-status="accepted">Accept</button><button class="tiny-button" data-dresp="'+x.id+'" data-status="declined">Decline</button><button class="tiny-button" data-dresp="'+x.id+'" data-status="countered">Counter</button>':'')+'</div></div>';}).join("")+'</div>':'<div class="empty"><strong>No decisions yet</strong>Create a decision instead of arguing through a long message thread.</div>')+'</section>';
  document.getElementById("add-decision").onclick=function(){openSimpleCreate("decision");};
  document.querySelectorAll("[data-dresp]").forEach(function(b){b.onclick=function(){respondItem("decision",b.dataset.dresp,b.dataset.status);};});
}

function openSimpleCreate(kind) {
  var isH=kind==="handover";
  openModal('<h3>'+(isH?'New handover':'New decision')+'</h3><p>'+(isH?'Set exactly what is happening, where and when.':'Ask one clear question with an explicit response state.')+'</p><form id="simple-form" class="form-stack"><div class="field"><label>Title</label><input name="title" required></div>'+(isH?'<div class="field"><label>When</label><input name="scheduled_at" type="datetime-local" required></div><div class="field"><label>Location</label><input name="location" placeholder="School gate"></div>':'<div class="field"><label>Details</label><textarea name="details"></textarea></div><div class="field"><label>Reply deadline</label><input name="deadline" type="date"></div>')+'<button class="primary-button" type="submit">Create '+kind+'</button></form>',function(){
    document.getElementById("simple-form").onsubmit=async function(e){e.preventDefault();var fd=new FormData(e.target), payload={title:fd.get("title")};if(isH){payload.scheduled_at=fd.get("scheduled_at");payload.location=fd.get("location");}else{payload.details=fd.get("details");payload.deadline=fd.get("deadline");}try{await api("/api/"+(isH?"handovers":"decisions"),{method:"POST",json:payload});closeModal();render();toast((isH?"Handover":"Decision")+" created","success");}catch(err){toast(err.message,"error");}};
  });
}

function respondItem(kind,id,statusValue) {
  var label=statusValue.charAt(0).toUpperCase()+statusValue.slice(1);
  openModal('<h3>'+label+' '+kind+'</h3><p>Add an optional note. The response and timestamp will be recorded in the evidence timeline.</p><form id="response-form" class="form-stack"><div class="field"><label>Note</label><textarea name="note" placeholder="Optional"></textarea></div><button class="primary-button" type="submit">'+label+'</button></form>',function(){
    document.getElementById("response-form").onsubmit=async function(e){e.preventDefault();var fd=new FormData(e.target);try{await api("/api/"+(kind==="handover"?"handovers":"decisions")+"/"+id+"/respond",{method:"POST",json:{status:statusValue,response_note:fd.get("note")}});closeModal();render();toast("Response recorded","success");}catch(err){toast(err.message,"error");}};
  });
}

async function renderExpenses() {
  var items=await api("/api/expenses"),uid=state.me.user.id;
  document.getElementById("page").innerHTML='<section class="card"><div class="card-head"><div><h3>Shared expenses</h3><p>Receipts, split, request and status stay attached to the same record.</p></div><button class="primary-button" id="add-expense">New expense</button></div>'+(items.length?'<div class="list">'+items.map(function(x){return '<div class="list-item"><div class="list-main"><div class="list-title">'+esc(x.title)+' · '+money(x.amount_pence)+'</div><div class="list-sub">'+x.split_percent+'% requested from other parent'+(x.due_date?' · due '+fmtDate(x.due_date):'')+(x.receipt_path?' · <a href="/api/receipts/'+encodeURIComponent(x.receipt_path)+'" target="_blank">receipt</a>':'')+'</div></div><div class="inline-actions">'+status(x.status)+(x.status==="pending"&&x.creator_id!==uid?'<button class="tiny-button" data-eresp="'+x.id+'" data-status="approved">Approve</button><button class="tiny-button" data-eresp="'+x.id+'" data-status="declined">Decline</button>':'')+(x.status==="approved"?'<button class="tiny-button primary" data-eresp="'+x.id+'" data-status="paid">Mark paid</button>':'')+'</div></div>';}).join("")+'</div>':'<div class="empty"><strong>No expenses yet</strong>Add a cost with the receipt and requested split.</div>')+'</section>';
  document.getElementById("add-expense").onclick=openExpenseModal;
  document.querySelectorAll("[data-eresp]").forEach(function(b){b.onclick=async function(){try{await api("/api/expenses/"+b.dataset.eresp+"/respond",{method:"POST",json:{status:b.dataset.status}});renderExpenses();toast("Expense updated","success");}catch(e){toast(e.message,"error");}};});
}

function openExpenseModal() {
  openModal('<h3>New shared expense</h3><p>Keep the amount, split and receipt together so neither parent has to hunt through chat later.</p><form id="expense-form" class="form-stack"><div class="field"><label>What was it for?</label><input name="title" required placeholder="School trip"></div><div class="field"><label>Total amount</label><input name="amount" type="number" step="0.01" min="0.01" required placeholder="24.50"></div><div class="field"><label>Request from other parent (%)</label><input name="split_percent" type="number" min="0" max="100" value="50" required></div><div class="field"><label>Due date</label><input name="due_date" type="date"></div><div class="field"><label>Receipt</label><input name="receipt" type="file" accept=".png,.jpg,.jpeg,.webp,.pdf"></div><button class="primary-button" type="submit">Create expense</button></form>',function(){
    document.getElementById("expense-form").onsubmit=async function(e){e.preventDefault();var form=e.target,fd=new FormData(form);try{var r=await fetch("/api/expenses",{method:"POST",headers:{"X-CSRF-Token":state.me.csrf},body:fd});var data=await r.json();if(!r.ok)throw new Error(data.error||"Could not save expense");closeModal();render();toast("Expense created","success");}catch(err){toast(err.message,"error");}};
  });
}

function timelineHtml(items) {
  if(!items.length)return '<div class="empty"><strong>No evidence records yet</strong>Activity will appear here automatically.</div>';
  return '<div class="timeline">'+items.map(function(x){return '<div class="timeline-item"><div class="timeline-type">'+esc(x.entity_type)+' · '+esc(x.event_type)+'</div><div class="timeline-title">'+esc(x.summary.replace(/immutable/gi,"saved"))+'</div><div class="timeline-meta">'+fmt(x.created_at)+' · '+esc(x.actor_name||"System")+'</div></div>';}).join("")+'</div>';
}

async function renderEvidence() {
  var items=await api("/api/timeline?limit=500");
  var verify=await api("/api/messages/verify");
  document.getElementById("page").innerHTML='<div class="page-grid"><section class="card span-4"><div class="card-head"><div><h3>Message records</h3><p>Checking saved messages for changes.</p></div></div><div class="metric-value" style="color:var(--success)">'+(verify.verified?"Checked":"Warning")+'</div><div class="metric-note">'+verify.count+' saved message'+(verify.count===1?"":"s")+'</div><div class="warning-box">The app can detect changes to its saved messages. This does not mean automatic court admissibility.</div></section><section class="card span-8"><div class="card-head"><div><h3>Export evidence pack</h3><p>Messages and activity in one chronological PDF.</p></div></div><form id="export-form" class="form-stack"><div class="export-dates"><div class="field"><label>From</label><input name="start" type="date"></div><div class="field"><label>To</label><input name="end" type="date"></div></div><button class="primary-button" type="submit">Download PDF evidence pack</button></form></section><section class="card span-12"><div class="card-head"><div><h3>Evidence timeline</h3><p>Actions are automatically timestamped and cannot be edited through the app.</p></div></div>'+timelineHtml(items)+'</section></div>';
  document.getElementById("export-form").onsubmit=function(e){e.preventDefault();var fd=new FormData(e.target),q=new URLSearchParams();if(fd.get("start"))q.set("start",fd.get("start"));if(fd.get("end"))q.set("end",fd.get("end"));window.location="/api/evidence.pdf?"+q.toString();};
}

async function renderRules() {
  var items=await api("/api/rules");
  document.getElementById("page").innerHTML='<div class="page-grid"><section class="card span-7"><div class="card-head"><div><h3>Saved agreement rules</h3><p>Turn parts of your parenting agreement into visible rules instead of relying on memory.</p></div></div>'+(items.length?'<div class="list">'+items.map(function(x){return '<div class="list-item"><div class="list-main"><div class="list-title">'+esc(x.title)+'</div><div class="list-sub">'+esc(x.rule_type.replaceAll("_"," "))+' · '+esc(x.value_text)+'</div></div></div>';}).join("")+'</div>':'<div class="empty"><strong>No rules yet</strong>Add the important rules both parents should be able to see.</div>')+'</section><section class="card span-5"><div class="card-head"><div><h3>Add rule</h3><p>Holiday notice rules are actively checked when a holiday is added.</p></div></div><form id="rule-form" class="form-stack"><div class="field"><label>Rule name</label><input name="title" required placeholder="Holiday notice"></div><div class="field"><label>Type</label><select name="rule_type"><option value="holiday_notice_days">Holiday notice days</option><option value="handover_time">Usual handover time</option><option value="expense_split">Default expense split</option><option value="custom">Custom rule</option></select></div><div class="field"><label>Value</label><input name="value_text" required placeholder="28"></div><button class="primary-button" type="submit">Save rule</button></form></section></div>';
  document.getElementById("rule-form").onsubmit=async function(e){e.preventDefault();var fd=new FormData(e.target);try{await api("/api/rules",{method:"POST",json:{title:fd.get("title"),rule_type:fd.get("rule_type"),value_text:fd.get("value_text")}});renderRules();toast("Rule saved","success");}catch(err){toast(err.message,"error");}};
}

function renderSearch() {
  document.getElementById("page").innerHTML='<div class="search-box"><input id="global-search" class="search-input" autocomplete="off" placeholder="Search words, names, dates, amounts, receipt filenames…"><div id="search-results" class="search-results"><div class="empty"><strong>Search the family record</strong>Messages, events, child profiles, handovers, decisions, expenses, rules and activity.</div></div></div>';
  var input=document.getElementById("global-search"),timer;
  input.focus();
  input.oninput=function(){clearTimeout(timer);timer=setTimeout(async function(){var q=input.value.trim();if(q.length<2){document.getElementById("search-results").innerHTML='<div class="empty"><strong>Keep typing</strong>Enter at least two characters.</div>';return;}try{var items=await api("/api/search?q="+encodeURIComponent(q));document.getElementById("search-results").innerHTML=items.length?'<div class="list">'+items.map(function(x){return '<div class="list-item"><div class="list-main"><div class="search-type">'+esc(x.type)+'</div><div class="list-title">'+esc(x.title)+'</div><div class="list-sub">'+esc(x.detail||"")+' · '+fmt(x.created_at)+'</div></div></div>';}).join("")+'</div>':'<div class="empty"><strong>No matches</strong>Nothing in the family record matched that search.</div>';}catch(e){toast(e.message,"error");}},260);};
}

document.querySelectorAll(".auth-tab").forEach(function(b){b.onclick=function(){setAuthTab(b.dataset.authTab);};});
document.getElementById("auth-theme").onclick=cycleTheme;
document.getElementById("sidebar-theme").onclick=cycleTheme;
document.getElementById("modal-close").onclick=closeModal;
document.getElementById("modal").onclick=function(e){if(e.target===e.currentTarget)closeModal();};
document.getElementById("search-shortcut").innerHTML=icons.search;
document.getElementById("search-shortcut").onclick=function(){navigate("search");};
document.getElementById("login-form").onsubmit=async function(e){e.preventDefault();var fd=new FormData(e.target);try{state.me=await api("/api/auth/login",{method:"POST",json:{email:fd.get("email"),password:fd.get("password")}});showApp();render();}catch(err){toast(err.message,"error");}};
document.getElementById("register-form").onsubmit=async function(e){e.preventDefault();var fd=new FormData(e.target);try{state.me=await api("/api/auth/register",{method:"POST",json:{name:fd.get("name"),email:fd.get("email"),password:fd.get("password")}});showApp();render();toast("Your family space is ready","success");}catch(err){toast(err.message,"error");}};
document.getElementById("logout-button").onclick=async function(){try{await api("/api/auth/logout",{method:"POST",json:{}});}catch(e){}location.reload();};
bootstrap();
