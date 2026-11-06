#include <iostream>
#include <string>
#include <map>
#include <set>
#include <cstring>
#include <stdexcept>
#include "Core/WorldMap.h"
#include "Entities/SquadEntity.h"

using namespace MilSim;
static_assert(sizeof(RadioPacket) == 40, "Python/C++ packet size mismatch");

class ClassroomWorld {
    WorldMap map;
    std::map<uint32_t, SquadEntity> units;
    uint64_t tick = 0;
    std::map<std::string, int> control{{"red", 0}, {"blue", 0}};
    static std::string side(uint32_t id) { return id < 70 ? "red" : "blue"; }
public:
    void reset() {
        map = WorldMap{};
        units.clear();
        tick = 0;
        control = {{"red", 0}, {"blue", 0}};
        for (uint32_t i = 1; i <= 5; ++i) map.add_node(i, float(i), 0, TerrainType::PLAINS);
        for (uint32_t i = 1; i < 5; ++i) map.add_connection(i, i + 1, 4.0f);
        units.emplace(1, SquadEntity(1, 1));
        units.emplace(74, SquadEntity(74, 5));
    }
    json state() const {
        json result{{"type", "STATE"}, {"scenario", "course_line_v1"}, {"tick", tick}, {"objective_node", 3}, {"control_ticks", control}, {"nodes", json::array()}, {"edges", json::array()}, {"entities", json::array()}};
        for (const auto& [id, node] : map.get_all_nodes()) {
            result["nodes"].push_back({{"id", id}, {"x", node.x}, {"y", node.y}, {"type", int(node.terrain)}});
            for (const auto& [to, cost] : node.neighbors) if (id < to) result["edges"].push_back(json::array({id, to, cost}));
        }
        for (const auto& [id, unit] : units) {
            auto data = unit.to_json();
            data["side"] = side(id);
            result["entities"].push_back(data);
        }
        return result;
    }
    std::string apply(const json& order, std::set<uint32_t>& seen) {
        const std::string hex = order.at("packet_hex").get<std::string>();
        if (hex.size() != 80) return "packet_length";
        RadioPacket packet{};
        auto* bytes = reinterpret_cast<unsigned char*>(&packet);
        auto digit = [](char c) -> int { if (c >= '0' && c <= '9') return c - '0'; if (c >= 'a' && c <= 'f') return c - 'a' + 10; if (c >= 'A' && c <= 'F') return c - 'A' + 10; return -1; };
        for (size_t i = 0; i < 40; ++i) {
            int a = digit(hex[2 * i]), b = digit(hex[2 * i + 1]);
            if (a < 0 || b < 0) return "packet_hex";
            bytes[i] = static_cast<unsigned char>(a * 16 + b);
        }
        if (packet.packet_id != tick) return "stale_snapshot";
        if (!units.count(packet.receiver_id)) return "unknown_unit";
        if (order.at("side").get<std::string>() != side(packet.receiver_id)) return "foreign_unit";
        if (seen.count(packet.receiver_id)) return "duplicate_order";
        auto& unit = units.at(packet.receiver_id);
        if (unit.get_state() == SquadState::DESTROYED || unit.get_state() == SquadState::ROUTED || unit.get_hp() <= 0) return "unit_uncontrollable";
        const auto* current = map.get_node(unit.get_current_node());
        if (!map.get_node(packet.target_node)) return "unknown_node";
        if (packet.command_code < 1 || packet.command_code > 4) return "unknown_action";
        if (packet.command_code == 3 && packet.target_node != unit.get_current_node()) return "defend_not_current_node";
        if ((packet.command_code == 2 || packet.command_code == 4) && packet.target_node != unit.get_current_node() && !current->neighbors.count(packet.target_node)) return "nonadjacent_action";
        seen.insert(packet.receiver_id);
        unit.on_receive_radio(packet, tick);
        return "";
    }
    void advance() {
        ++tick;
        std::map<uint32_t, std::pair<float, float>> forces;
        for (const auto& [id, unit] : units) if (unit.get_state() != SquadState::DESTROYED && unit.get_state() != SquadState::ROUTED) {
            auto& pair = forces[unit.get_current_node()];
            (id < 70 ? pair.first : pair.second) += unit.get_hp();
        }
        for (auto& [id, unit] : units) {
            auto [red, blue] = forces[unit.get_current_node()];
            bool contact = red > 0 && blue > 0;
            unit.set_combat_status(contact);
            unit.set_force_ratio(contact ? (id < 70 ? red / blue : blue / red) : 1.0f);
        }
        for (auto& [id, unit] : units) unit.tick(tick, map);
        std::set<std::string> present;
        for (const auto& [id, unit] : units) if (unit.get_current_node() == 3 && unit.get_hp() > 0 && unit.get_state() != SquadState::ROUTED && unit.get_state() != SquadState::DESTROYED) present.insert(side(id));
        if (present.size() == 1) ++control[*present.begin()];
    }
    json handle(const json& request) {
        if (request.value("command", "") == "reset") { reset(); return state(); }
        if (request.value("command", "") == "state") return state();
        if (request.value("command", "") != "step") throw std::runtime_error("unknown command");
        int count = request.value("ticks", 1);
        if (count < 1 || count > 16) throw std::runtime_error("ticks must be 1..16");
        auto orders = request.value("orders", json::array());
        if (!orders.is_array() || orders.size() > 8) throw std::runtime_error("too many orders");
        json checks = json::array();
        std::set<uint32_t> seen;
        for (const auto& order : orders) {
            try { std::string error = apply(order, seen); checks.push_back({{"accepted", error.empty()}, {"error", error}}); }
            catch (const std::exception&) { checks.push_back({{"accepted", false}, {"error", "invalid_order_fields"}}); }
        }
        for (int i = 0; i < count; ++i) advance();
        auto result = state(); result["order_checks"] = checks; return result;
    }
};

int main() {
    // Keep legacy entity diagnostics on stderr; stdout is exclusively JSONL.
    auto* protocol_buffer = std::cout.rdbuf();
    std::ostream protocol(protocol_buffer);
    std::cout.rdbuf(std::cerr.rdbuf());
    ClassroomWorld world;
    world.reset();
    std::string line;
    while (std::getline(std::cin, line)) {
        try {
            if (line.size() > 65536) throw std::runtime_error("request too large");
            protocol << world.handle(json::parse(line)).dump() << std::endl;
        } catch (const std::exception& e) { protocol << json({{"type", "ERROR"}, {"message", e.what()}}).dump() << std::endl; }
    }
    return 0;
}
