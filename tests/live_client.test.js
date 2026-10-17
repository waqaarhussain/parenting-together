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
  const ctx={state:{page:'rules'},document:{getElementById:()=>container},render:async()=>{
    inputs=[{name:'title',value:'',checked:false},{name:'start',value:'',checked:false}];container.scrollTop=0;
  }};
  vm.createContext(ctx);
  vm.runInContext(source.slice(source.indexOf('async function refreshLivePage()'),source.indexOf('async function refreshLiveState(')),ctx);
  await ctx.refreshLivePage();
  assert.equal(inputs[0].value,'unsaved rule');assert.equal(inputs[1].value,'2026-10-01');assert.equal(container.scrollTop,47);
});

test('message notifications clear only while viewing the visible Messages page',async()=>{
  for(const [page,hidden,clears] of [['messages',false,true],['home',false,false],['messages',true,false]]){
    const calls=[];
    const items=[{id:7,notification_type:'message'},{id:6,notification_type:'event_created'}];
    const ctx={state:{me:{user:{id:1}},page},document:{hidden},lastNotificationRefresh:0,
      Date,updateNotificationBadge(){},api:async(path,options)=>{
        calls.push({path,options});
        if(options){assert.equal(options.json.message_through_id,7);return {ok:true};}
        return calls.length>1?{unread:1,items:[items[1]]}:{unread:2,items};
      }};
    vm.createContext(ctx);
    vm.runInContext(source.slice(source.indexOf('async function refreshNotifications('),source.indexOf('async function openNotifications(')),ctx);
    await ctx.refreshNotifications(true);
    assert.equal(calls.filter(call=>call.options).length,clears?1:0);
    assert.equal(ctx.state.notificationUnread,clears?1:2);
  }
});
