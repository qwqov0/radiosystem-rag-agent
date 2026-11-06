#include "Core/RadioBus.h"

// 必须包裹在命名空间内！
namespace MilSim {

    // 注意这里必须是 RadioBus::ScheduledMessage::
    bool RadioBus::ScheduledMessage::operator<(const ScheduledMessage& other) const {
        return delivery_tick > other.delivery_tick;
    }

    // 注意这里必须是 RadioBus::
    void RadioBus::push_message(const RadioPacket& packet, uint64_t current_tick, uint64_t delay_ticks) {
        ScheduledMessage scheduled_msg;
        scheduled_msg.delivery_tick = current_tick + delay_ticks;
        scheduled_msg.packet = packet;
        m_message_heap.push(scheduled_msg);
    }

    // 注意这里必须是 RadioBus::
    std::vector<RadioPacket> RadioBus::fetch_ready_messages(uint64_t current_tick) {
        std::vector<RadioPacket> ready_msgs;
        while (!m_message_heap.empty() && m_message_heap.top().delivery_tick <= current_tick) {
            ready_msgs.push_back(m_message_heap.top().packet);
            m_message_heap.pop();
        }
        return ready_msgs;
    }

    // 注意这里必须是 RadioBus::
    size_t RadioBus::get_in_flight_count() const {
        return m_message_heap.size();
    }

} // namespace MilSim 结束