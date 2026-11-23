import test from 'node:test';
import assert from 'node:assert/strict';
import { createFamilyDraftReadClient } from '../src/api/family_draft_read.mjs';
const ids={school_id:'11111111-1111-4111-8111-111111111111',household_id:'22222222-2222-4222-8222-222222222222',academic_year_id:'33333333-3333-4333-8333-333333333333',application_id:'44444444-4444-4444-8444-444444444444',child_id:'55555555-5555-4555-8555-555555555555'};
const ok=body=>({ok:true,json:async()=>body});
const client=(fetcher,currentScope=()=>ids,syntheticOnly=true)=>createFamilyDraftReadClient({fetcher,currentScope,syntheticOnly});
const draft={id:ids.application_id,status:'DRAFT',school_id:ids.school_id,household_id:ids.household_id,academic_year_id:ids.academic_year_id};

test('no synthetic opt-in: no fetch',async()=>{
 let count=0;const c=client(async()=>{count++;return ok(draft)},()=>ids,false);
 await assert.rejects(c.readDraft(),/disabled/);assert.equal(count,0);
});
test('exact draft route uses cookie, GET and no token or CROWN headers',async()=>{
 let request;const c=client(async(url,options)=>{request={url,options};return ok(draft)});
 assert.equal((await c.readDraft()).id,ids.application_id);
 assert.deepEqual(request,{url:'/api/v1/schools/'+ids.school_id+'/households/'+ids.household_id+'/academic-years/'+ids.academic_year_id+'/aid-application/draft/',options:{method:'GET',credentials:'same-origin',redirect:'error',cache:'no-store',headers:{Accept:'application/json'}}});
});
test('invalid scope fails before transport',async()=>{
 let count=0;const c=client(async()=>{count++;return ok(draft)},()=>({...ids,school_id:'../bad'}));
 await assert.rejects(c.readDraft(),/scope unavailable/);assert.equal(count,0);
});
test('server-side scope mismatch is never returned',async()=>{
 const c=client(async()=>ok({...draft,school_id:'99999999-9999-4999-8999-999999999999'}));
 await assert.rejects(c.readDraft(),/scope mismatch/);
});
test('change in household while request pending rejects stale response',async()=>{
 let current={...ids};const c=client(async()=>{current={...current,household_id:'88888888-8888-4888-8888-888888888888'};return ok(draft)},()=>current);
 await assert.rejects(c.readDraft(),/context changed/);
});
test('change during JSON parsing rejects stale response',async()=>{
 let current={...ids};const c=client(async()=>({ok:true,json:async()=>{current={...current,school_id:'88888888-8888-4888-8888-888888888888'};return draft}}),()=>current);
 await assert.rejects(c.readDraft(),/context changed/);
});
test('403 and 404 both hide server errors',async()=>{
 for(const status of [403,404]){const c=client(async()=>({ok:false,status,json:async()=>({detail:'sensitive'})}));await assert.rejects(c.readDraft(),e=>e.message==='Family record unavailable');}
});
test('read children and selected students using exact read-only routes',async()=>{
 const calls=[];const c=client(async url=>{calls.push(url);return ok(url.endsWith('draft/students/')?{application_id:ids.application_id,student_ids:[ids.child_id]}:{household_id:ids.household_id,students:[{id:ids.child_id,first_name:'Fictional',last_name:'Child'}]})});
 assert.equal((await c.readChildren()).students[0].id,ids.child_id);
 assert.equal((await c.readSelectedChildren()).student_ids[0],ids.child_id);
 assert.equal(calls.length,2);
});
test('wrong-household children record denied',async()=>{
 const c=client(async()=>ok({household_id:'88888888-8888-4888-8888-888888888888',students:[]}));
 await assert.rejects(c.readChildren(),/scope mismatch/);
});
test('client surface contains no mutation capability',()=>{
 assert.deepEqual(Object.keys(client(async()=>ok({}))).sort(),['readChildren','readDraft','readHousehold','readSelectedChildren']);
});
