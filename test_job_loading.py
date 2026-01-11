# test_job_loading.py
from agent.job_stories import JobStoryParser

parser = JobStoryParser()  # Auto-detects directory
stories = parser.list_available_stories()

print(f"Loaded {len(stories)} stories:")
for story_id in stories[:5]:
    print(f"  - {story_id}")

# Test loading individual story
story = parser.load_from_yaml('gig_economy_delivery')
print(f"\nLoaded: {story.story_id}")
print(f"Vehicle type: {story.parameters.get('vehicle_type')}")