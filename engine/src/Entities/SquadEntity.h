#pragma once
#include <cstdint>
#include <iostream>
#include <vector>
#include "Core/Protocol.h"
#include <nlohmann/json.hpp>
using json = nlohmann::json;

namespace MilSim {
    class WorldMap;

    enum class UnitType {
        LIGHT_INFANTRY = 0,  // 轻装步兵 (跑得快)
        HEAVY_INFANTRY = 1,  // 重装步兵 (血厚，跑得慢)
        ARTILLERY = 2,       // 炮兵阵地 (手长，脆皮)
        MILITIA = 3          // 支前民兵 (战五渣，纯补给)
    };

    struct UnitStats {
        float max_hp;               // 最大血量
        float speed_multiplier;     // 移速倍率 (1.0为标准)
        int attack_range;           // 射程 (0=无武装, 1=同节点近战, 2=跨节点开火)
        float defense_multiplier;   // 承伤倍率 (越低越肉)
    };

    // ==========================================
    // 【新增 1】：战术生命周期状态枚举
    // ==========================================
    enum class SquadState {
        MARCHING = 0,    // 行军 (全速，防御低)
        ENCOUNTER = 1,   // 遭遇瞬间 (短暂惊慌)
        ENGAGED = 2,     // 持续交战 (阵地战)
        RETREATING = 3,  // 有序撤退 (掩护减速)
        ROUTED = 4,      // 溃散 (不可控逃跑)
        STATIONARY = 5,   // 驻扎/待机
        DESTROYED = 6   // 整建制全歼
    };

    // 1. 战术黑板：存放政委的宏观意图与底层的物理感知
    struct TacticalBlackboard {
        // --- 宏观意图 ---
        bool has_macro_order = false;
        uint32_t target_node = 0;

        // --- 微观感知与属性 (数值增减在这里) ---
        bool is_under_fire = false;
        int ammo = 500;
        float morale = 100.0f;  // 【新增】
        SquadState state = SquadState::STATIONARY; // 【新增】
        float local_force_ratio = 1.0f;
        uint32_t final_destination = 0; // 最终目的地
        bool route_calculated = true;   // 路线是否已规划
    };

    class SquadEntity {
    private:
        uint32_t m_id;
        uint32_t m_current_node;
        UnitType m_type;
        float m_hp = 100.0f;

        float m_move_progress;

        // 核心大脑
        TacticalBlackboard m_bb;

        // --- 行为树底层的微观动作 (Micro Actions) ---
        void update_sensors(const WorldMap& world_map);
        void execute_action_idle();
        void execute_action_take_cover();
        void execute_action_tactical_march(const WorldMap& world_map);
        void execute_action_bounding_overwatch(const WorldMap& world_map);

        // 【新增】：溃散时无脑乱跑的微观动作
        void execute_panic_run(const WorldMap& world_map);
        std::vector<uint32_t> m_path_queue;

        // 【新增】：路线规划算法
        void calculate_route(const WorldMap& map);

    public:
        SquadEntity(uint32_t id, uint32_t start_node, UnitType type = UnitType::LIGHT_INFANTRY);
        UnitType get_type() const { return m_type; }

        void on_receive_radio(const RadioPacket& packet, uint64_t current_tick);
        uint32_t get_current_node() const { return m_current_node; }
        uint32_t get_id() const { return m_id; }

        SquadState get_state() const { return m_bb.state; }
        float get_hp() const { return m_hp; }

        void set_combat_status(bool under_fire) {
            m_bb.is_under_fire = under_fire;
        }
        // 每帧执行行为树仲裁
        void tick(uint64_t current_tick, const WorldMap& world_map);

        void set_force_ratio(float ratio) {
            m_bb.local_force_ratio = ratio;
        }

        json to_json() const {
            return json{
            {"id", m_id},
            {"current_node", m_current_node},
            {"target_node", m_bb.has_macro_order ? m_bb.target_node : m_current_node},
            {"progress", m_move_progress},
            {"hp", m_hp},
            {"ammo", m_bb.ammo},
            {"morale", m_bb.morale}, // 【新增】传给 Python
            {"state", static_cast<int>(m_bb.state)}, // 【新增】传给 Python，转为 int 方便解析
            {"is_under_fire", m_bb.is_under_fire},
            {"has_macro_order", m_bb.has_macro_order},
            };
        }
    };
}
