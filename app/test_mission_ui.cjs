/* Synthetic DOM/JavaScript contract test; this is not browser visual QA. */
const fs=require('fs'),vm=require('vm'),assert=require('assert');
class Element {
  constructor(){this.value='';this.innerHTML='';this.textContent='';this.style={};this.checked=false;this.classList={toggle(){},remove(){},add(){}};this.options=[];}
  add(option,index){if(index===undefined)this.options.push(option);else this.options.splice(index,0,option);}
  appendChild(){} insertAdjacentElement(){} scrollIntoView(){}
  insertAdjacentHTML(position,text){this.innerHTML=position==='afterbegin'?text+this.innerHTML:this.innerHTML+text;}
}
const elements=new Map(),get=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
const ctx=vm.createContext({document:{getElementById:get,createElement:()=>new Element(),head:new Element(),querySelectorAll:()=>[]},
  Option:function(text,value){this.text=text;this.value=value;},setInterval(){},setTimeout(){},clearTimeout(){},window:{},fetch:async()=>{throw Error('network disabled in synthetic test');}});
const html=fs.readFileSync('battle_ui.html','utf8');
vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1],ctx);
vm.runInContext(fs.readFileSync('battle_intel_v4.js','utf8'),ctx);
vm.runInContext(fs.readFileSync('battle_mission_v5.js','utf8'),ctx);
vm.runInContext(`
$('perspective').value='blue';
const task={kind:'deny',type:'breakthrough',targets:[{id:'A',node:1},{id:'B',node:2}],possible_sites:[{id:'A',node:1},{id:'B',node:2}],target_public:false,remaining_ticks:10,deadline:20,required:1,completed:null,status:'active',description:'阻击任务'};
shown={perspective:'blue',scenario:'mission_hidden_v5',tick:10,horizon:20,winner:'',own_mission:task,mission_sites:task.possible_sites,visible_nodes:[1],events:[],objectives:[],nodes:[{id:1,x:100,y:100,terrain:2},{id:2,x:200,y:100,terrain:1}],edges:[[1,2,4]],entities:[{id:101,side:'blue',role:'infantry',status:'READY',current_node:1,x:100,y:100,hp:100,morale:100,suppression:0,ammo:90,goal:1,order:'DEFEND'},{id:102,side:'blue',role:'light',status:'EXITED',current_node:2,x:200,y:100,hp:90,morale:90,suppression:0,ammo:50,goal:2,order:'MOVE'}]};
live={state:shown,decisions:[{side:'blue',agent_version:'commander_v5',source_tick:10,accepted:true,choice_origin:'local_llm',plan:'保持观察',goal_hypotheses:[{objective:'unknown',purpose:'unknown',confidence:'low',support:[],counter_evidence:[],basis:'无足够敌情',would_change_if:'新目击'}],evidence:[],tracks:[],assignments:[],candidate_plans:[],trigger_conditions:['new_contact']}],last_contacts:{blue:[]},busy:{blue:false},controllers:{red:'scripted',blue:'memory'}};
intelSide='blue';render();
`,ctx);
assert(get('missionPanel').innerHTML.includes('对手脱离数未公开'));
assert(!get('missionPanel').innerHTML.includes('红方 /'));
assert(get('map').innerHTML.includes('出口 A')&&get('map').innerHTML.includes('出口 B'));
assert(!get('map').innerHTML.includes('· 指定'));
assert(!get('map').innerHTML.includes('<title>102'));
assert(get('roster').innerHTML.includes('已脱离'));
assert(get('intel').innerHTML.includes('目标未明'));
assert(get('intel').innerHTML.includes('已观察事实'));
assert(get('intel').innerHTML.includes('来源事实记录'));
console.log('PASS synthetic mission DOM: private task, exits, roster, hypotheses, sources');
