#include <iostream>
#include "Battle/BattleWorld.h"
int main() {
    MilSim::BattleWorld world;
    std::string line;
    while (std::getline(std::cin, line)) {
        try {
            if (line.size() > 262144) throw std::runtime_error("request_too_large");
            std::cout << world.handle(MilSim::BattleJson::parse(line)).dump() << std::endl;
        } catch (const std::exception& e) {
            std::cout << MilSim::BattleJson({{"type", "ERROR"}, {"message", e.what()}}).dump() << std::endl;
        }
    }
}
