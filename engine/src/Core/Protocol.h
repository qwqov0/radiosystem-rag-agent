#pragma once
#include <cstdint>

namespace MilSim {

    // ==========================================
    // 【新增】：多维战术指令集 (密码本)
    // ==========================================
    enum class CommandType : uint8_t {
        NONE = 0,
        MOVE = 1,       // 常规行军：前往目标节点
        ATTACK = 2,     // 强攻：不顾伤亡，火力压制
        DEFEND = 3,     // 驻防：停止移动，就地展开防御
        RETREAT = 4     // 撤退：交替掩护，撤向安全节点
    };

    // ==========================================
    // 战术总线数据包 (严格保持 40 字节，与 Python 的 struct.pack 对应)
    // ==========================================
#pragma pack(push, 1)
    struct RadioPacket {
        uint64_t packet_id;      // 8 字节: 时间戳或包序列号
        uint32_t sender_id;      // 4 字节: 发送者 ID (0 代表统帅部)
        uint32_t receiver_id;    // 4 字节: 接收部队 ID
        uint8_t  command_code;   // 1 字节: 指令类型 (对应 CommandType)
        uint8_t  padding1[7];    // 7 字节: 内存对齐填充
        uint32_t target_node;    // 4 字节: 目标节点 ID
        uint8_t  padding2[12];   // 12 字节: 扩展槽位/填充
    };
#pragma pack(pop)

}