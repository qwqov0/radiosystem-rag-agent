#pragma once
#include <nlohmann/json.hpp>
#include <map>
#include <string>
#include <vector>
#include <set>
#include "Core/WorldMap.h"

namespace MilSim {
using BattleJson = nlohmann::json;
// BattleWorld is the authoritative v3 rules engine. UI, scripts and agents all
// use the same JSONL commands; legacy CourseSim remains a frozen baseline.
struct BattleUnit {
    int id = 0, node = 0, from = 0, next = 0, goal = 0, ammo = 80;
    int rally = 0, trapped = 0, facing = 0;
    std::string side, role = "infantry", order = "DEFEND", status = "READY";
    double hp = 100, morale = 100, suppression = 0, progress = 0, entrenchment = 0;
    bool under_fire = false, flanked = false;
    int exited_tick = -1;
    std::vector<int> route;
};
class BattleWorld {
    WorldMap map_;
    std::map<int, BattleUnit> units_;
    BattleJson objectives_, events_ = BattleJson::array();
    std::map<std::string, int> score_;
    int tick_ = 0, horizon_ = 360, score_limit_ = 140;
    std::string scenario_, winner_;
    BattleJson mission_ = BattleJson::object();
    std::set<int> exited_;
    std::string winner_reason_;
    void evaluate_mission();
    BattleJson mission_view(const std::string& side) const;
    void reset(const BattleJson& config);
    BattleJson scenario() const;
    BattleJson unit_json(const BattleUnit& unit, bool private_fields) const;
    std::set<int> visible_nodes(const std::string& side) const;
    bool detectable(const BattleUnit& unit, const std::string& side,
                    const std::set<int>& visible) const;
    int hops(int from, int to) const;
    std::vector<int> path(int from, int to, const BattleUnit& unit, bool safe) const;
    double terrain_cost(int node, const BattleUnit& unit) const;
    bool alive(const BattleUnit& unit) const;
    bool hostile_at(int node, const std::string& side) const;
    void event(const std::string& kind, int node, int actor = 0, int target = 0,
               double value = 0);
    int retreat_node(const BattleUnit& unit) const;
    void advance();
    std::string validate(const BattleJson& order, std::set<int>& seen) const;
    void apply(const BattleJson& order);
public:
    BattleWorld();
    BattleJson state(const std::string& side = "observer") const;
    BattleJson handle(const BattleJson& request);
    static BattleJson rules();
};
}
