#include "Core/WorldMap.h"
#include <cmath>

namespace MilSim {

    void WorldMap::add_node(uint32_t id, float x, float y, TerrainType t) {
        // 使用聚合初始化，邻居列表默认为空
        m_nodes[id] = {id, x, y, t, {}};
    }

    void WorldMap::add_connection(uint32_t from, uint32_t to, float cost) {
        // 军工级校验：确保两个节点都存在
        if (m_nodes.count(from) && m_nodes.count(to)) {
            m_nodes[from].neighbors[to] = cost;
            m_nodes[to].neighbors[from] = cost; // 双向连通图
        }
    }

    float WorldMap::get_distance(uint32_t node_a, uint32_t node_b) const {
        if (!m_nodes.count(node_a) || !m_nodes.count(node_b)) return 9999.0f; // 极远距离
        
        float dx = m_nodes.at(node_a).x - m_nodes.at(node_b).x;
        float dy = m_nodes.at(node_a).y - m_nodes.at(node_b).y;
        return std::sqrt(dx * dx + dy * dy);
    }

    const MapNode* WorldMap::get_node(uint32_t id) const {
        auto it = m_nodes.find(id);
        if (it != m_nodes.end()) return &(it->second);
        return nullptr;
    }
}