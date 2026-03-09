"""
agent/generate_combination_report.py

Generate a report of all user+job story combinations for review.
This helps identify nonsensical combinations that should be blocked.

Usage:
    python -m agent.generate_combination_report > combinations_report.txt
"""

import sys
from pathlib import Path
from typing import List, Dict, Set
import logging

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.user_stories import UserStoryParser
from agent.job_stories import JobStoryParser
from agent.story_compatibility import (
    is_compatible, 
    COMPATIBLE_USERS_FOR_JOB,
    filter_compatible_combinations
)

logging.basicConfig(level=logging.WARNING)


def generate_combination_report(
    user_stories_path: Path = None,
    job_stories_path: Path = None,
    output_format: str = 'detailed'  # 'detailed', 'matrix', 'blocked_only'
):
    """
    Generate a report of all user+job combinations.
    
    Args:
        user_stories_path: Path to personas.yaml
        job_stories_path: Path to job_stories.yaml
        output_format: Report format
    """
    # Load stories
    user_parser = UserStoryParser(user_stories_path)
    job_parser = JobStoryParser(job_stories_path)
    
    user_story_ids = user_parser.list_available_stories()
    job_story_ids = job_parser.list_available_stories()
    
    print("="*100)
    print("AGENT COMBINATION REPORT")
    print("="*100)
    print(f"\nUser Stories: {len(user_story_ids)}")
    print(f"Job Stories: {len(job_story_ids)}")
    print(f"Total Possible Combinations: {len(user_story_ids) * len(job_story_ids)}")
    print("="*100)
    
    # Get compatible combinations
    compatible = filter_compatible_combinations(user_story_ids, job_story_ids)
    blocked = []
    
    for user in user_story_ids:
        for job in job_story_ids:
            if (user, job) not in compatible:
                blocked.append((user, job))
    
    print(f"\n✅ ALLOWED Combinations: {len(compatible)}")
    print(f"❌ BLOCKED Combinations: {len(blocked)}")
    print(f"📊 Filter Efficiency: {len(blocked) / (len(user_story_ids) * len(job_story_ids)) * 100:.1f}% blocked")
    
    if output_format == 'detailed':
        print_detailed_report(user_story_ids, job_story_ids, compatible, blocked)
    elif output_format == 'matrix':
        print_matrix_report(user_story_ids, job_story_ids, compatible)
    elif output_format == 'blocked_only':
        print_blocked_report(blocked)
    
    # Check for missing whitelists
    print("\n" + "="*100)
    print("⚠️  JOBS WITHOUT WHITELISTS (allowing ALL users - may be wrong!)")
    print("="*100)
    
    missing_whitelists = []
    for job in job_story_ids:
        if job not in COMPATIBLE_USERS_FOR_JOB:
            missing_whitelists.append(job)
            # Count how many users this allows
            count = sum(1 for u in user_story_ids if is_compatible(u, job))
            print(f"  ⚠️  {job}: Allowing {count}/{len(user_story_ids)} users (NO WHITELIST!)")
    
    if not missing_whitelists:
        print("  ✅ All jobs have whitelists defined!")
    else:
        print(f"\n  🚨 {len(missing_whitelists)} jobs missing whitelists - URGENT!")


def print_detailed_report(user_story_ids, job_story_ids, compatible, blocked):
    """Print detailed breakdown by job type."""
    print("\n" + "="*100)
    print("DETAILED BREAKDOWN BY JOB TYPE")
    print("="*100)
    
    for job in sorted(job_story_ids):
        print(f"\n📋 JOB: {job}")
        print("-"*100)
        
        # Get allowed users for this job
        allowed_users = [u for u in user_story_ids if is_compatible(u, job)]
        blocked_users = [u for u in user_story_ids if not is_compatible(u, job)]
        
        print(f"  ✅ ALLOWED ({len(allowed_users)}):")
        for user in sorted(allowed_users):
            print(f"      - {user}")
        
        if blocked_users:
            print(f"  ❌ BLOCKED ({len(blocked_users)}):")
            for user in sorted(blocked_users):
                print(f"      - {user}")


def print_matrix_report(user_story_ids, job_story_ids, compatible):
    """Print matrix view."""
    print("\n" + "="*100)
    print("COMPATIBILITY MATRIX")
    print("="*100)
    print("\nLegend: ✅ = Allowed, ❌ = Blocked\n")
    
    # Header
    print(f"{'USER STORY':<30}", end='')
    for job in job_story_ids:
        print(f"{job[:15]:<17}", end='')
    print()
    print("-" * (30 + len(job_story_ids) * 17))
    
    # Rows
    for user in user_story_ids:
        print(f"{user:<30}", end='')
        for job in job_story_ids:
            symbol = "✅" if is_compatible(user, job) else "❌"
            print(f"{symbol:<17}", end='')
        print()


def print_blocked_report(blocked):
    """Print only blocked combinations."""
    print("\n" + "="*100)
    print("BLOCKED COMBINATIONS (Review these - are they correct?)")
    print("="*100)
    
    for user, job in sorted(blocked):
        print(f"  ❌ {user} + {job}")


def print_nonsensical_candidates(user_story_ids, job_story_ids):
    """
    Print combinations that LOOK nonsensical but are currently allowed.
    This helps identify missing whitelist entries.
    """
    print("\n" + "="*100)
    print("🚨 POTENTIALLY NONSENSICAL (But Currently Allowed!)")
    print("="*100)
    print("Review these - should they be blocked?\n")
    
    # Heuristics for nonsensical combinations
    nonsensical_patterns = [
        ('tourist', ['freight', 'delivery', 'waste', 'construction', 'warehouse']),
        ('budget_student', ['freight', 'hgv', 'truck', 'construction']),
        ('disabled_commuter', ['freight', 'hgv', 'truck', 'construction']),
        ('concerned_parent', ['freight', 'waste', 'hgv', 'construction']),
        ('freight_operator', ['tourist', 'shopping', 'leisure', 'scenic']),
        ('delivery_driver', ['tourist', 'leisure', 'scenic']),
    ]
    
    for user, job_keywords in nonsensical_patterns:
        if user not in user_story_ids:
            continue
        
        for job in job_story_ids:
            # Check if job contains any nonsensical keywords
            if any(keyword in job.lower() for keyword in job_keywords):
                if is_compatible(user, job):
                    print(f"  🚨 {user} + {job} ← ALLOWED but looks wrong!")


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Generate agent combination report')
    parser.add_argument('--format', choices=['detailed', 'matrix', 'blocked_only'], 
                       default='detailed', help='Report format')
    parser.add_argument('--user-stories', type=Path, help='Path to personas.yaml')
    parser.add_argument('--job-stories', type=Path, help='Path to job_stories.yaml')
    
    args = parser.parse_args()
    
    generate_combination_report(
        user_stories_path=args.user_stories,
        job_stories_path=args.job_stories,
        output_format=args.format
    )
    
    # Also print nonsensical candidates
    if args.format == 'detailed':
        user_parser = UserStoryParser(args.user_stories)
        job_parser = JobStoryParser(args.job_stories)
        print_nonsensical_candidates(
            user_parser.list_available_stories(),
            job_parser.list_available_stories()
        )