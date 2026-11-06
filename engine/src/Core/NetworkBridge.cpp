#include "Core/NetworkBridge.h"
#include "Core/WorldMap.h"
#include <iostream>

#ifdef _WIN32
#include <winsock2.h>
#include <ws2tcpip.h>
#endif

namespace MilSim {

    // 1. 构造函数：注入地图引用 m_map
    NetworkBridge::NetworkBridge(RadioBus& bus, const WorldMap& map)
        : m_bus(bus), m_map(map), m_running(false), m_active_client_socket(0) {
#ifdef _WIN32
        WSADATA wsaData;
        WSAStartup(MAKEWORD(2, 2), &wsaData);
#endif
    }

    NetworkBridge::~NetworkBridge() {
        stop_server();
#ifdef _WIN32
        WSACleanup();
#endif
    }

    void NetworkBridge::start_server(int port) {
        m_running = true;
        m_worker_thread = std::thread(&NetworkBridge::network_worker_loop, this, port);
    }

    void NetworkBridge::network_worker_loop(int port) {
#ifdef _WIN32
        SOCKET server_fd = socket(AF_INET, SOCK_STREAM, 0);
        sockaddr_in address;
        address.sin_family = AF_INET;
        address.sin_addr.s_addr = INADDR_ANY;
        address.sin_port = htons(port);

        bind(server_fd, (struct sockaddr*)&address, sizeof(address));
        listen(server_fd, 1);

        while (m_running) {
            SOCKET client_socket = accept(server_fd, nullptr, nullptr);
            if (client_socket == INVALID_SOCKET) continue;

            std::cout << "[网络] 大模型指挥官已上线！数据链路已接通。\n";
            m_active_client_socket = client_socket;

            // 【修复点 1】：不带参数，直接调用
            broadcast_map();

            while (m_running) {
                char buffer[1024] = {0};
                int valread = recv(client_socket, buffer, sizeof(buffer), 0);

                if (valread > 0 && valread >= sizeof(RadioPacket)) {
                    RadioPacket incoming;
                    memcpy(&incoming, buffer, sizeof(RadioPacket));

                    {
                        std::lock_guard<std::mutex> lock(m_bus_mutex);
                        m_bus.push_message(incoming, 0, 0);
                    }
                } else if (valread == 0 || valread == SOCKET_ERROR) {
                    std::cout << "[网络] 大模型指挥官已断开连接。\n";
                    m_active_client_socket = 0;
                    closesocket(client_socket);
                    break;
                }
            }
        }
        closesocket(server_fd);
#endif
    }

    // 【修复点 2】：函数签名无参
    void NetworkBridge::broadcast_map() {
        if (m_active_client_socket == 0) return;

        json map_json;
        map_json["type"] = "MAP_DATA";

        // 【修复点 3】：使用 m_map.get_all_nodes()
        for (const auto& pair : m_map.get_all_nodes()) {
            uint32_t id = pair.first;
            const auto& node = pair.second;

            json n;
            n["id"] = id;
            n["x"] = node.x;
            n["y"] = node.y;
            n["type"] = static_cast<int>(node.terrain);
            map_json["nodes"].push_back(n);

            for (const auto& edge : node.neighbors) {
                if (id < edge.first) {
                    // 【修复点 4】：使用 json::array() 包装
                    json edge_arr;               // 明确创建一个空的 JSON 数组
                    edge_arr.push_back(id);          // 压入整数起点
                    edge_arr.push_back(edge.first);  // 压入整数终点
                    edge_arr.push_back(edge.second); // 压入浮点数代价
                    map_json["edges"].push_back(edge_arr); // 把组装好的数组塞进总 JSON 里
                }
            }
        }

        std::string payload = map_json.dump() + "\n";
#ifdef _WIN32
        send(m_active_client_socket, payload.c_str(), payload.length(), 0);
#endif
    }

    void NetworkBridge::broadcast_telemetry(uint64_t tick, const std::map<uint32_t, SquadEntity>& entities) {
        if (m_active_client_socket == 0) return;

        json root;
        root["type"] = "TELEMETRY";
        root["tick"] = tick;

        for (const auto& [id, squad] : entities) {
            root["entities"].push_back(squad.to_json());
        }

        std::string payload = root.dump() + "\n";
#ifdef _WIN32
        send(m_active_client_socket, payload.c_str(), payload.length(), 0);
#endif
    }

    void NetworkBridge::stop_server() {
        m_running = false;
        if (m_worker_thread.joinable()) {
            m_worker_thread.detach();
        }
    }

    std::vector<RadioPacket> NetworkBridge::fetch_safe(uint64_t current_tick) {
        std::lock_guard<std::mutex> lock(m_bus_mutex);
        return m_bus.fetch_ready_messages(current_tick);
    }
}