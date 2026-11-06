#pragma once
#include <vector>
#include <map>
#include <cstdint>

namespace MilSim {

    enum class TerrainType : uint8_t {
        URBAN = 0,    // 城镇：掩护高，无线电干扰中
        FOREST = 1,   // 森林：移动慢，无线电干扰强
        PLAINS = 2,   // 平原：移动快，无线电信号极佳
        HILL = 3      // 山地：视野好，信号中转站
    };

    struct MapNode {
        uint32_t id;
        float x, y; // 用于在 UI 上渲染的参考坐标
        TerrainType terrain;
        
        // 邻居节点列表：ID -> 移动代价 (Cost)
        // 比如从节点 A 到节点 B，走公路 Cost 是 1.0，走泥地是 5.0
        std::map<uint32_t, float> neighbors; 
    };

    class WorldMap {
    private:
        std::map<uint32_t, MapNode> m_nodes;

    public:
        void add_node(uint32_t id, float x, float y, TerrainType t);
        void add_connection(uint32_t from, uint32_t to, float cost);
        
        // 获取两个节点间的距离（物理距离，用于计算无线电延迟）
        float get_distance(uint32_t node_a, uint32_t node_b) const;
        
        // 核心接口：获取从 A 到 B 的移动步长
        const MapNode* get_node(uint32_t id) const;
        const std::map<uint32_t, MapNode>& get_all_nodes() const {
            return m_nodes;
        }
    };
}