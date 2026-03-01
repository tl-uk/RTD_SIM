from events.event_bus_safe import SafeEventBus
from events.event_types import PolicyChangeEvent
from agent.story_driven_agent import StoryDrivenAgent

bus = SafeEventBus()

agent = StoryDrivenAgent(
    user_story_id='commuter_cost_conscious',
    job_story_id='commute_flexible',
    origin=(55.9533, -3.1883),
    dest=(55.9500, -3.1800),
    agent_id='test_agent'
)

# Register and subscribe
bus.register_agent('test_agent', lat=55.9533, lon=-3.1883)
agent.subscribe_to_events(bus)
bus.start_listening()

# Publish event
event = PolicyChangeEvent('carbon_tax', 50, 100, 55.9533, -3.1883)
bus.publish(event)

import time
time.sleep(0.5)

print(f"Perceived: {agent.get_perceived_policies()}")
# Should show: {'carbon_tax': 100.0}

bus.close()