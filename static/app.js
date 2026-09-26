var state = { me: null, page: "home", cache: {}, chat: null, unread: 0, notificationUnread: 0, messageTarget: null, eventTarget: null, eventTargetAt: null, recordTarget: null, calendarEvents: [], calendarCursor: new Date(), theme: localStorage.getItem("pt-theme") || "system" };
var liveTimer = null;
var liveBusy = false;
var lastNotificationRefresh = 0;
var typingActive = false;
var typingIdleTimer = null;
var typingHeartbeat = null;
var appVersion = window.PT_APP_VERSION || "dev";
var appUpdatePending = false;
var appUpdateTimer = null;

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
  bell:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"/></svg>',
  down:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="m6 9 6 6 6-6"/></svg>',
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
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/static/sw.js?v=" + encodeURIComponent(appVersion), {updateViaCache:"none"}).catch(function(){});
  startAppUpdateWatcher();
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

async function checkForAppUpdate() {
  if (appUpdatePending) return;
  try {
    var response = await fetch("/api/version?t=" + Date.now(), {cache:"no-store", credentials:"same-origin"});
    if (!response.ok) return;
    var deployed = await response.json();
    if (!deployed.version || deployed.version === appVersion) return;
    appUpdatePending = true;
    window.location.replace("/?v=" + encodeURIComponent(deployed.version));
  } catch (e) {}
}

function startAppUpdateWatcher() {
  if (appUpdateTimer) return;
  checkForAppUpdate();
  appUpdateTimer = setInterval(checkForAppUpdate, 20000);
  document.addEventListener("visibilitychange", function(){
    if (!document.hidden) checkForAppUpdate();
  });
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
  if (!liveTimer) liveTimer = setInterval(refreshLiveState, 1000);
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
function updateNotificationBadge() {
  var badge=document.getElementById("notification-badge");
  if(!badge)return;
  badge.textContent=state.notificationUnread>99?"99+":String(state.notificationUnread);
  badge.classList.toggle("hidden",state.notificationUnread===0);
}
async function refreshNotifications(force) {
  if(!state.me)return null;
  if(!force&&Date.now()-lastNotificationRefresh<5000)return null;
  lastNotificationRefresh=Date.now();
  var data=await api("/api/notifications");
  state.notificationUnread=data.unread;
  updateNotificationBadge();
  return data;
}
async function openNotifications() {
  try{
    var data=await refreshNotifications(true) || await api("/api/notifications");
    var html='<div class="notification-head"><div><h3>Notifications</h3><p>Messages, plans, reminders and requests.</p></div>'+(data.unread?'<button id="mark-notifications-read" class="tiny-button">Mark all read</button>':'')+'</div>';
    html+=data.items.length?'<div class="notification-list">'+data.items.map(function(item){return '<button class="notification-item '+(item.read_at?'':'unread')+'" data-notification-id="'+item.id+'" data-target-type="'+esc(item.target_type||"")+'" data-target-id="'+esc(item.target_id||"")+'" data-target-value="'+esc(item.target_value||"")+'"><span class="notification-dot"></span><span><strong>'+esc(item.title)+'</strong><small>'+esc(item.body||"")+'</small><em>'+fmt(item.created_at)+'</em></span></button>';}).join("")+'</div>':'<div class="empty"><strong>No notifications yet</strong>New messages, reminders and requests will appear here.</div>';
    openModal(html,function(){
      var mark=document.getElementById("mark-notifications-read");
      if(mark)mark.onclick=async function(){await api("/api/notifications/read",{method:"POST",json:{}});state.notificationUnread=0;updateNotificationBadge();openNotifications();};
      document.querySelectorAll("[data-notification-id]").forEach(function(button){button.onclick=async function(){await api("/api/notifications/read",{method:"POST",json:{id:Number(button.dataset.notificationId)}});state.notificationUnread=Math.max(0,state.notificationUnread-(button.classList.contains("unread")?1:0));updateNotificationBadge();closeModal();openRecordTarget(button.dataset.targetType,Number(button.dataset.targetId)||null,button.dataset.targetValue||null);};});
    });
  }catch(e){toast(e.message,"error");}
}
async function refreshLiveState() {
  if (liveBusy || !state.me || document.hidden) return;
  liveBusy = true;
  try {
    if (state.page === "messages" && state.chat) await pollChat();
    var status = await api("/api/messages/status");
    state.unread = status.unread;
    updateUnreadBadges();
    await refreshNotifications(false);
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
    api("/api/rules"), api("/api/events")
  ]);
  return {handovers:data[0],decisions:data[1],expenses:data[2],rules:data[3],events:data[4]};
}

async function renderHome() {
  var d = await getAll();
  var pending = d.handovers.filter(function(x){return x.status==="pending";}).length + d.decisions.filter(function(x){return x.status==="pending";}).length + d.expenses.filter(function(x){return x.status==="pending";}).length;
  var upcoming=d.events.filter(function(x){return isFutureEvent(x.start_at);}).slice(0,8);
  var connected = state.me.members.length > 1;
  document.getElementById("page").innerHTML =
    '<div class="page-grid">'+
      '<section class="card welcome-card span-8"><p class="eyebrow">YOUR FAMILY SPACE</p><h3>Hi '+esc(state.me.user.name.split(" ")[0])+'.</h3><p>'+ (connected ? 'Everything shared between both parents stays organised, timestamped and easy to find.' : 'You are in solo mode. Start organising now, then connect the other parent whenever you are ready.') +'</p><div class="quick-actions"><button class="quick-action" id="qa-invite">'+(connected?'Family code':'Connect co-parent')+'</button><button class="quick-action" id="qa-child">Add child</button></div></section>'+
      '<section class="metric-card span-4"><div class="metric-label">Open items</div><div class="metric-value">'+pending+'</div><div class="metric-note">Handovers, decisions and expenses awaiting action.</div></section>'+
      '<section class="metric-card span-6"><div class="metric-label">Children</div><div class="metric-value">'+state.me.children.length+'</div><div class="metric-note">'+(state.me.children.length?state.me.children.map(function(c){return esc(c.name);}).join(" · "):"Add profiles to personalise the family space.")+'</div></section>'+
      '<section class="metric-card span-6"><div class="metric-label">Upcoming plans</div><div class="metric-value">'+upcoming.length+(d.events.filter(function(x){return isFutureEvent(x.start_at);}).length>8?"+":"")+'</div><div class="metric-note">Events that have not started yet.</div></section>'+
      '<section class="card span-12"><div class="card-head"><div><h3>Upcoming events</h3><p>Your next shared plans.</p></div><button class="tiny-button" id="home-calendar">View calendar</button></div>'+listEvents(upcoming)+'</section>'+
    '</div>';
  document.getElementById("qa-invite").onclick=openInviteModal;
  document.getElementById("qa-child").onclick=openChildModal;
  document.getElementById("home-calendar").onclick=function(){navigate("calendar");};
  bindEventLinks();
}

function listEvents(items) {
  if (!items.length) return '<div class="empty"><strong>Nothing coming up</strong>Add school runs, appointments, clubs or holidays.</div>';
  return '<div class="list">'+items.map(function(e){
    return '<button class="list-item event-list-item" data-event-open="'+e.id+'" data-event-start="'+esc(e.start_at)+'"><div class="list-main"><div class="list-title">'+esc(e.title)+'</div><div class="list-sub">'+fmt(e.start_at)+' · '+esc(e.category)+(e.is_recurring?' · repeats '+esc(e.recurrence):'')+'</div></div><span class="status">'+esc(e.category)+'</span></button>';
  }).join("")+'</div>';
}
function bindEventLinks(){document.querySelectorAll("[data-event-open]").forEach(function(button){button.onclick=function(){var id=Number(button.dataset.eventOpen),start=button.dataset.eventStart;if(state.page==="calendar"){var event=state.calendarEvents.find(function(item){return item.id===id&&item.start_at===start;})||state.calendarEvents.find(function(item){return item.id===id;});if(event)openEventModal(event);}else openRecordTarget("event",id,start);};});}

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
    chat.hasNewer=false;
    var jump=document.getElementById("jump-latest");
    if(jump)jump.classList.add("hidden");
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
  if (typingIdleTimer) clearTimeout(typingIdleTimer);
  if (typingHeartbeat) clearInterval(typingHeartbeat);
  typingIdleTimer = null;
  typingHeartbeat = null;
  if (!typingActive || !state.me) return;
  typingActive = false;
  api("/api/messages/typing", {method:"POST", json:{typing:false}}).catch(function(){});
}
function startTyping(input) {
  if (typingIdleTimer) clearTimeout(typingIdleTimer);
  if (!typingActive) {
    typingActive = true;
    api("/api/messages/typing", {method:"POST", json:{typing:true}}).catch(function(){});
  }
  if (!typingHeartbeat) {
    typingHeartbeat = setInterval(function(){
      if (typingActive && input.value.trim() && document.activeElement === input) {
        api("/api/messages/typing", {method:"POST", json:{typing:true}}).catch(function(){});
      }
    }, 3000);
  }
  typingIdleTimer = setTimeout(stopTyping, 1800);
}
async function renderMessages() {
  var targetId=state.messageTarget;
  var result = targetId ? await api("/api/messages?around="+targetId) : await api("/api/messages");
  var messages = Array.isArray(result) ? result : result.messages;
  var hasOlder = Array.isArray(result) ? messages.length===50 : result.has_older;
  var hasNewer = Array.isArray(result) ? false : result.has_newer;
  var verify = await api("/api/messages/verify");
  if (state.page !== "messages") return;
  state.chat = {messages:messages, hasOlder:hasOlder, hasNewer:hasNewer, loadingOlder:false, polling:false};
  document.getElementById("page").innerHTML =
    '<div class="chat-shell"><div class="chat-header"><div><strong>Family messages</strong><br><span>Sent messages cannot be edited or deleted.</span></div><span class="integrity"><i class="integrity-dot"></i>'+(verify.verified?"Records checked":"Record check failed")+'</span></div>'+
    '<div id="messages" class="messages"><div id="history-trigger"><button id="load-older" class="tiny-button'+(hasOlder?'':' hidden')+'" type="button">Load earlier messages</button></div>'+
    (messages.length?messages.map(messageHtml).join(""):'<div class="empty"><strong>No messages yet</strong>Start the conversation. Sent messages stay in the family record.</div>')+'</div>'+
    '<button id="jump-latest" class="jump-latest'+(hasNewer?'':' hidden')+'" type="button" aria-label="Jump to latest messages">'+icons.down+'<span>Latest</span></button>'+
    '<div class="compose-area"><div id="typing-indicator" class="typing-indicator hidden"></div><form id="message-form" class="chat-compose"><textarea name="body" maxlength="5000" placeholder="Write a message…" required></textarea><button class="send-button" aria-label="Send">'+icons.send+'</button></form></div></div>';
  var box = document.getElementById("messages");
  var jump=document.getElementById("jump-latest");
  if(targetId){
    var targetMessage=box.querySelector('[data-message-id="'+targetId+'"]');
    if(targetMessage){targetMessage.classList.add("message-target");targetMessage.scrollIntoView({block:"center"});}
  }else box.scrollTop = box.scrollHeight;
  state.messageTarget=null;
  box.addEventListener("scroll", function(){
    if (box.scrollTop < 50) loadOlderMessages();
    var away=box.scrollHeight-box.scrollTop-box.clientHeight>160;
    jump.classList.toggle("hidden",!state.chat.hasNewer&&!away);
    if (!away) refreshLiveState();
  });
  jump.onclick=function(){state.messageTarget=null;renderMessages();};
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
    startTyping(input);
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
  var cur=state.calendarCursor;
  var y=cur.getFullYear(),m=cur.getMonth();
  var first=new Date(y,m,1), start=new Date(y,m,1-first.getDay());
  var rangeEnd=new Date(start);rangeEnd.setDate(rangeEnd.getDate()+41);rangeEnd.setHours(23,59,59,999);
  var now=new Date(),upcomingEnd=new Date(now);upcomingEnd.setFullYear(upcomingEnd.getFullYear()+2);
  var loaded=await Promise.all([
    api("/api/events?start="+encodeURIComponent(start.toISOString())+"&end="+encodeURIComponent(rangeEnd.toISOString())),
    api("/api/events?start="+encodeURIComponent(now.toISOString())+"&end="+encodeURIComponent(upcomingEnd.toISOString()))
  ]);
  var events=loaded[0],upcoming=loaded[1].filter(function(x){return isFutureEvent(x.start_at);}).slice(0,8);
  state.calendarEvents=events.concat(upcoming.filter(function(item){return !events.some(function(existing){return existing.occurrence_key===item.occurrence_key;});}));
  var today=new Date();
  var cells="";
  for(var i=0;i<42;i++){
    var d=new Date(start);d.setDate(start.getDate()+i);
    var key=d.getFullYear()+"-"+String(d.getMonth()+1).padStart(2,"0")+"-"+String(d.getDate()).padStart(2,"0");
    var ev=events.filter(function(x){return String(x.start_at).slice(0,10)===key;});
    var cls="day"+(d.getMonth()!==m?" other":"")+(d.toDateString()===today.toDateString()?" today":"");
    cells+='<div class="'+cls+'"><div class="day-num">'+d.getDate()+'</div>'+ev.slice(0,3).map(function(x){var target=state.eventTarget===x.id&&(!state.eventTargetAt||String(x.start_at).slice(0,16)===String(state.eventTargetAt).slice(0,16));return '<button class="event-chip'+(target?' event-target':'')+'" data-event-open="'+x.id+'" data-event-start="'+esc(x.start_at)+'">'+esc(x.title)+'</button>';}).join("")+'</div>';
  }
  document.getElementById("page").innerHTML='<div class="calendar-wrap"><section class="calendar-card"><div class="calendar-head"><button class="tiny-button" id="cal-prev">‹</button><strong>'+cur.toLocaleDateString([],{month:"long",year:"numeric"})+'</strong><button class="tiny-button" id="cal-next">›</button></div><div class="calendar-grid">'+["Sun","Mon","Tue","Wed","Thu","Fri","Sat"].map(function(x){return '<div class="weekday">'+x+'</div>';}).join("")+cells+'</div></section><section class="card"><div class="card-head"><div><h3>Upcoming events</h3><p>School, appointments, clubs and holidays.</p></div><button class="tiny-button primary" id="cal-add">+ Add</button></div>'+listEvents(upcoming)+'</section></div>';
  document.getElementById("cal-prev").onclick=function(){state.calendarCursor=new Date(y,m-1,1);renderCalendar();};
  document.getElementById("cal-next").onclick=function(){state.calendarCursor=new Date(y,m+1,1);renderCalendar();};
  document.getElementById("cal-add").onclick=openEventModal;
  bindEventLinks();
  var highlighted=document.querySelector(".event-target");
  if(highlighted)highlighted.scrollIntoView({block:"center",behavior:"smooth"});
  state.eventTarget=null;state.eventTargetAt=null;
}

function openEventModal(existing) {
  var editing=existing&&existing.id;
  var startValue=editing?(existing.series_start_at||existing.start_at):"";
  var endValue=editing?(existing.series_end_at||""):"";
  var recurrence=editing?(existing.recurrence||"none"):"none";
  var category=editing?(existing.category||"general"):"general";
  function selected(value,current){return value===current?' selected':'';}
  openModal('<h3>'+(editing?'Edit event':'Add event')+'</h3><p>'+(editing&&existing.is_recurring?'Changes apply to the full repeating event.':'Plans appear in both parents’ calendars.')+'</p><form id="event-form" class="form-stack"><div class="field"><label>Title</label><input name="title" required placeholder="School pickup" value="'+esc(editing?existing.title:'')+'"></div><div class="field"><label>Type</label><select name="category"><option value="general"'+selected('general',category)+'>General</option><option value="school"'+selected('school',category)+'>School</option><option value="handover"'+selected('handover',category)+'>Handover</option><option value="appointment"'+selected('appointment',category)+'>Appointment</option><option value="club"'+selected('club',category)+'>Club</option><option value="holiday"'+selected('holiday',category)+'>Holiday</option></select></div><div class="event-time-grid"><div class="field"><label>Starts</label><input type="datetime-local" name="start_at" required value="'+esc(startValue)+'"></div><div class="field"><label>Ends <span>(optional)</span></label><input type="datetime-local" name="end_at" value="'+esc(endValue)+'"></div></div><div class="field"><label>Remind me this many minutes before</label><input type="number" name="reminder_minutes" min="0" max="10080" list="reminder-times" value="'+(editing?Number(existing.reminder_minutes||0):15)+'"><datalist id="reminder-times"><option value="0"><option value="15"><option value="30"><option value="60"><option value="120"><option value="1440"><option value="10080"></datalist><small>Examples: 15, 30, 60, 1440 for one day, or any time up to one week.</small></div><div class="field"><label>Repeat</label><select name="recurrence"><option value="none"'+selected('none',recurrence)+'>Does not repeat</option><option value="daily"'+selected('daily',recurrence)+'>Daily</option><option value="weekly"'+selected('weekly',recurrence)+'>Weekly</option><option value="monthly"'+selected('monthly',recurrence)+'>Monthly</option></select></div><div id="repeat-until-field" class="field"><label>Repeat until</label><input type="date" name="recurrence_until" value="'+esc(editing?(existing.recurrence_until||''):'')+'"></div><div class="field"><label>Notes</label><textarea name="notes" placeholder="Anything both parents need to know">'+esc(editing?(existing.notes||''):'')+'</textarea></div><div class="modal-actions"><button class="primary-button" type="submit">'+(editing?'Save changes':'Add to calendar')+'</button>'+(editing?'<button class="danger-button" id="cancel-event" type="button">Cancel event</button>':'')+'</div></form>',function(){
    var form=document.getElementById("event-form"),repeat=form.elements.namedItem("recurrence"),until=document.getElementById("repeat-until-field");
    function toggleUntil(){var repeats=repeat.value!=="none";until.classList.toggle("hidden",!repeats);form.elements.namedItem("recurrence_until").required=repeats;}
    repeat.onchange=toggleUntil;toggleUntil();
    form.onsubmit=async function(e){e.preventDefault();var fd=new FormData(form),payload={title:fd.get("title"),category:fd.get("category"),start_at:fd.get("start_at"),end_at:fd.get("end_at"),reminder_minutes:Number(fd.get("reminder_minutes")||0),recurrence:fd.get("recurrence"),recurrence_until:fd.get("recurrence_until"),timezone_offset:new Date().getTimezoneOffset(),notes:fd.get("notes")};try{var r=await api(editing?"/api/events/"+existing.id:"/api/events",{method:editing?"PUT":"POST",json:payload});closeModal();await renderCalendar();if(r.warnings&&r.warnings.length)toast(r.warnings[0],"error");else toast(editing?"Event updated":"Event added","success");}catch(err){toast(err.message,"error");}};
    var cancel=document.getElementById("cancel-event");if(cancel)cancel.onclick=async function(){if(!confirm("Cancel this event"+(existing.is_recurring?" and all of its repeats":"")+"?"))return;try{await api("/api/events/"+existing.id,{method:"DELETE",json:{}});closeModal();await renderCalendar();toast("Event cancelled","success");}catch(err){toast(err.message,"error");}};
  });
}

async function renderHandovers() {
  var items=await api("/api/handovers");
  var uid=state.me.user.id;
  document.getElementById("page").innerHTML='<div class="page-grid"><section class="card span-12"><div class="card-head"><div><h3>Handover record</h3><p>Make pickups and drop-offs explicit, not buried inside chat.</p></div><button class="primary-button" id="add-handover">New handover</button></div>'+(items.length?'<div class="list">'+items.map(function(x){return '<div class="list-item" data-record-type="handover" data-record-id="'+x.id+'"><div class="list-main"><div class="list-title">'+esc(x.title)+'</div><div class="list-sub">'+fmt(x.scheduled_at)+(x.location?' · '+esc(x.location):'')+' · requested by '+esc(x.creator_name)+(x.response_note?' · '+esc(x.response_note):'')+'</div></div><div class="inline-actions">'+status(x.status)+(x.status==="pending"&&x.creator_id!==uid?'<button class="tiny-button" data-hresp="'+x.id+'" data-status="accepted">Accept</button><button class="tiny-button" data-hresp="'+x.id+'" data-status="declined">Decline</button><button class="tiny-button" data-hresp="'+x.id+'" data-status="countered">Counter</button>':'')+(x.status==="accepted"?'<button class="tiny-button primary" data-complete="'+x.id+'">Mark complete</button>':'')+'</div></div>';}).join("")+'</div>':'<div class="empty"><strong>No handovers yet</strong>Create a structured pickup or drop-off request.</div>')+'</section></div>';
  document.getElementById("add-handover").onclick=function(){openSimpleCreate("handover");};
  document.querySelectorAll("[data-hresp]").forEach(function(b){b.onclick=function(){respondItem("handover",b.dataset.hresp,b.dataset.status);};});
  document.querySelectorAll("[data-complete]").forEach(function(b){b.onclick=async function(){try{await api("/api/handovers/"+b.dataset.complete+"/complete",{method:"POST",json:{}});renderHandovers();toast("Handover completion recorded","success");}catch(e){toast(e.message,"error");}};});
  focusRecordTarget();
}

async function renderDecisions() {
  var items=await api("/api/decisions"),uid=state.me.user.id;
  document.getElementById("page").innerHTML='<section class="card"><div class="card-head"><div><h3>Structured decisions</h3><p>School trips, clubs, passports and other choices get a clear answer and permanent history.</p></div><button class="primary-button" id="add-decision">New decision</button></div>'+(items.length?'<div class="list">'+items.map(function(x){return '<div class="list-item" data-record-type="decision" data-record-id="'+x.id+'"><div class="list-main"><div class="list-title">'+esc(x.title)+'</div><div class="list-sub">'+esc(x.details||"No details")+(x.deadline?' · Reply by '+fmtDate(x.deadline):'')+(x.response_note?' · '+esc(x.response_note):'')+'</div></div><div class="inline-actions">'+status(x.status)+(x.status==="pending"&&x.creator_id!==uid?'<button class="tiny-button" data-dresp="'+x.id+'" data-status="accepted">Accept</button><button class="tiny-button" data-dresp="'+x.id+'" data-status="declined">Decline</button><button class="tiny-button" data-dresp="'+x.id+'" data-status="countered">Counter</button>':'')+'</div></div>';}).join("")+'</div>':'<div class="empty"><strong>No decisions yet</strong>Create a decision instead of arguing through a long message thread.</div>')+'</section>';
  document.getElementById("add-decision").onclick=function(){openSimpleCreate("decision");};
  document.querySelectorAll("[data-dresp]").forEach(function(b){b.onclick=function(){respondItem("decision",b.dataset.dresp,b.dataset.status);};});
  focusRecordTarget();
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
  document.getElementById("page").innerHTML='<section class="card"><div class="card-head"><div><h3>Shared expenses</h3><p>Receipts, split, request and status stay attached to the same record.</p></div><button class="primary-button" id="add-expense">New expense</button></div>'+(items.length?'<div class="list">'+items.map(function(x){return '<div class="list-item" data-record-type="expense" data-record-id="'+x.id+'"><div class="list-main"><div class="list-title">'+esc(x.title)+' · '+money(x.amount_pence)+'</div><div class="list-sub">'+x.split_percent+'% requested from other parent'+(x.due_date?' · due '+fmtDate(x.due_date):'')+(x.receipt_path?' · <a href="/api/receipts/'+encodeURIComponent(x.receipt_path)+'" target="_blank">receipt</a>':'')+'</div></div><div class="inline-actions">'+status(x.status)+(x.status==="pending"&&x.creator_id!==uid?'<button class="tiny-button" data-eresp="'+x.id+'" data-status="approved">Approve</button><button class="tiny-button" data-eresp="'+x.id+'" data-status="declined">Decline</button>':'')+(x.status==="approved"?'<button class="tiny-button primary" data-eresp="'+x.id+'" data-status="paid">Mark paid</button>':'')+'</div></div>';}).join("")+'</div>':'<div class="empty"><strong>No expenses yet</strong>Add a cost with the receipt and requested split.</div>')+'</section>';
  document.getElementById("add-expense").onclick=openExpenseModal;
  document.querySelectorAll("[data-eresp]").forEach(function(b){b.onclick=async function(){try{await api("/api/expenses/"+b.dataset.eresp+"/respond",{method:"POST",json:{status:b.dataset.status}});renderExpenses();toast("Expense updated","success");}catch(e){toast(e.message,"error");}};});
  focusRecordTarget();
}

function openExpenseModal() {
  openModal('<h3>New shared expense</h3><p>Keep the amount, split and receipt together so neither parent has to hunt through chat later.</p><form id="expense-form" class="form-stack"><div class="field"><label>What was it for?</label><input name="title" required placeholder="School trip"></div><div class="field"><label>Total amount</label><input name="amount" type="number" step="0.01" min="0.01" required placeholder="24.50"></div><div class="field"><label>Request from other parent (%)</label><input name="split_percent" type="number" min="0" max="100" value="50" required></div><div class="field"><label>Due date</label><input name="due_date" type="date"></div><div class="field"><label>Receipt</label><input name="receipt" type="file" accept=".png,.jpg,.jpeg,.webp,.pdf"></div><button class="primary-button" type="submit">Create expense</button></form>',function(){
    document.getElementById("expense-form").onsubmit=async function(e){e.preventDefault();var form=e.target,fd=new FormData(form);try{var r=await fetch("/api/expenses",{method:"POST",headers:{"X-CSRF-Token":state.me.csrf},body:fd});var data=await r.json();if(!r.ok)throw new Error(data.error||"Could not save expense");closeModal();render();toast("Expense created","success");}catch(err){toast(err.message,"error");}};
  });
}

function timelineHtml(items) {
  if(!items.length)return '<div class="empty"><strong>No recent activity yet</strong>Activity will appear here automatically.</div>';
  return '<div class="timeline">'+items.map(function(x){return '<div class="timeline-item" data-record-type="activity" data-record-id="'+x.id+'"><div class="timeline-type">'+esc(x.entity_type)+' · '+esc(x.event_type)+'</div><div class="timeline-title">'+esc(x.summary.replace(/immutable/gi,"saved"))+'</div>'+(x.detail?'<div class="timeline-detail">'+esc(x.detail)+'</div>':'')+'<div class="timeline-meta">'+fmt(x.created_at)+' · '+esc(x.actor_name||"System")+'</div></div>';}).join("")+'</div>';
}

async function renderEvidence() {
  var items=await api("/api/timeline?limit=500");
  var verify=await api("/api/messages/verify");
  document.getElementById("page").innerHTML='<div class="page-grid"><section class="card span-4"><div class="card-head"><div><h3>Message records</h3><p>Checking saved messages for changes.</p></div></div><div class="metric-value" style="color:var(--success)">'+(verify.verified?"Checked":"Warning")+'</div><div class="metric-note">'+verify.count+' saved message'+(verify.count===1?"":"s")+'</div><div class="warning-box">The app can detect changes to its saved messages. This does not mean automatic court admissibility.</div></section><section class="card span-8"><div class="card-head"><div><h3>Export Messages</h3><p>Download messages from any date range as a PDF.</p></div></div><form id="export-form" class="form-stack"><div class="export-dates"><div class="field"><label>From</label><input name="start" type="date"></div><div class="field"><label>To</label><input name="end" type="date"></div></div><button class="primary-button" type="submit">Download messages</button></form></section><section class="card span-12"><div class="card-head"><div><h3>Recent activity</h3><p>Actions are automatically timestamped and cannot be edited through the app.</p></div></div>'+timelineHtml(items)+'</section></div>';
  var exportForm=document.getElementById("export-form"),fromDate=exportForm.elements.namedItem("start"),toDate=exportForm.elements.namedItem("end");
  fromDate.onchange=function(){toDate.min=fromDate.value;if(toDate.value&&toDate.value<fromDate.value)toDate.value=fromDate.value;};
  exportForm.onsubmit=function(e){e.preventDefault();var fd=new FormData(e.target),q=new URLSearchParams();if(fd.get("start")&&fd.get("end")&&fd.get("start")>fd.get("end")){toast("The From date must be before the To date.","error");return;}if(fd.get("start"))q.set("start",fd.get("start"));if(fd.get("end"))q.set("end",fd.get("end"));window.location="/api/evidence.pdf?"+q.toString();};
  focusRecordTarget();
}

async function renderRules() {
  var items=await api("/api/rules");
  document.getElementById("page").innerHTML='<div class="page-grid"><section class="card span-7"><div class="card-head"><div><h3>Saved agreement rules</h3><p>Turn parts of your parenting agreement into visible rules instead of relying on memory.</p></div></div>'+(items.length?'<div class="list">'+items.map(function(x){return '<div class="list-item" data-record-type="rule" data-record-id="'+x.id+'"><div class="list-main"><div class="list-title">'+esc(x.title)+'</div><div class="list-sub">'+esc(x.rule_type.replaceAll("_"," "))+' · '+esc(x.value_text)+'</div></div></div>';}).join("")+'</div>':'<div class="empty"><strong>No rules yet</strong>Add the important rules both parents should be able to see.</div>')+'</section><section class="card span-5"><div class="card-head"><div><h3>Add rule</h3><p>Holiday notice rules are actively checked when a holiday is added.</p></div></div><form id="rule-form" class="form-stack"><div class="field"><label>Rule name</label><input name="title" required placeholder="Holiday notice"></div><div class="field"><label>Type</label><select name="rule_type"><option value="holiday_notice_days">Holiday notice days</option><option value="handover_time">Usual handover time</option><option value="expense_split">Default expense split</option><option value="custom">Custom rule</option></select></div><div class="field"><label>Value</label><input name="value_text" required placeholder="28"></div><button class="primary-button" type="submit">Save rule</button></form></section></div>';
  document.getElementById("rule-form").onsubmit=async function(e){e.preventDefault();var fd=new FormData(e.target);try{await api("/api/rules",{method:"POST",json:{title:fd.get("title"),rule_type:fd.get("rule_type"),value_text:fd.get("value_text")}});renderRules();toast("Rule saved","success");}catch(err){toast(err.message,"error");}};
  focusRecordTarget();
}

function focusRecordTarget(){
  if(!state.recordTarget)return;
  var target=document.querySelector('[data-record-type="'+state.recordTarget.type+'"][data-record-id="'+state.recordTarget.id+'"]');
  if(target){target.classList.add("record-target");target.scrollIntoView({block:"center",behavior:"smooth"});}
  state.recordTarget=null;
}
function openRecordTarget(type,id,targetValue){
  if(type==="message"){state.messageTarget=id;navigate("messages");return;}
  if(type==="event"){
    var date=new Date(targetValue);
    if(!isNaN(date))state.calendarCursor=new Date(date.getFullYear(),date.getMonth(),1);
    state.eventTarget=id;state.eventTargetAt=targetValue;navigate("calendar");return;
  }
  var pagesByType={handover:"handovers",decision:"decisions",expense:"expenses",rule:"rules",activity:"evidence",child:"home",home:"home",family:"home"};
  state.recordTarget=id&&["handover","decision","expense","rule","activity"].includes(type)?{type:type,id:id}:null;
  navigate(pagesByType[type]||"home");
}

function renderSearch() {
  document.getElementById("page").innerHTML='<div class="search-box"><input id="global-search" class="search-input" autocomplete="off" placeholder="Search words, names, dates, amounts, receipt filenames…"><div id="search-results" class="search-results"><div class="empty"><strong>Search the family record</strong>Messages, events, child profiles, handovers, decisions, expenses, rules and activity.</div></div></div>';
  var input=document.getElementById("global-search"),timer;
  input.focus();
  input.oninput=function(){clearTimeout(timer);timer=setTimeout(async function(){var q=input.value.trim();if(q.length<2){document.getElementById("search-results").innerHTML='<div class="empty"><strong>Keep typing</strong>Enter at least two characters.</div>';return;}try{var items=await api("/api/search?q="+encodeURIComponent(q)),results=document.getElementById("search-results");results.innerHTML=items.length?'<div class="list">'+items.map(function(x){return '<button class="list-item search-result" data-result-type="'+esc(x.type)+'" data-result-id="'+x.id+'" data-result-value="'+esc(x.target_at||'')+'"><div class="list-main"><div class="search-type">'+esc(x.type)+'</div><div class="list-title">'+esc(x.title)+'</div><div class="list-sub">'+esc(x.detail||"")+' · '+fmt(x.created_at)+'</div></div><span class="result-arrow">›</span></button>';}).join("")+'</div>':'<div class="empty"><strong>No matches</strong>Nothing in the family record matched that search.</div>';results.querySelectorAll("[data-result-type]").forEach(function(button){button.onclick=function(){openRecordTarget(button.dataset.resultType,Number(button.dataset.resultId),button.dataset.resultValue||null);};});}catch(e){toast(e.message,"error");}},260);};
}

document.querySelectorAll(".auth-tab").forEach(function(b){b.onclick=function(){setAuthTab(b.dataset.authTab);};});
document.getElementById("auth-theme").onclick=cycleTheme;
document.getElementById("sidebar-theme").onclick=cycleTheme;
document.getElementById("modal-close").onclick=closeModal;
document.getElementById("modal").onclick=function(e){if(e.target===e.currentTarget)closeModal();};
document.getElementById("search-shortcut").innerHTML=icons.search;
document.getElementById("search-shortcut").onclick=function(){navigate("search");};
document.getElementById("notification-button").insertAdjacentHTML("afterbegin",icons.bell);
document.getElementById("notification-button").onclick=openNotifications;
document.getElementById("login-form").onsubmit=async function(e){e.preventDefault();var fd=new FormData(e.target);try{state.me=await api("/api/auth/login",{method:"POST",json:{email:fd.get("email"),password:fd.get("password")}});showApp();render();}catch(err){toast(err.message,"error");}};
document.getElementById("register-form").onsubmit=async function(e){e.preventDefault();var fd=new FormData(e.target);try{state.me=await api("/api/auth/register",{method:"POST",json:{name:fd.get("name"),email:fd.get("email"),password:fd.get("password")}});showApp();render();toast("Your family space is ready","success");}catch(err){toast(err.message,"error");}};
document.getElementById("logout-button").onclick=async function(){try{await api("/api/auth/logout",{method:"POST",json:{}});}catch(e){}location.reload();};
bootstrap();
