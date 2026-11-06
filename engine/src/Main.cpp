#include <iostream>
#include <vector>
#include <map>
#include <thread>
#include <chrono>

#ifdef _WIN32
#include <windows.h>
#endif

#include "Core/Protocol.h"
#include "Core/RadioBus.h"
#include "Core/WorldMap.h"
#include "Entities/SquadEntity.h"
#include "Core/NetworkBridge.h" // 【新增】：引入网桥

using namespace MilSim;

int main() {
#ifdef _WIN32
    SetConsoleOutputCP(CP_UTF8);
#endif

    uint64_t current_tick = 0;
    RadioBus global_bus;
    // ==========================================
    // [历史剧本注入]：孟良崮战役 (1947年5月)
    // ==========================================
    WorldMap sand_table;
    std::map<uint32_t, SquadEntity> world_entities;

    // --- 1. 构建战区节点 (Nodes) ---
    // 国军核心阵地
    sand_table.add_node(2001, 50.0f, 30.0f, TerrainType::HILL);    // 孟良崮主峰 (易守难攻，但无水无粮)
    sand_table.add_node(2000, 50.0f, 60.0f, TerrainType::URBAN);   // 垛庄 (74师后勤补给线，战略要地)
    sand_table.add_node(2005, 80.0f, 80.0f, TerrainType::URBAN);   // 临沂 (国军大本营/出发地)
    sand_table.add_node(2006, 65.0f, 70.0f, TerrainType::PLAINS);  // 汤头 (临沂到垛庄的必经之路)

    // 解放军集结与穿插阵地
    sand_table.add_node(2002, 20.0f, 20.0f, TerrainType::PLAINS);  // 坦埠 (华东野战军指挥部所在地)
    sand_table.add_node(2003, 20.0f, 50.0f, TerrainType::FOREST);  // 垛庄以西密林 (穿插路线)
    sand_table.add_node(2004, 70.0f, 20.0f, TerrainType::HILL);    // 芦山/雕窼 (孟良崮侧翼制高点)

    // --- 2. 构建战术路网 (Edges) ---
    sand_table.add_connection(2001, 2000, 4.0f); // 孟良崮 - 垛庄 (退路)
    sand_table.add_connection(2001, 2002, 6.0f); // 孟良崮 - 坦埠 (正面战场)
    sand_table.add_connection(2001, 2004, 3.0f); // 孟良崮 - 芦山 (侧翼争夺)
    sand_table.add_connection(2000, 2003, 4.0f); // 垛庄 - 西侧密林 (6纵穿插神仙步)
    sand_table.add_connection(2000, 2006, 5.0f); // 垛庄 - 汤头 (补给线)
    sand_table.add_connection(2006, 2005, 5.0f); // 汤头 - 临沂

    // --- 3. 历史兵力初始部署 (Entities) ---
    // 【蓝军】
    world_entities.emplace(74, SquadEntity(74, 2001)); // 整编第74师 (张灵甫) -> 孤军突进孟良崮
    world_entities.emplace(83, SquadEntity(83, 2005)); // 整编第83师 (李天霞) -> 在临沂磨洋工，准备救援

    // 【红军】(华东野战军)
    world_entities.emplace(1, SquadEntity(1, 2002)); // 1纵 (叶飞) -> 坦埠正面主攻
    world_entities.emplace(4, SquadEntity(4, 2004)); // 4纵 (陶勇) -> 抢占芦山侧翼
    world_entities.emplace(6, SquadEntity(6, 2003)); // 6纵 (王必成) -> 飞兵急行军，目标切断垛庄！
    world_entities.emplace(9, SquadEntity(9, 2002)); // 9纵 (许世友) -> 坦埠协同主攻

    // (由于你已经写了动态握手协议，Python 雷达会自动适配这张新地图！)

    std::cout << "--- 军火系统校验完成。推演服务端启动 ---\n";

    // 1. 【新增】：点火启动网络桥梁！
    NetworkBridge net_bridge(global_bus, sand_table);
    net_bridge.start_server(5555);
    std::cout << "[系统] 战术网络桥梁已建立，监听端口 5555...\n";

    // 2. 【修改】：无尽的物理主循环
    while (true) {
        current_tick++;
        std::cout << "\n>>> Tick: " << current_tick << " <<<\n";

        // 1. 获取网络指令包 (删除了你代码里重复抓取的那一段)
        auto ready_msgs = net_bridge.fetch_safe(current_tick);
        for (const auto& msg : ready_msgs) {
            auto it = world_entities.find(msg.receiver_id);
            if (it != world_entities.end()) {
                it->second.on_receive_radio(msg, current_tick);
            }
        }

        // ==========================================
        // 【终极交战仲裁庭】：基于真实HP的兰切斯特压制算法
        // ==========================================
        std::map<uint32_t, std::pair<float, float>> node_forces;
        node_forces.clear();

        // 统计血量
        for (auto& [id, squad] : world_entities) {
            MilSim::SquadState state = squad.get_state();
            if (state != MilSim::SquadState::DESTROYED && state != MilSim::SquadState::ROUTED) {
                if (id < 70) node_forces[squad.get_current_node()].first += squad.get_hp();
                else node_forces[squad.get_current_node()].second += squad.get_hp();
            }
        }

        // 裁决交火与倍率
        for (auto& [id, squad] : world_entities) {
            MilSim::SquadState state = squad.get_state();
            if (state == MilSim::SquadState::DESTROYED || state == MilSim::SquadState::ROUTED) {
                squad.set_combat_status(false);
                continue;
            }

            uint32_t node = squad.get_current_node();
            float red_hp = node_forces[node].first;
            float blue_hp = node_forces[node].second;

            if (red_hp > 0.0f && blue_hp > 0.0f) {
                squad.set_combat_status(true);
                float ratio = (id < 70) ? (red_hp / blue_hp) : (blue_hp / red_hp);
                squad.set_force_ratio(ratio);
            } else {
                squad.set_combat_status(false);
                squad.set_force_ratio(1.0f);
            }
        }

        // 3. 执行物理引擎与状态机运转 (整个循环里只能有这一个 tick 调用！)
        for (auto& [id, squad] : world_entities) {
            squad.tick(current_tick, sand_table);
        }

        // 4. 定期广播战报 (每 5 帧发一次，减轻网络压力)
        if (current_tick % 5 == 0) {
            net_bridge.broadcast_telemetry(current_tick, world_entities);
        }

        std::this_thread::sleep_for(std::chrono::milliseconds(300));
    }

    net_bridge.stop_server();
    return 0;
}