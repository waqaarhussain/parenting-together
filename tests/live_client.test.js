const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('static/app.js','utf8');

function client(){
  const intervals=new Map(),timeouts=new Map(),events={},windowEvents={},streams=[],refreshes=[];
  let serial=0;
  class EventSource {
    constructor(url){this.url=url;this.handlers={};this.readyState=0;streams.push(this);}
    addEventListener(name,fn){this.handlers[name]=fn;}
    close(){this.closed=true;this.readyState=2;}
  }
  const document={hidden:false,addEventListener:(name,fn)=>events[name]=fn};
  const window={EventSource,addEventListener:(name,fn)=>windowEvents[name]=fn};
  const context={state:{me:{user:{id:1}}},liveTimer:null,liveSource:null,liveDebounce:null,
    liveTables:new Set(),EventSource,document,window,appVersion:'same',checkForAppUpdate(){},
    stopTyping(){},refreshLiveState:tables=>refreshes.push(tables),
    setInterval:(fn,delay)=>{const id=++serial;intervals.set(id,{fn,delay});return id;},
    clearInterval:id=>intervals.delete(id),setTimeout:(fn,delay)=>{const id=++serial;timeouts.set(id,{fn,delay});return id;},
    clearTimeout:id=>timeouts.delete(id)};
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('function stopLiveUpdates()'),source.indexOf('async function refreshLivePage()')),context);
  function flush(){for(const [id,timer] of [...timeouts]){timeouts.delete(id);timer.fn();}}
  return {context,intervals,timeouts,events,streams,refreshes,flush};
}

test('one stream replaces idle polling and coalesces event bursts',()=>{
  const c=client();c.context.startLiveUpdates();c.context.startLiveUpdates();
  assert.equal(c.streams.length,1);
  assert.equal([...c.intervals.values()][0].delay,30000);
  c.streams[0].onopen();c.flush();
  assert.equal(c.intervals.size,0);
  c.refreshes.length=0;
  for(let i=0;i<20;i++)c.streams[0].handlers.change({data:JSON.stringify({tables:['messages']})});
  assert.equal(c.timeouts.size,1);c.flush();
  assert.equal(c.refreshes.length,1);
  assert.deepEqual(Array.from(c.refreshes[0]),['messages']);
});

test('background cleanup and foreground catch-up reopen one connection',()=>{
  const c=client();c.context.startLiveUpdates();c.streams[0].onopen();c.flush();
  c.context.document.hidden=true;c.events.visibilitychange();
  assert(c.streams[0].closed);assert.equal(c.intervals.size,0);assert.equal(c.timeouts.size,0);
  c.context.document.hidden=false;c.events.visibilitychange();c.flush();
  assert.equal(c.streams.length,2);assert(c.refreshes.length>=2);
});

test('connection failure activates one slow fallback and retries closed streams',()=>{
  const c=client();c.context.startLiveUpdates();c.streams[0].onopen();c.flush();
  c.streams[0].onerror();c.streams[0].onerror();assert.equal(c.intervals.size,1);
  c.streams[0].readyState=2;[...c.intervals.values()][0].fn();
  assert.equal(c.streams.length,2);assert.equal(c.intervals.size,1);
  c.streams[1].onopen();assert.equal(c.intervals.size,0);
});

test('browsers without EventSource retain the slower refresh',()=>{
  const c=client();c.context.window.EventSource=null;c.context.startLiveUpdates();
  assert.equal(c.streams.length,0);assert.equal(c.intervals.size,1);
  [...c.intervals.values()][0].fn();assert.equal(c.refreshes.length,1);
});

test('live page refresh preserves unsent form values and scroll position',async()=>{
  let inputs=[{name:'title',value:'unsaved rule',checked:false},{name:'start',value:'2026-10-01',checked:false}];
  const container={scrollTop:47,querySelectorAll:()=>inputs};
  const ctx={state:{page:'rules'},document:{getElementById:()=>container},render:async(background)=>{
    assert.equal(background,true);
    inputs=[{name:'title',value:'',checked:false},{name:'start',value:'',checked:false}];container.scrollTop=0;
  }};
  vm.createContext(ctx);
  vm.runInContext(source.slice(source.indexOf('async function refreshLivePage()'),source.indexOf('async function refreshLiveState(')),ctx);
  await ctx.refreshLivePage();
  assert.equal(inputs[0].value,'unsaved rule');assert.equal(inputs[1].value,'2026-10-01');assert.equal(container.scrollTop,47);
});

test('visible section clears its own alerts while other sections and hidden apps retain them',async()=>{
  const sections={messages:'message',calendar:'event',handovers:'handover',decisions:'decision',rules:'rule',expenses:'expense',evidence:'activity',home:'home'};
  for(const [page,target] of Object.entries(sections)){
    for(const hidden of [false,true]){
      const calls=[];
      const items=[{id:7,target_type:target},{id:6,target_type:'unrelated'}];
      const ctx={state:{me:{user:{id:1}},page},document:{hidden},lastNotificationRefresh:0,
        Date,updateNotificationBadge(){},api:async(path,options)=>{
          calls.push({path,options});
          if(options){assert.equal(options.json.through_id,7);assert.equal(options.json.page,page);return {ok:true};}
          return calls.length>1?{unread:1,items:[items[1]]}:{unread:2,items};
        }};
      vm.createContext(ctx);
      vm.runInContext(source.slice(source.indexOf('async function refreshNotifications('),source.indexOf('async function openNotifications(')),ctx);
      await ctx.refreshNotifications(true);
      assert.equal(calls.filter(call=>call.options).length,hidden?0:1);
      assert.equal(ctx.state.notificationUnread,hidden?2:1);
    }
  }
  const ctx={state:{me:{},page:'calendar'},document:{hidden:false},lastNotificationRefresh:0,
    Date,updateNotificationBadge(){},api:async(path,options)=>{
      assert.equal(options,undefined);
      return {unread:2,items:[{id:7,target_type:'message'},{id:6,target_type:'rule'}]};
    }};
  vm.createContext(ctx);
  vm.runInContext(source.slice(source.indexOf('async function refreshNotifications('),source.indexOf('async function openNotifications(')),ctx);
  await ctx.refreshNotifications(true);
  assert.equal(ctx.state.notificationUnread,2);
});

function sender(api,pollChat){
  const errors=[],button={disabled:false},input={value:'test 1'},form={querySelector:()=>button};
  let refreshes=0;
  const ctx={api,pollChat,stopTyping(){},toast:message=>errors.push(message),scheduleLiveRefresh:()=>refreshes++};
  vm.createContext(ctx);
  vm.runInContext(source.slice(source.indexOf('async function sendChatMessage('),source.indexOf('async function loadOlderMessages(')),ctx);
  return {ctx,errors,button,input,form,get refreshes(){return refreshes;}};
}

test('accepted sends survive refresh errors without a false send failure or resending',async()=>{
  let sends=0;
  const c=sender(async()=>{sends++;},async()=>{throw new Error('refresh failed');});
  await c.ctx.sendChatMessage(c.form,c.input);
  assert.equal(sends,1);assert.equal(c.input.value,'');assert.equal(c.errors.length,0);
  assert.equal(c.refreshes,1);assert.equal(c.button.disabled,false);
});

test('failed sends retain the draft and allow a deliberate retry',async()=>{
  let polls=0;
  const c=sender(async()=>{throw new Error('send failed');},async()=>polls++);
  await c.ctx.sendChatMessage(c.form,c.input);
  assert.equal(c.input.value,'test 1');assert.deepEqual(c.errors,['send failed']);
  assert.equal(c.button.disabled,false);assert.equal(polls,0);
});

test('rapid submissions do not duplicate a pending send or erase the next draft',async()=>{
  let finish,sends=0;
  const c=sender(()=>{sends++;return new Promise(resolve=>finish=resolve);},async()=>{});
  const first=c.ctx.sendChatMessage(c.form,c.input);
  c.input.value='test 2';
  await c.ctx.sendChatMessage(c.form,c.input);
  assert.equal(sends,1);finish();await first;
  assert.equal(c.input.value,'test 2');assert.equal(c.button.disabled,false);
});

test('forced chat refresh waits for the in-flight read then fetches newly sent messages',async()=>{
  let complete,calls=0;
  const appended=[];
  const chat={messages:[{id:1}],polling:false};
  const box={scrollHeight:100,scrollTop:100,clientHeight:100,querySelector:()=>null,
    insertAdjacentHTML:(_,html)=>appended.push(html)};
  const ctx={state:{chat,page:'messages'},document:{getElementById:id=>id==='messages'?box:null},
    messageHtml:message=>String(message.id),api:()=>{
      calls++;
      if(calls===1)return new Promise(resolve=>complete=resolve);
      return Promise.resolve([{id:2}]);
    }};
  vm.createContext(ctx);
  vm.runInContext(source.slice(source.indexOf('async function pollChat('),source.indexOf('async function sendChatMessage(')),ctx);
  const initial=ctx.pollChat();const forced=ctx.pollChat(true);
  assert.equal(calls,1);complete([]);await initial;await forced;
  assert.equal(calls,2);assert.equal(chat.polling,false);
  assert.deepEqual(chat.messages.map(m=>m.id),[1,2]);assert.deepEqual(appended,['2']);
});

test('incoming messages update activity but do not redraw Home or unrelated sections',()=>{
  const ctx={};vm.createContext(ctx);
  vm.runInContext(source.slice(source.indexOf('function livePageNeedsRefresh('),source.indexOf('async function refreshLiveState(')),ctx);
  const messageChange=['messages','audit','notifications'];
  for(const page of ['home','handovers','decisions','rules','expenses'])assert.equal(ctx.livePageNeedsRefresh(page,messageChange),false);
  assert.equal(ctx.livePageNeedsRefresh('evidence',messageChange),true);
  for(const table of ['events','rules','handovers','decisions','expenses','children'])assert.equal(ctx.livePageNeedsRefresh('home',[table]),true);
  for(const page of ['home','handovers','decisions','rules','expenses','evidence']){
    assert.equal(ctx.livePageNeedsRefresh(page,['all']),true);
    assert.equal(ctx.livePageNeedsRefresh(page,['family_members']),true);
    assert.equal(ctx.livePageNeedsRefresh(page),true);
  }
});

test('background rendering keeps existing content during loading and failed refreshes',async()=>{
  let complete;
  const writes=[],page={};let html='existing home';
  Object.defineProperty(page,'innerHTML',{get:()=>html,set:value=>{writes.push(value);html=value;}});
  const ctx={state:{page:'home'},document:{getElementById:()=>page},
    setPageMode(){throw Error('background refresh must not reset layout');},
    setHeading(){throw Error('background refresh must not reset heading');},
    renderHome:()=>new Promise(resolve=>complete=()=>{page.innerHTML='updated home';resolve();})};
  vm.createContext(ctx);
  vm.runInContext(source.slice(source.indexOf('async function render('),source.indexOf('async function getAll(')),ctx);
  const pending=ctx.render(true);
  assert.equal(html,'existing home');assert.deepEqual(writes,[]);
  complete();await pending;assert.deepEqual(writes,['updated home']);
  ctx.renderHome=async()=>{throw Error('temporary connection failure');};
  await assert.rejects(ctx.render(true),/temporary connection failure/);
  assert.equal(html,'updated home');assert.equal(writes.length,1);
});

test('busy live refresh retains changed tables without escalating to a full-page refresh',async()=>{
  const c=client();Object.assign(c.context,{liveBusy:true,liveRefreshPending:false});
  vm.runInContext(source.slice(source.indexOf('async function refreshLiveState('),source.indexOf('async function navigate(')),c.context);
  await c.context.refreshLiveState(['messages','notifications']);
  assert.equal(c.context.liveRefreshPending,true);
  assert.deepEqual(Array.from(c.context.liveTables),['messages','notifications']);
  // The queued refresh passes its accumulated table names through unchanged.
  const received=[];c.context.refreshLiveState=tables=>received.push(Array.from(tables));
  c.context.scheduleLiveRefresh([]);c.flush();
  assert.deepEqual(received,[['messages','notifications']]);
});

test('incoming message refresh updates badges while leaving Home content alone',async()=>{
  const me={authenticated:true,family:{id:1,name:'Family'},members:[],children:[]};
  let badgeUpdates=0,notificationUpdates=0,redraws=0;
  const ctx={state:{me,page:'home'},liveBusy:false,liveRefreshPending:false,
    liveTables:new Set(),document:{hidden:false,getElementById:()=>({innerHTML:''})},
    api:async url=>url==='/api/me'?me:{unread:2,reads:{}},
    updateUnreadBadges:()=>badgeUpdates++,refreshNotifications:async()=>notificationUpdates++,
    refreshLivePage:async()=>redraws++,
    scheduleLiveRefresh(){},showAuth(){throw Error('unexpected logout');}};
  vm.createContext(ctx);
  vm.runInContext(source.slice(source.indexOf('function livePageNeedsRefresh('),source.indexOf('async function navigate(')),ctx);
  await ctx.refreshLiveState(['messages','audit','notifications']);
  assert.equal(ctx.state.unread,2);assert.equal(badgeUpdates,1);assert.equal(notificationUpdates,1);assert.equal(redraws,0);
  assert.equal(ctx.liveBusy,false);
});
