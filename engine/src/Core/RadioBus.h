#pragma once
#include <queue>
#include <vector>
#include "Protocol.h"

namespace MilSim {

    class RadioBus {
    private:
        // 【架构师细节】：将 ScheduledMessage 藏在类内部的 private 中。
        // 外界连这个结构体的存在都不需要知道，极度封装。
        struct ScheduledMessage {
            uint64_t delivery_tick;
            RadioPacket packet;

            // 运算符重载的声明
            bool operator<(const ScheduledMessage& other) const;
        };

        // 底层容器
        std::priority_queue<ScheduledMessage> m_message_heap;

    public:
        RadioBus() = default;

        // 仅提供对外接口的声明（契约）
        void push_message(const RadioPacket& packet, uint64_t current_tick, uint64_t delay_ticks);
        std::vector<RadioPacket> fetch_ready_messages(uint64_t current_tick);
        size_t get_in_flight_count() const;
    };

}