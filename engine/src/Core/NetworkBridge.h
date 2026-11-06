#pragma once
#include <thread>
#include <atomic>
#include <mutex>
#include <map>
#include <vector>
#include <nlohmann/json.hpp>
#include "Core/RadioBus.h"
#include "Entities/SquadEntity.h"

using json = nlohmann::json;

namespace MilSim {

    // 前向声明，告诉编译器有这个类，不需要在这里 include
    class WorldMap;

    class NetworkBridge {
    private:
        RadioBus& m_bus;
        const WorldMap& m_map;           // 【核心修复】：将地图作为常量引用保存在网桥中
        std::thread m_worker_thread;
        std::atomic<bool> m_running;
        std::mutex m_bus_mutex;

        std::atomic<uint64_t> m_active_client_socket;

        void network_worker_loop(int port);

    public:
        // 【核心修复】：构造函数合同更新，接收 bus 和 map
        NetworkBridge(RadioBus& bus, const WorldMap& map);
        ~NetworkBridge();

        void start_server(int port = 5555);
        void stop_server();

        std::vector<RadioPacket> fetch_safe(uint64_t current_tick);

        // 【核心修复】：广播地图不再需要传参，直接使用内部保存的 m_map
        void broadcast_map();

        // 广播实体战况快照
        void broadcast_telemetry(uint64_t tick, const std::map<uint32_t, SquadEntity>& entities);
    };
}