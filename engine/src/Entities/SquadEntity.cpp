#include "Entities/SquadEntity.h"
#include "Core/WorldMap.h"
#include <queue>
#include <unordered_map>
#include <vector>

namespace MilSim {

    SquadEntity::SquadEntity(uint32_t id, uint32_t start_node, UnitType type)
        : m_id(id), m_current_node(start_node), m_type(type), m_hp(100), m_move_progress(0.0f) {
        m_bb.ammo = 500;
        m_bb.is_under_fire = false;
        m_bb.has_macro_order = false;
    }

    // ==========================================
    // 【核心重构】：处理统帅部发来的多维战术指令
    // ==========================================
    void SquadEntity::on_receive_radio(const RadioPacket& packet, uint64_t current_tick) {
        // 1. 过滤：不是发给本部队的电报，直接丢弃
        if (packet.receiver_id != m_id) return;
        // ==========================================
        // 【新增】：战场抗命机制
        // ==========================================
        if (m_bb.state == SquadState::DESTROYED) return;
        if (m_bb.state == SquadState::ROUTED) {
            std::cout << "[战场抗命] " << m_id << " 纵队已全线溃散，拒不执行统帅部指令！\n";
            return;
        }
        // 2. 解析：获取指令类型
        CommandType cmd = static_cast<CommandType>(packet.command_code);

        // 3. 执行：强制推翻当前状态，响应统帅部号令
        switch (cmd) {
            case CommandType::MOVE:
                m_bb.has_macro_order = true;
                m_bb.final_destination = packet.target_node; // 记下最终目标
                m_bb.route_calculated = false;               // 标记需要查地图
                m_bb.state = SquadState::MARCHING;
                // (别忘了把下面原本的 m_bb.target_node 赋值删掉)
                break;

            case CommandType::DEFEND:
                m_bb.has_macro_order = false;
                m_bb.target_node = m_current_node; // 目标改为脚下
                m_bb.state = SquadState::STATIONARY;
                std::cout << "[C2 指挥链] " << m_id << " 纵队收到指令：停止前进，就地展开防御阵型！\n";
                break;

            case CommandType::RETREAT:
                m_bb.has_macro_order = true;
                m_bb.target_node = packet.target_node;
                m_bb.state = SquadState::RETREATING;
                std::cout << "[C2 指挥链] " << m_id << " 纵队收到指令：立刻向 " << m_bb.target_node << " 方向交替掩护撤退！\n";
                break;

            case CommandType::ATTACK:
                m_bb.has_macro_order = true;
                m_bb.target_node = packet.target_node;
                m_bb.state = SquadState::MARCHING; // 暂时用行军逻辑替代，后续可在此处增加攻击 Buff
                std::cout << "[C2 指挥链] " << m_id << " 纵队收到指令：向 " << m_bb.target_node << " 发起强攻！\n";
                break;

            default:
                break;
        }
    }

    // --- 战术雷达：更新感知 ---
    void SquadEntity::update_sensors(const WorldMap& world_map) {
        // 剧本设定：假设 1002 (森林) 是敌人的伏击圈
        if (m_current_node == 1002 && !m_bb.is_under_fire) {
            m_bb.is_under_fire = true;
            std::cout << "\n[警报] Squad " << m_id << " 遭遇猛烈火力伏击！\n";
        } else if (m_current_node != 1002) {
            m_bb.is_under_fire = false; // 离开 1002 就安全了
        }
    }
        // ==========================================
    // 【核心重构】：注入战术生命周期与士气数学模型
    // ==========================================
    void SquadEntity::tick(uint64_t current_tick, const WorldMap& world_map) {
        // 【新增】：如果被全歼，直接变为地图上的尸体，不再进行任何物理计算
        if (m_bb.state == SquadState::DESTROYED) return;

        // [阶段 A] 数值安全锁 (严禁负数)
        if (m_hp < 0) m_hp = 0;
        if (m_bb.ammo < 0) m_bb.ammo = 0;
        if (m_bb.morale < 0.0f) m_bb.morale = 0.0f;

        // 1. 环境感知：当前是否正在承受敌方火力
        bool enemy_present = m_bb.is_under_fire;
        // 【新增导航控制】：如果是新指令，立刻查阅地图生成路线
        if (m_bb.has_macro_order && !m_bb.route_calculated) {
            calculate_route(world_map);
            m_bb.route_calculated = true;

            // 设定第一个途径点
            if (!m_path_queue.empty()) {
                m_bb.target_node = m_path_queue.front();
                m_path_queue.erase(m_path_queue.begin());
            }
        }

        // 【新增接力控制】：走到中途节点后，接力走向下一个节点
        if (m_bb.state == SquadState::MARCHING && m_current_node == m_bb.target_node) {
            if (!m_path_queue.empty()) {
                m_bb.target_node = m_path_queue.front(); // 提取下一个途径点
                m_path_queue.erase(m_path_queue.begin());
            } else if (m_current_node == m_bb.final_destination) {
                m_bb.state = SquadState::STATIONARY;     // 彻底抵达终点
                m_bb.has_macro_order = false;
            }
        }
        // ---------------------------------------------------------
        // 【阶段 A：士气 (Morale) 损耗与恢复模型】
        // ---------------------------------------------------------
        if (enemy_present) {
            // 处于交火中，基础士气缓慢下降
            m_bb.morale -= 0.1f;

            // [绝望惩罚 1]：弹药耗尽会导致极度恐慌
            if (m_bb.ammo <= 0) {
                m_bb.morale -= 0.5f;
            }

            // [绝望惩罚 2]：伤亡过半 (假设满血 100) 会加速士气崩溃
            if (m_hp < 50) {
                m_bb.morale -= 0.2f;
            }
        } else {
            // 脱离战斗后，如果处于驻防状态，士气会缓慢恢复（最高100）
            if (m_bb.state == SquadState::STATIONARY && m_bb.morale < 100.0f) {
                m_bb.morale += 0.05f;
                if (m_bb.morale > 100.0f) m_bb.morale = 100.0f;
            }
        }

        // ---------------------------------------------------------
        // 【阶段 B：有限状态机 (FSM) 自决逻辑】
        // ---------------------------------------------------------
        switch (m_bb.state) {
            // 【必须补回来的三大核心状态】！！！
            case SquadState::STATIONARY:
                if (m_bb.has_macro_order && m_current_node != m_bb.target_node) {
                    m_bb.state = SquadState::MARCHING; // 收到指令，起步拔营
                } else if (enemy_present) {
                    m_bb.state = SquadState::ENGAGED;  // 驻防时遇袭，直接开打
                }
                break;

            case SquadState::MARCHING:
                if (enemy_present) {
                    m_bb.state = SquadState::ENCOUNTER; // 行军中突遇敌军 -> 遭遇
                    m_bb.morale -= 15.0f;               // 遭到伏击，士气大跌
                } else if (m_current_node == m_bb.target_node) {
                    m_bb.state = SquadState::STATIONARY; // 到达目的地，转入驻防
                    m_bb.has_macro_order = false;
                }
                break;

            case SquadState::ENCOUNTER:
                // 遭遇瞬间的应激反应，下一个 Tick 自动转入稳定交战
                m_bb.state = SquadState::ENGAGED;
                break;

            case SquadState::ENGAGED: {
                float damage_multiplier = 1.0f / m_bb.local_force_ratio;
                if (damage_multiplier > 3.0f) damage_multiplier = 3.0f;
                if (damage_multiplier < 0.5f) damage_multiplier = 0.5f;

                if (m_bb.ammo > 0) m_bb.ammo -= 2;

                // ==========================================
                // 【修复 1】：调整数学模型，心理崩溃必须快于肉体消亡
                // ==========================================
                m_hp -= (0.5f * damage_multiplier);        // 降低肉体致死率 (给他们留血逃跑)
                m_bb.morale -= (1.8f * damage_multiplier); // 暴增火力压制带来的恐慌感

                if (m_hp <= 0) {
                    m_bb.state = SquadState::DESTROYED;
                    m_bb.morale = 0.0f;
                } else if (m_bb.morale <= 20.0f) {
                    m_bb.state = SquadState::ROUTED;

                    auto node_ptr = world_map.get_node(m_current_node);
                    if (node_ptr && !node_ptr->neighbors.empty()) {
                        m_bb.final_destination = node_ptr->neighbors.begin()->first;
                        m_bb.route_calculated = false;
                        m_bb.has_macro_order = true;
                    }
                } else if (!enemy_present) {
                    m_bb.state = SquadState::STATIONARY;
                }
                break;
            }

            case SquadState::ROUTED:
                // 溃散中的部队不受控制地逃亡，如果跑到目标点
                if (m_current_node == m_bb.final_destination) {
                    if (enemy_present) {
                        //整建制投降/被歼灭
                        m_hp = 0.0f;
                        m_bb.morale = 0.0f;
                        m_bb.state = SquadState::DESTROYED;
                    } else {
                        // 逃出生天，转为驻防，惊魂未定
                        m_bb.state = SquadState::STATIONARY;
                        m_bb.morale = 25.0f;
                    }
                }
                break;

            default:
                break;
        }

        // ---------------------------------------------------------
        // 【阶段 C：物理执行层】
        // ---------------------------------------------------------
        // 【修复 2】：允许处于“溃散 (ROUTED)”状态的部队进行物理位移！
        if (m_bb.state == SquadState::MARCHING ||
            m_bb.state == SquadState::RETREATING ||
            m_bb.state == SquadState::ROUTED) {
            execute_action_tactical_march(world_map);
            }
    }

    // 补齐溃散时的行为
    void SquadEntity::execute_panic_run(const WorldMap& world_map) {
        m_bb.has_macro_order = false;
        // 暂时原地僵直（后续可以补充往相邻安全节点逃跑的逻辑）
    }

    // --- 微观动作库 (Micro Actions) ---

    void SquadEntity::execute_action_idle() {
        // 待机时不刷屏，保持静默
    }

    void SquadEntity::execute_action_take_cover() {
        m_bb.ammo -= 2; // 盲目反击极度消耗弹药
        std::cout << "  [本能] Squad " << m_id << " 正在掩体后盲目还击！弹药剩余: " << m_bb.ammo << "\n";
    }

    void SquadEntity::execute_action_tactical_march(const WorldMap& world_map) {
        const MapNode* current = world_map.get_node(m_current_node);
        auto it = current->neighbors.find(m_bb.target_node);
        if (it == current->neighbors.end()) return;

        float cost = it->second;
        m_move_progress += 1.0f; // 【全速行军】：每 Tick 推进 1.0

        std::cout << "  [执行] Squad " << m_id << " 正在全速战术行军... 进度: " << m_move_progress << "/" << cost << "\n";

        if (m_move_progress >= cost) {
            m_current_node = m_bb.target_node;
            m_move_progress = 0.0f;
            m_bb.has_macro_order = false; // 到达目标，清空黑板意图
            std::cout << "[战报] Squad " << m_id << " 抵达目标节点 " << m_current_node << "。\n";
        }
    }

    void SquadEntity::execute_action_bounding_overwatch(const WorldMap& world_map) {
        const MapNode* current = world_map.get_node(m_current_node);
        auto it = current->neighbors.find(m_bb.target_node);
        if (it == current->neighbors.end()) return;

        float cost = it->second;
        m_move_progress += 0.5f; // 【交替掩护】：为了生存，速度只有全速的一半！
        m_bb.ammo -= 1;          // 后撤也需要消耗弹药进行压制

        std::cout << "  [本能+执行] Squad " << m_id << " 扔出烟雾弹，正在【交替掩护撤退】！进度: " << m_move_progress << "/" << cost << "，弹药: " << m_bb.ammo << "\n";

        if (m_move_progress >= cost) {
            m_current_node = m_bb.target_node;
            m_move_progress = 0.0f;
            m_bb.has_macro_order = false;
            std::cout << "[战报] Squad " << m_id << " 成功突围，抵达节点 " << m_current_node << "！\n";
        }
    }
    void SquadEntity::calculate_route(const WorldMap& map) {
        m_path_queue.clear();
        if (m_current_node == m_bb.final_destination) return;

        std::queue<uint32_t> frontier;
        frontier.push(m_current_node);
        std::unordered_map<uint32_t, uint32_t> came_from;
        came_from[m_current_node] = m_current_node;

        bool found = false;
        while (!frontier.empty()) {
            uint32_t current = frontier.front();
            frontier.pop();

            if (current == m_bb.final_destination) {
                found = true;
                break;
            }

            auto node_ptr = map.get_node(current);
            if (node_ptr) {
                for (const auto& pair : node_ptr->neighbors) {
                    uint32_t next_node = pair.first;
                    if (came_from.find(next_node) == came_from.end()) {
                        frontier.push(next_node);
                        came_from[next_node] = current;
                    }
                }
            }
        }

        if (found) {
            uint32_t curr = m_bb.final_destination;
            std::vector<uint32_t> temp_path;
            while (curr != m_current_node) {
                temp_path.push_back(curr);
                curr = came_from[curr];
            }
            // 倒序压入队列，形成起步到终点的路线
            for (int i = temp_path.size() - 1; i >= 0; --i) {
                m_path_queue.push_back(temp_path[i]);
            }
        }
    }
}
