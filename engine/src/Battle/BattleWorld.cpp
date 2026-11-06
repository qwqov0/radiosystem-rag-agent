#include "BattleWorld.h"
#include <algorithm>
#include <cmath>
#include <limits>
#include <queue>
#include <stdexcept>
#include <tuple>

namespace MilSim {
namespace {
struct Profile { double speed, fire, shock; int range, vision, ammo; };
const std::map<std::string, Profile> profiles = {
    {"infantry", {1.0, 5.0, 1.0, 1, 2, 90}},
    {"light", {1.4, 3.6, .8, 1, 3, 75}},
    {"artillery", {.65, 5.0, 2.7, 3, 1, 45}},
    {"tank", {1.2, 6.2, 1.3, 1, 2, 65}}
};
const char* terrain_names[] = {"urban", "forest", "plains", "hill"};
double clamp(double x, double a, double b) { return std::max(a, std::min(b, x)); }
bool mobile(const BattleUnit& u) { return u.status != "DESTROYED" && u.status != "SURRENDERED" && u.status != "EXITED"; }
bool routed(const BattleUnit& u) { return u.status == "ROUTED"; }
double round2(double x) { return std::round(x * 100) / 100; }
}

BattleWorld::BattleWorld() { reset(scenario()); }
bool BattleWorld::alive(const BattleUnit& u) const { return mobile(u) && u.hp > 0; }
BattleJson BattleWorld::rules() {
    BattleJson roles = BattleJson::object();
    for (const auto& [name, p] : profiles) roles[name] = {
        {"speed", p.speed}, {"fire", p.fire}, {"suppression", p.shock},
        {"range", p.range}, {"vision", p.vision}, {"ammo", p.ammo}};
    return {{"version", "battle_v5.0"}, {"roles", roles},
        {"missions", {"breakthrough", "hold_extract"}},
        {"mission_order", "simultaneous combat -> surviving eligible exits -> success -> deadline -> feasibility"},
        {"flank_angle_degrees", 100}, {"flank_damage_multiplier", 1.25},
        {"flank_morale_multiplier", 1.5}, {"rout_threshold", 20},
        {"rally_ticks", 10}, {"rally_morale", 40},
        {"terrain", {{"plains", {{"cover", 1.0}, {"foot_cost", 1.0}, {"tank_cost", 1.0}}},
                     {"forest", {{"cover", .52}, {"foot_cost", 1.4}, {"tank_cost", 2.8}}},
                     {"urban", {{"cover", .48}, {"foot_cost", 1.25}, {"tank_cost", 2.2}}},
                     {"hill", {{"cover", .70}, {"foot_cost", 1.6}, {"tank_cost", 1.9}}}}},
        {"semantics", "Deterministic graph wargame; simultaneous fire; shared friendly spotting; no hidden enemy orders in observations"}};
}
BattleJson BattleWorld::scenario() const {
    BattleJson nodes = BattleJson::array(), edges = BattleJson::array(), units = BattleJson::array();
    const int terrain[24] = {1,1,2,3,1,1, 2,0,3,2,0,2, 1,1,2,0,1,1, 2,2,3,2,2,2};
    for (int r=0; r<4; ++r) for (int c=0; c<6; ++c) {
        int id=r*6+c+1;
        nodes.push_back({{"id",id},{"x",85+c*145+(r%2)*22}, {"y",85+r*125+(c%2)*12}, {"terrain",terrain[id-1]}});
        if(c<5) edges.push_back({id,id+1,4.0});
        if(r<3) edges.push_back({id,id+6,4.6});
    }
    edges.push_back({9,16,5.8}); edges.push_back({10,15,5.8});
    int red_nodes[]={7,19,1,13,1}, blue_nodes[]={12,24,6,18,6};
    const char* roles[]={"infantry","infantry","light","tank","artillery"};
    for(int i=0;i<5;++i) {
        units.push_back({{"id",i+1},{"side","red"},{"node",red_nodes[i]},{"role",roles[i]}});
        units.push_back({{"id",i+101},{"side","blue"},{"node",blue_nodes[i]},{"role",roles[i]}});
    }
    return {{"name","twin_ridges_v3"},{"nodes",nodes},{"edges",edges},{"units",units},
        {"objectives",{{{"node",9},{"name","北岭观察所"}},{{"node",16},{"name","南部枢纽镇"}}}},
        {"horizon",360},{"score_limit",140}};
}
void BattleWorld::reset(const BattleJson& cfg) {
    // Parse into a temporary world representation first; an invalid reset must
    // never leave a half-loaded live match behind.
    WorldMap new_map; std::map<int,BattleUnit> new_units;
    auto ns=cfg.at("nodes"), es=cfg.at("edges"), us=cfg.at("units");
    if(!ns.is_array() || ns.empty() || ns.size()>80 || !es.is_array() || es.size()>320 || !us.is_array() || us.empty() || us.size()>32) throw std::runtime_error("scenario_size");
    std::set<int> ids;
    for(const auto& n:ns) {
        int id=n.at("id"), t=n.value("terrain",2); double x=n.at("x"),y=n.at("y");
        if(id<1 || !ids.insert(id).second || t<0 || t>3 || !std::isfinite(x) || !std::isfinite(y) || std::abs(x)>10000 || std::abs(y)>10000) throw std::runtime_error("invalid_node");
        new_map.add_node(id,float(x),float(y),TerrainType(t));
    }
    for(const auto& e:es) {
        if(!e.is_array() || e.size()!=3) throw std::runtime_error("invalid_edge");
        int a=e[0],b=e[1];double cost=e[2];
        if(a==b || !ids.count(a) || !ids.count(b) || !std::isfinite(cost) || cost<.1 || cost>100) throw std::runtime_error("invalid_edge");
        new_map.add_connection(a,b,float(cost));
    }
    for(const auto& v:us) {
        BattleUnit u; u.id=v.at("id");u.node=v.at("node");u.side=v.at("side");u.role=v.value("role","infantry");
        if(u.id<1 || new_units.count(u.id) || !ids.count(u.node) || (u.side!="red" && u.side!="blue") || !profiles.count(u.role)) throw std::runtime_error("invalid_unit");
        u.hp=v.value("hp",100.0);u.morale=v.value("morale",100.0);u.ammo=v.value("ammo",profiles.at(u.role).ammo);
        if(!std::isfinite(u.hp) || !std::isfinite(u.morale) || u.hp<=0 || u.hp>100 || u.morale<0 || u.morale>100 || u.ammo<0 || u.ammo>1000) throw std::runtime_error("invalid_unit_stats");
        u.goal=u.next=u.from=u.node;u.facing=u.side=="red"?0:4;
        new_units.emplace(u.id,u);
    }
    auto objectives=cfg.value("objectives",BattleJson::array());
    if(!objectives.is_array() || objectives.size()>8) throw std::runtime_error("invalid_objectives");
    std::set<int> objective_ids;
    for(auto& o:objectives) { int node=o.at("node");if(!ids.count(node)||!objective_ids.insert(node).second) throw std::runtime_error("invalid_objectives");o["owner"]="neutral"; }
    int horizon=cfg.value("horizon",360),limit=cfg.value("score_limit",140);
    if(horizon<1||horizon>10000||limit<1||limit>10000) throw std::runtime_error("invalid_limits");
    auto mission=cfg.value("mission",BattleJson::object());
    if(!mission.is_object())throw std::runtime_error("invalid_mission");
    if(!mission.empty()) {
        std::string type=mission.at("type"), mover=mission.at("mover");
        if((type!="breakthrough"&&type!="hold_extract")||(mover!="red"&&mover!="blue"))throw std::runtime_error("invalid_mission");
        int deadline=mission.at("deadline"),required=mission.at("required");
        if(deadline<1||deadline>horizon||required<1)throw std::runtime_error("invalid_mission_limits");
        auto sites=mission.at("sites"), targets=mission.at("target_ids"), eligible=mission.at("eligible_units");
        if(!sites.is_array()||sites.empty()||sites.size()>4||!targets.is_array()||targets.empty()||!eligible.is_array())throw std::runtime_error("invalid_mission_fields");
        std::set<std::string> site_ids;std::set<int> site_nodes, unit_ids;
        for(const auto& s:sites){std::string id=s.at("id");int n=s.at("node");if(id.empty()||id.size()>20||!ids.count(n)||!site_ids.insert(id).second||!site_nodes.insert(n).second)throw std::runtime_error("invalid_mission_site");}
        std::set<std::string> target_ids;
        for(const auto& t:targets){std::string id=t;if(!site_ids.count(id)||!target_ids.insert(id).second)throw std::runtime_error("invalid_mission_target");}
        for(const auto& uid:eligible){int id=uid;if(!new_units.count(id)||new_units.at(id).side!=mover||!unit_ids.insert(id).second)throw std::runtime_error("invalid_mission_unit");}
        if(required>int(unit_ids.size()))throw std::runtime_error("invalid_mission_required");
        if(type=="hold_extract") {int h=mission.at("hold_until"),n=mission.at("hold_node");if(h<1||h>=deadline||!ids.count(n))throw std::runtime_error("invalid_hold_stage");}
        bool target_public=mission.value("target_public",false);mission["target_public"]=target_public;
        auto fallback=mission.value("fallback_nodes",BattleJson::object());
        if(!fallback.is_object())throw std::runtime_error("invalid_fallback");
        for(auto it=fallback.begin();it!=fallback.end();++it){if((it.key()!="red"&&it.key()!="blue")||!it.value().is_array())throw std::runtime_error("invalid_fallback");for(const auto& n:it.value())if(!ids.count(n.get<int>()))throw std::runtime_error("invalid_fallback");}
        mission["fallback_nodes"]=fallback;
    }
    map_=std::move(new_map);units_=std::move(new_units);objectives_=objectives;
    tick_=0;events_=BattleJson::array();score_={{"red",0},{"blue",0}};winner_="";
    horizon_=horizon;score_limit_=limit;scenario_=cfg.value("name","custom");
    mission_=mission;exited_.clear();winner_reason_.clear();
}
BattleJson BattleWorld::mission_view(const std::string& side) const {
    if(mission_.empty())return BattleJson::object();
    const bool mover=side==mission_["mover"].get<std::string>();
    bool public_target=mission_.at("target_public");
    auto sites=mission_["sites"];BattleJson selected=BattleJson::array();
    for(const auto& s:sites)if(mover||public_target){if(std::find(mission_["target_ids"].begin(),mission_["target_ids"].end(),s["id"])!=mission_["target_ids"].end())selected.push_back(s);}
    else selected.push_back(s);
    bool hold=mission_["type"]=="hold_extract"&&tick_<mission_["hold_until"].get<int>();
    auto fallback=mission_["fallback_nodes"].value(side,BattleJson::array());
    BattleJson out={{"kind",mover?(hold?"hold":"breakthrough"):"deny"},{"type",mission_["type"]},
        {"targets",selected},{"possible_sites",sites},{"deadline",mission_["deadline"]},
        {"remaining_ticks",std::max(0,mission_["deadline"].get<int>()-tick_)},{"required",mission_["required"]},
        {"target_public",public_target},{"fallback_nodes",fallback},{"status",winner_.empty()?"active":(winner_==side?"success":"failed")},
        {"description",mover?(hold?"阶段一：截止前不得让对手独占坚守点；随后撤至指定出口":"在截止节拍内让规定数量的指定部队抵达任务出口并脱离"):
            (public_target?"在截止节拍前阻止对手在公开任务出口完成脱离":"在截止节拍前阻止对手完成任务；对手真实私有目标不提供给本方")}};
    if(mover){out["eligible_units"]=mission_["eligible_units"];out["completed"]=exited_.size();out["exited_units"]=exited_;}
    else out["completed"]=nullptr;
    if(mission_["type"]=="hold_extract"){out["hold_until"]=mission_["hold_until"];out["hold_node"]=mission_["hold_node"];}
    return out;
}
void BattleWorld::evaluate_mission() {
    const std::string mover=mission_["mover"],deny=mover=="red"?"blue":"red";
    const bool hold=mission_["type"]=="hold_extract";
    if(hold&&tick_<=mission_["hold_until"].get<int>()) {
        int n=mission_["hold_node"];bool friendly=false,enemy=false;
        for(const auto& [id,u]:units_)if(alive(u)&&!routed(u)&&u.status!="RALLYING"&&u.node==n)(u.side==mover?friendly:enemy)=true;
        if(enemy&&!friendly){winner_=deny;winner_reason_="hold_breached";return;}
    }
    // Exit after combat: a destroyed/routed unit cannot escape in the same tick.
    if(!hold||tick_>=mission_["hold_until"].get<int>()) {
        for(const auto& uid:mission_["eligible_units"]){auto& u=units_.at(uid.get<int>());
            bool target=false;for(const auto& s:mission_["sites"])if(s["node"]==u.node&&std::find(mission_["target_ids"].begin(),mission_["target_ids"].end(),s["id"])!=mission_["target_ids"].end())target=true;
            if(target&&alive(u)&&!routed(u)&&u.status!="RALLYING"&&u.route.empty()&&!hostile_at(u.node,mover)){
                exited_.insert(u.id);u.status="EXITED";u.exited_tick=tick_;u.route.clear();u.progress=0;event("unit_exited",u.node,u.id);
            }
        }
    }
    int possible=int(exited_.size());for(const auto& uid:mission_["eligible_units"])if(alive(units_.at(uid.get<int>())))++possible;
    if(int(exited_.size())>=mission_["required"].get<int>()){winner_=mover;winner_reason_="mission_completed";}
    else if(tick_>=mission_["deadline"].get<int>()){winner_=deny;winner_reason_="mission_deadline";}
    else if(possible<mission_["required"].get<int>()){winner_=deny;winner_reason_="mission_unachievable";}
}
int BattleWorld::hops(int from,int to) const {
    if(from==to)return 0;
    std::queue<std::pair<int,int>> q;q.push({from,0});std::set<int> seen{from};
    while(!q.empty()) {auto [n,d]=q.front();q.pop();auto p=map_.get_node(n);if(!p)continue;
        for(auto [v,c]:p->neighbors)if(seen.insert(v).second){if(int(v)==to)return d+1;q.push({int(v),d+1});}}
    return 9999;
}
double BattleWorld::terrain_cost(int node,const BattleUnit& u) const {
    int t=int(map_.get_node(node)->terrain);
    const double foot[]={1.25,1.4,1.0,1.6}, tank[]={2.2,2.8,1.0,1.9};
    double c=(u.role=="tank"?tank[t]:foot[t]);
    if(u.role=="light" && t==1)c=1.0;
    if(u.role=="artillery" && t==3)c*=1.15;
    return c;
}
bool BattleWorld::hostile_at(int node,const std::string& side) const {
    for(const auto& [id,u]:units_)if(alive(u)&&u.side!=side&&u.node==node)return true;
    return false;
}
std::set<int> BattleWorld::visible_nodes(const std::string& side) const {
    std::set<int> out;
    for(const auto& [id,u]:units_)if(alive(u)&&u.side==side) {
        int range=profiles.at(u.role).vision+(map_.get_node(u.node)->terrain==TerrainType::HILL?1:0);
        std::queue<std::pair<int,int>> q;q.push({u.node,0});std::set<int> seen{u.node};
        while(!q.empty()) {auto [n,d]=q.front();q.pop();out.insert(n);
            auto p=map_.get_node(n);if(d>=range || (d>0&&(p->terrain==TerrainType::FOREST||p->terrain==TerrainType::URBAN)))continue;
            for(auto [v,c]:p->neighbors)if(seen.insert(v).second)q.push({int(v),d+1});
        }
    }
    return out;
}
bool BattleWorld::detectable(const BattleUnit& u,const std::string& side,const std::set<int>& visible) const {
    if(u.side==side)return true;
    if(u.status=="EXITED"&&u.exited_tick!=tick_)return false;
    if(!visible.count(u.node))return false;
    if(map_.get_node(u.node)->terrain!=TerrainType::FOREST)return true;
    for(const auto& [id,f]:units_)if(alive(f)&&f.side==side && (hops(f.node,u.node)<=1 || (map_.get_node(f.node)->terrain==TerrainType::HILL&&hops(f.node,u.node)<=2)))return true;
    return false;
}
std::vector<int> BattleWorld::path(int from,int to,const BattleUnit& u,bool safe) const {
    std::map<int,double> dist;std::map<int,int> prev;
    using Item=std::pair<double,int>;std::priority_queue<Item,std::vector<Item>,std::greater<Item>> q;
    dist[from]=0;q.push({0,from});auto vis=visible_nodes(u.side);
    while(!q.empty()) {
        auto [d,n]=q.top();q.pop();if(d!=dist[n])continue;if(n==to)break;
        for(auto [v,c]:map_.get_node(n)->neighbors) {
            double risk=0;
            if(safe)for(const auto& [id,e]:units_)if(alive(e)&&e.side!=u.side&&detectable(e,u.side,vis)) {
                if(e.node==int(v)){risk=1e8;break;}
                if(hops(e.node,v)<=profiles.at(e.role).range)risk+=12;
            }
            if(risk>=1e8)continue;
            double nd=d+c*terrain_cost(v,u)/profiles.at(u.role).speed+risk;
            if(!dist.count(v)||nd<dist[v]-1e-8){dist[v]=nd;prev[v]=n;q.push({nd,int(v)});}
        }
    }
    if(!dist.count(to))return {};
    std::vector<int> result;for(int n=to;n!=from;n=prev.at(n))result.push_back(n);
    std::reverse(result.begin(),result.end());return result;
}
void BattleWorld::event(const std::string& kind,int node,int actor,int target,double value) {
    events_.push_back({{"tick",tick_},{"kind",kind},{"node",node},{"actor",actor},{"target",target},{"value",round2(value)}});
    if(events_.size()>400)events_.erase(events_.begin());
}
int BattleWorld::retreat_node(const BattleUnit& u) const {
    double best=std::numeric_limits<double>::infinity();int choice=u.node;auto vis=visible_nodes(u.side);
    auto cur=map_.get_node(u.node);
    for(auto [n,c]:cur->neighbors) {
        double danger=0;bool occupied=false;
        for(const auto& [id,e]:units_)if(alive(e)&&e.side!=u.side&&detectable(e,u.side,vis)) {
            int d=hops(n,e.node);if(d==0){occupied=true;break;}
            if(d<=profiles.at(e.role).range)danger+=e.hp/(d+.3);
        }
        if(occupied)continue;
        for(const auto& [id,f]:units_)if(alive(f)&&f.side==u.side&&f.id!=u.id&&!routed(f)&&hops(n,f.node)<=1)danger-=8;
        // Rearward preference is geometric, never dependent on a node's ID.
        double dx=map_.get_node(n)->x-cur->x;
        if(!mission_.empty()&&mission_["fallback_nodes"].contains(u.side)&&!mission_["fallback_nodes"][u.side].empty()) {
            int distance=9999;for(const auto& home:mission_["fallback_nodes"][u.side])distance=std::min(distance,hops(n,home.get<int>()));danger+=distance*.25;
        } else danger+=(u.side=="red"?dx:-dx)*.025;
        danger+=c*terrain_cost(n,u)*.2;
        if(danger<best){best=danger;choice=n;}
    }
    return choice;
}
void BattleWorld::advance() {
    if(!winner_.empty())return;
    ++tick_;
    // Movement is independent of LLM wall time and uses weighted routes.
    for(auto& [id,u]:units_)if(alive(u)) {
        u.under_fire=false;u.flanked=false;
        if(routed(u)&&u.route.empty()) {
            bool danger=false;auto vis=visible_nodes(u.side);
            for(const auto& [eid,e]:units_)if(alive(e)&&e.side!=u.side&&detectable(e,u.side,vis)&&hops(u.node,e.node)<=profiles.at(e.role).range)danger=true;
            if(danger){int n=retreat_node(u);
                if(n!=u.node){u.goal=n;u.route={n};u.next=n;u.trapped=0;event("rout_move",u.node,id,n);}
                else ++u.trapped;
            } else u.trapped=0;
        }
        if(!u.route.empty()&&(routed(u)||u.order=="RETREAT")&&hostile_at(u.route.front(),u.side)) {
            u.route.clear();u.progress=0;int n=retreat_node(u);
            if(n!=u.node){u.goal=n;u.route={n};u.next=n;}
            event("retreat_blocked",u.node,id);
        }
        bool move=!u.route.empty();
        if(u.order=="ATTACK"&&!routed(u)) {
            auto vis=visible_nodes(u.side);
            for(const auto& [eid,e]:units_)if(alive(e)&&e.side!=u.side&&!routed(e)&&detectable(e,u.side,vis)&&hops(u.node,e.node)<=profiles.at(u.role).range){move=false;break;}
        }
        if(move) {
            u.next=u.route.front();double cost=map_.get_node(u.node)->neighbors.at(u.next)*terrain_cost(u.next,u);
            double speed=profiles.at(u.role).speed*(routed(u)?1.15:(u.order=="RETREAT"?.72:1.0));
            u.progress+=speed*clamp(1-u.suppression*.006,.35,1.0);u.entrenchment=0;
            if(!routed(u))u.status=u.order=="RETREAT"?"RETREATING":"MARCHING";
            if(u.progress>=cost) {
                u.from=u.node;u.node=u.next;u.route.erase(u.route.begin());u.progress=0;event("arrived",u.node,id);
                if(u.route.empty()&&!routed(u)){u.status=u.order=="RETREAT"?"RALLYING":"READY";u.rally=0;u.order="DEFEND";}
                u.next=u.route.empty()?u.node:u.route.front();
            }
        } else if(!routed(u)&&u.status!="RALLYING") {u.status="READY";if(u.order=="DEFEND")u.entrenchment=std::min(1.0,u.entrenchment+.06);}
    }
    struct Shot {int a,b,sector;double damage,shock,dx,dy;bool direct;};
    std::vector<Shot> shots;
    std::map<std::string,std::set<int>> vision{{"red",visible_nodes("red")},{"blue",visible_nodes("blue")}};
    for(auto& [id,u]:units_)if(alive(u)&&!routed(u)&&u.ammo>0&&u.status!="RALLYING") {
        int target=0;double best=-1e9;
        for(const auto& [eid,e]:units_)if(alive(e)&&e.side!=u.side&&detectable(e,u.side,vision[u.side])) {
            int d=hops(u.node,e.node);if(d>profiles.at(u.role).range)continue;
            double priority=(e.node==u.goal&&u.order=="ATTACK"?30:0)+(e.role=="artillery"?8:0)+(routed(e)?-6:0)-d*2;
            if(priority>best){best=priority;target=eid;}
        }
        if(!target)continue;
        const auto& e=units_.at(target);int d=hops(u.node,e.node),t=int(map_.get_node(e.node)->terrain);
        double match=1;
        if(u.role=="tank"&&e.role!="tank")match=1.6;
        if((u.role=="infantry"||u.role=="light")&&e.role=="tank")match=u.role=="light"?.30:.45;
        if(u.role=="artillery"&&e.role=="tank")match=.35;
        if(e.role=="artillery"&&u.role!="artillery")match=1.9;
        if(e.role=="tank"&&(t==0||t==1)&&(u.role=="infantry"||u.role=="light"))match*=3.4;
        if(u.role=="tank"&&(t==0||t==1)&&e.role!="tank")match*=.42;
        double cover[]={.48,.52,1.0,.70};double protection=e.role=="tank"?((t==0||t==1)?1.1:.72):cover[t];
        if(u.role=="artillery")protection=std::max(.80,protection);
        double damage=profiles.at(u.role).fire*match*protection*(1-e.entrenchment*.28)*(.35+.65*u.hp/100)*clamp(1-u.suppression*.009,.25,1.0);
        double shock=profiles.at(u.role).shock*(e.role=="tank"?.55:1.0);
        if(u.order=="MOVE")damage*=.60;
        if(u.order=="RETREAT"){damage*=.38;shock*=.5;}
        if(u.role=="artillery"&&d<2){damage*=.18;shock*=.25;}
        auto p=map_.get_node(u.node), ep=map_.get_node(e.node);
        if(p->terrain==TerrainType::HILL&&ep->terrain!=TerrainType::HILL)damage*=1.12;
        double dx=p->x-ep->x,dy=p->y-ep->y;
        if(d==0){auto approach=map_.get_node(u.from);dx=approach->x-ep->x;dy=approach->y-ep->y;}
        double len=std::hypot(dx,dy);if(len<.001){dx=u.side=="red"?-1:1;dy=0;len=1;}
        dx/=len;dy/=len;int sector=int(std::floor((std::atan2(dy,dx)+3.14159265)*4/3.14159265))%8;
        shots.push_back({id,target,sector,damage,shock,dx,dy,u.role!="artillery"});
    }
    // All shots are selected from the same post-movement snapshot; losses do
    // not cancel an opponent's already-selected shot within this tick.
    std::map<int,std::vector<Shot>> incoming;
    for(const auto& shot:shots){incoming[shot.b].push_back(shot);--units_.at(shot.a).ammo;event("fire",units_.at(shot.b).node,shot.a,shot.b,shot.damage);}
    for(auto& [id,u]:units_)if(alive(u)) {
        double loss=0,shock=0;bool flank=false;std::map<int,int> widths;
        auto& hits=incoming[id];
        for(size_t i=0;i<hits.size();++i)for(size_t j=i+1;j<hits.size();++j)
            if(hits[i].direct&&hits[j].direct&&hits[i].dx*hits[j].dx+hits[i].dy*hits[j].dy<std::cos(100*3.14159265/180))flank=true;
        // Strongest direct shot gets frontage first. ID order cannot change damage.
        std::sort(hits.begin(),hits.end(),[](const Shot&a,const Shot&b){return std::tie(a.damage,a.shock)>std::tie(b.damage,b.shock);});
        for(const auto& hit:hits){int width=hit.direct?widths[hit.sector]++:0;double factor=width==0?1:(width==1?.6:.35);loss+=hit.damage*factor;shock+=hit.shock*factor;}
        u.under_fire=!hits.empty();u.flanked=flank;
        if(flank){loss*=1.25;shock*=1.5;event("flanked",u.node,0,id);}
        if(u.under_fire) {
            u.hp-=loss;u.suppression=clamp(u.suppression+shock*3-1,0,100);
            u.morale-=loss*.55+shock*(flank?2.3:1.5)+(u.ammo==0?1.2:0);u.rally=0;
            if(!routed(u)&&u.order!="RETREAT")u.status="ENGAGED";
            event("damage",u.node,0,id,loss);
        } else {
            u.suppression=std::max(0.0,u.suppression-4);
            bool close=false,support=false;
            for(const auto& [fid,f]:units_)if(alive(f)&&fid!=id){if(f.side!=u.side&&detectable(f,u.side,vision[u.side])&&hops(u.node,f.node)<=1)close=true;if(f.side==u.side&&!routed(f)&&hops(u.node,f.node)<=1)support=true;}
            if(!close){++u.rally;u.morale+=routed(u)||u.status=="RALLYING"?2.4:(support?.6:.3);}
            else u.rally=0;
        }
        u.hp=clamp(u.hp,0,100);u.morale=clamp(u.morale,0,100);
        if(u.hp<=0){u.status="DESTROYED";u.route.clear();u.progress=0;event("destroyed",u.node,0,id);continue;}
        if(!routed(u)&&u.morale<=20){u.status="ROUTED";u.order="RETREAT";u.route.clear();u.progress=0;u.entrenchment=0;u.rally=0;event("routed",u.node,id);}
        if(routed(u)&&u.trapped>=8){u.status="SURRENDERED";u.route.clear();u.progress=0;event("surrendered",u.node,id);}
        if((routed(u)||u.status=="RALLYING")&&u.rally>=10&&u.morale>=40){u.status="READY";u.order="DEFEND";u.route.clear();u.goal=u.next=u.node;u.progress=0;u.trapped=0;event("rallied",u.node,id);}
    }
    for(auto& obj:objectives_) {
        int n=obj.at("node");std::set<std::string> present;
        for(const auto& [id,u]:units_)if(alive(u)&&!routed(u)&&u.status!="RALLYING"&&u.node==n)present.insert(u.side);
        std::string owner=present.size()==1?*present.begin():(present.empty()?"neutral":"contested");
        if(owner!=obj["owner"]){obj["owner"]=owner;event("objective_"+owner,n);}
        if(present.size()==1)++score_[owner];
    }
    if(!mission_.empty()) {evaluate_mission();if(!winner_.empty())event("battle_end",0);return;}
    bool red=false,blue=false;for(auto [id,u]:units_)if(alive(u)){if(u.side=="red")red=true;else blue=true;}
    if(!red||!blue)winner_=red?"red":(blue?"blue":"draw");
    else if(score_["red"]>=score_limit_||score_["blue"]>=score_limit_||tick_>=horizon_) {
        double r=score_["red"],b=score_["blue"];
        if(r==b)for(auto [id,u]:units_)if(alive(u))(u.side=="red"?r:b)+=u.hp*.01;
        winner_=std::abs(r-b)<1e-8?"draw":(r>b?"red":"blue");
    }
    if(!winner_.empty())event("battle_end",0);
}
BattleJson BattleWorld::unit_json(const BattleUnit& u,bool full) const {
    auto p=map_.get_node(u.node);double x=p->x,y=p->y;
    if(!u.route.empty()&&u.progress>0){auto to=map_.get_node(u.route.front());double c=p->neighbors.at(to->id)*terrain_cost(to->id,u),a=clamp(u.progress/c,0,1);x+=(to->x-x)*a;y+=(to->y-y)*a;}
    BattleJson v={{"id",u.id},{"side",u.side},{"role",u.role},{"current_node",u.node},{"x",round2(x)},{"y",round2(y)},
        {"hp",round2(u.hp)},{"status",u.status},{"under_fire",u.under_fire}};
    if(full){v["morale"]=round2(u.morale);v["suppression"]=round2(u.suppression);v["ammo"]=u.ammo;v["order"]=u.order;v["goal"]=u.goal;v["target_node"]=u.next;v["route"]=u.route;v["progress"]=round2(u.progress);v["entrenchment"]=round2(u.entrenchment);v["flanked"]=u.flanked;v["rally_ticks"]=u.rally;}
    return v;
}
BattleJson BattleWorld::state(const std::string& side) const {
    if(side!="observer"&&side!="red"&&side!="blue")throw std::runtime_error("invalid_side");
    bool observer=side=="observer";auto visible=observer?std::set<int>{}:visible_nodes(side);
    BattleJson ns=BattleJson::array(),es=BattleJson::array(),us=BattleJson::array();std::set<int> exposed;
    for(const auto& [id,n]:map_.get_all_nodes()) {
        ns.push_back({{"id",id},{"x",n.x},{"y",n.y},{"terrain",int(n.terrain)},{"terrain_name",terrain_names[int(n.terrain)]}});
        for(auto [to,c]:n.neighbors)if(id<to)es.push_back({id,to,c});
    }
    for(const auto& [id,u]:units_)if(observer||u.side==side||detectable(u,side,visible)){us.push_back(unit_json(u,observer||u.side==side));exposed.insert(id);}
    BattleJson result={{"type","BATTLE_STATE"},{"rules_version","battle_v5.0"},{"scenario",scenario_},{"tick",tick_},{"perspective",side},
        {"nodes",ns},{"edges",es},{"entities",us},{"horizon",horizon_},{"score_limit",score_limit_},{"winner",winner_}};
    if(observer){result["objectives"]=objectives_;result["score"]=score_;result["events"]=events_;}
    else {
        result["visible_nodes"]=visible;
        auto objs=objectives_;for(auto& o:objs)if(!visible.count(o["node"].get<int>()))o["owner"]="unknown";
        result["objectives"]=objs;result["own_score"]=score_.at(side);
        BattleJson ev=BattleJson::array();for(const auto& e:events_) {
            int a=e["actor"],t=e["target"],n=e["node"];
            // Never backfill old events using today's visibility. The memory
            // layer derives events from observations captured at their actual tick.
            if(e["tick"]==tick_&&visible.count(n)&&(!a||exposed.count(a))&&(!t||exposed.count(t)))ev.push_back(e);
        }
        result["events"]=ev;
    }
    if(!mission_.empty()) {
        result["mission_sites"]=mission_["sites"];result["winner_reason"]=winner_reason_;
        if(observer){result["mission_details"]=mission_;result["missions"]={{"red",mission_view("red")},{"blue",mission_view("blue")}};}
        else result["own_mission"]=mission_view(side);
    }
    return result;
}
std::string BattleWorld::validate(const BattleJson& o,std::set<int>& seen) const {
    int id=o.at("unit_id"),node=o.at("target_node");std::string side=o.at("side"),action=o.at("action");
    if(!winner_.empty())return "battle_finished";
    if(!units_.count(id))return "unknown_unit";
    const auto& u=units_.at(id);
    if(side!=u.side)return "foreign_unit";
    if(!seen.insert(id).second)return "duplicate_order";
    if(!alive(u)||routed(u)||u.status=="RALLYING")return "unit_uncontrollable";
    if(!map_.get_node(node))return "unknown_node";
    if(action!="MOVE"&&action!="ATTACK"&&action!="DEFEND"&&action!="RETREAT")return "unknown_action";
    if(action=="DEFEND"&&node!=u.node)return "defend_not_current_node";
    if(action!="DEFEND"&&node!=u.node&&path(u.node,node,u,action=="RETREAT").empty())return "unreachable_or_unsafe";
    return "";
}
void BattleWorld::apply(const BattleJson& o) {
    auto& u=units_.at(o.at("unit_id").get<int>());std::string action=o.at("action");int n=o.at("target_node");
    // Reissuing an identical order does not teleport a unit back to the start
    // of its edge or repeatedly reset defensive preparation.
    if(u.order==action&&u.goal==n)return;
    u.order=action;u.goal=n;u.route=action=="DEFEND"?std::vector<int>{}:path(u.node,n,u,action=="RETREAT");
    u.next=u.route.empty()?u.node:u.route.front();u.progress=0;u.rally=0;
    u.status=action=="RETREAT"?"RETREATING":(u.route.empty()?"READY":"MARCHING");
    if(action!="DEFEND")u.entrenchment=0;
    event("order_"+action,u.node,u.id,n);
}
BattleJson BattleWorld::handle(const BattleJson& req) {
    std::string cmd=req.value("command","state");
    if(cmd=="rules")return rules();
    if(cmd=="default_scenario")return scenario();
    if(cmd=="reset"){reset(req.value("scenario",scenario()));return state();}
    if(cmd=="state")return state(req.value("side","observer"));
    if(cmd!="step")throw std::runtime_error("unknown_command");
    int ticks=req.value("ticks",1);if(ticks<0||ticks>32)throw std::runtime_error("invalid_ticks");
    auto orders=req.value("orders",BattleJson::array());if(!orders.is_array()||orders.size()>32)throw std::runtime_error("invalid_orders");
    bool fresh=req.value("expected_tick",tick_)==tick_;
    BattleJson checks=BattleJson::array();std::set<int> seen;bool valid=fresh;
    for(const auto& o:orders){std::string err;try{err=fresh?validate(o,seen):"stale_snapshot";}catch(const std::exception&){err="invalid_order_fields";}valid&=err.empty();checks.push_back({{"accepted",err.empty()},{"error",err}});}
    if(!valid)for(auto& c:checks){if(c["error"]=="")c["error"]="batch_rejected";c["accepted"]=false;}
    if(valid)for(const auto& o:orders)apply(o);
    // A stale submission never advances the match; caller must fetch a new snapshot.
    if(fresh)for(int i=0;i<ticks&&!winner_.size();++i)advance();
    auto out=state();out["order_checks"]=checks;out["batch_accepted"]=valid;return out;
}
}
