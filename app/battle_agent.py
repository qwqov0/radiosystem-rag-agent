"""Public commander entry points; v3 remains available for comparison."""
from battle_agent_v3 import distances, scripted_orders
from battle_commander import decide as legacy_decide

def decide(obs,memory,mode='memory'):
 if obs.get('own_mission'):
  from mission_commander import decide as mission_decide
  return mission_decide(obs,memory,mode)
 return legacy_decide(obs,memory,mode)

__all__ = ['decide', 'distances', 'scripted_orders']
